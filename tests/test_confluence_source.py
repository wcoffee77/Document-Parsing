"""sources/confluence.py — REST API 클라이언트.

실제 Confluence 서버 없이 httpx.MockTransport로 요청/응답을 가로채 검증한다.
확인할 것: 인증 헤더 선택(Cloud는 Basic, Server/DC는 Bearer), storage 본문·첨부파일
내려받기, 흔한 HTTP 오류의 메시지.
"""

from __future__ import annotations

import httpx
import pytest

from doc2report.sources.confluence import load_confluence, page_id_from_url


@pytest.mark.parametrize("url,expected", [
    ("https://회사.atlassian.net/wiki/spaces/TEAM/pages/123456/제목", "123456"),
    ("https://wiki.회사.com/pages/viewpage.action?pageId=7890", None),
    ("123456", "123456"),
    ("not-a-url", None),
])
def test_page_id_from_url(url, expected):
    assert page_id_from_url(url) == expected


def _patch_client(monkeypatch, handler) -> None:
    real_client = httpx.Client

    def fake_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr("doc2report.sources.confluence.httpx.Client", fake_client)


def _page_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={
        "title": "분기 개선 보고",
        "body": {"storage": {"value": "<h2>배경</h2><p>내용</p>"}},
    })


def _attachments_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"results": [
        {"title": "구조도.png", "_links": {"download": "/download/attachments/123/구조도.png"}},
    ]})


def test_cloud_auth_uses_basic_with_email_and_token(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFLUENCE_URL", "https://회사.atlassian.net/wiki")
    monkeypatch.setenv("CONFLUENCE_USERNAME", "me@company.com")
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", "cloud-token")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        if request.url.path.endswith("/child/attachment"):
            return _attachments_response(request)
        if request.url.path.endswith("/구조도.png"):
            return httpx.Response(200, content=b"PNGDATA")
        return _page_response(request)

    _patch_client(monkeypatch, handler)
    loaded = load_confluence("https://회사.atlassian.net/wiki/spaces/TEAM/pages/123/x")

    assert seen["auth"].startswith("Basic ")
    assert loaded.format == "confluence_storage"
    assert loaded.title == "분기 개선 보고"
    assert "<h2>배경</h2>" in loaded.text
    assert (loaded.base_dir / "구조도.png").read_bytes() == b"PNGDATA"


def test_server_dc_auth_uses_bearer_token_without_username(monkeypatch):
    monkeypatch.setenv("CONFLUENCE_URL", "https://wiki.company.com")
    monkeypatch.delenv("CONFLUENCE_USERNAME", raising=False)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", "server-pat")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        if request.url.path.endswith("/child/attachment"):
            return httpx.Response(200, json={"results": []})
        return _page_response(request)

    _patch_client(monkeypatch, handler)
    load_confluence("999")

    assert seen["auth"] == "Bearer server-pat"


@pytest.mark.parametrize("status,fragment", [
    (401, "인증 실패"),
    (403, "접근 권한"),
    (404, "찾을 수 없습니다"),
])
def test_http_errors_are_translated_to_clear_messages(monkeypatch, status, fragment):
    monkeypatch.setenv("CONFLUENCE_URL", "https://wiki.company.com")
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", "t")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="denied")

    _patch_client(monkeypatch, handler)
    with pytest.raises(RuntimeError, match=fragment):
        load_confluence("123")


def test_missing_credentials_raise_clear_error(monkeypatch):
    monkeypatch.delenv("CONFLUENCE_URL", raising=False)
    monkeypatch.delenv("CONFLUENCE_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="환경변수"):
        load_confluence("123")
