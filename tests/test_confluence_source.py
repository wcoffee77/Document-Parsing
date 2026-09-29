"""sources/confluence.py — REST API 클라이언트.

실제 Confluence 서버 없이 httpx.MockTransport로 요청/응답을 가로채 검증한다.
확인할 것: 인증 헤더 선택(Cloud는 Basic, Server/DC는 Bearer), storage 본문·첨부파일
내려받기, 흔한 HTTP 오류의 메시지.
"""

from __future__ import annotations

import base64
import json
import subprocess

import httpx
import pytest

from doc2report.sources.confluence import (
    _normalize_base_url,
    _ps_escape,
    load_confluence,
    page_id_from_url,
)


@pytest.mark.parametrize("url,expected", [
    ("https://회사.atlassian.net/wiki/spaces/TEAM/pages/123456/제목", "123456"),
    # Server/Data Center의 고전 URL 형식 — 한동안 못 잡던 버그였다(2026-09-28 발견·수정).
    ("https://wiki.회사.com/pages/viewpage.action?pageId=7890", "7890"),
    ("https://wiki.회사.com/pages/viewpage.action?spaceKey=TEAM&pageId=7890", "7890"),
    ("123456", "123456"),
    ("https://wiki.회사.com/x/AbCd", None),  # 단축 링크는 REST 한 번으로 못 푼다
    ("not-a-url", None),
])
def test_page_id_from_url(url, expected):
    assert page_id_from_url(url) == expected


@pytest.mark.parametrize("url,expected", [
    # 사내 REST 게이트웨이가 사용자 안내 주소 자체에 /rest/api를 포함하는 경우
    # (실제 사례: http://api.confluence.samsungds.net/rest/api/, 2026-09-28).
    ("http://api.confluence.samsungds.net/rest/api/", "http://api.confluence.samsungds.net"),
    ("http://api.confluence.samsungds.net/rest/api", "http://api.confluence.samsungds.net"),
    ("http://api.confluence.samsungds.net", "http://api.confluence.samsungds.net"),
    ("https://wiki.company.com/", "https://wiki.company.com"),
    ("https://x.atlassian.net/wiki", "https://x.atlassian.net/wiki"),
])
def test_normalize_base_url_accepts_either_form(url, expected):
    assert _normalize_base_url(url) == expected


def test_confluence_url_with_rest_api_suffix_does_not_duplicate_path(monkeypatch):
    """CONFLUENCE_URL에 /rest/api가 이미 있어도 요청 경로가 두 번 붙지 않는다."""
    monkeypatch.setenv("CONFLUENCE_URL", "http://api.confluence.samsungds.net/rest/api/")
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", "pat")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/child/attachment"):
            return httpx.Response(200, json={"results": []})
        seen["path"] = request.url.path
        return _page_response(request)

    _patch_client(monkeypatch, handler)
    load_confluence("999")

    assert seen["path"] == "/rest/api/content/999"


def test_unrecognized_url_fails_fast_with_a_clear_message(monkeypatch):
    monkeypatch.setenv("CONFLUENCE_URL", "https://wiki.company.com")
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", "t")
    with pytest.raises(RuntimeError, match="페이지 ID를 못 찾았습니다"):
        load_confluence("https://wiki.company.com/x/AbCd")


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


# ── PowerShell 대체 경로 (2026-09-29, 사내망에서 httpx가 403으로 막히는 문제) ──
#
# 실제 PowerShell을 실행하지 않고 subprocess.run만 흉내 낸다 — 여기서 검증하는 건
# "403을 받으면 PowerShell로 재시도하고, 그 결과를 올바르게 파싱하는가"이지 PowerShell
# 스크립트 자체의 정확성이 아니다(그건 Windows에서만 실측 가능).


def _fake_ps_run(monkeypatch, stdout: str = "", returncode: int = 0, stderr: str = ""):
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr("doc2report.sources.confluence.subprocess.run", fake_run)
    return calls


def _b64_json(data: dict) -> str:
    return base64.b64encode(json.dumps(data).encode("utf-8")).decode()


def test_403_on_windows_falls_back_to_powershell_and_succeeds(monkeypatch):
    monkeypatch.setenv("CONFLUENCE_URL", "https://wiki.company.com")
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", "pat")
    monkeypatch.setattr("doc2report.sources.confluence.platform.system", lambda: "Windows")

    def handler(request: httpx.Request) -> httpx.Response:
        # httpx는 뭘 보내든 사내망처럼 403으로 막는다.
        return httpx.Response(403, text="blocked by gateway")

    _patch_client(monkeypatch, handler)
    responses = iter([
        _b64_json({"title": "분기 보고", "body": {"storage": {"value": "<p>내용</p>"}}}),
        _b64_json({"results": []}),
    ])
    calls = _fake_ps_run(monkeypatch, stdout="")
    monkeypatch.setattr(
        "doc2report.sources.confluence.subprocess.run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout=next(responses), stderr=""),
    )

    loaded = load_confluence("123")

    assert "<p>내용</p>" in loaded.text
    assert any("PowerShell" in note for note in loaded.notes)


def test_forced_powershell_transport_never_calls_httpx(monkeypatch):
    monkeypatch.setenv("CONFLUENCE_URL", "https://wiki.company.com")
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", "pat")
    monkeypatch.setenv("DOC2REPORT_CONFLUENCE_TRANSPORT", "powershell")

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("httpx로 요청이 가면 안 된다 — transport가 강제돼 있음")

    _patch_client(monkeypatch, handler)
    responses = iter([
        _b64_json({"title": "t", "body": {"storage": {"value": "<p>x</p>"}}}),
        _b64_json({"results": []}),
    ])
    monkeypatch.setattr(
        "doc2report.sources.confluence.subprocess.run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout=next(responses), stderr=""),
    )

    loaded = load_confluence("123")
    assert "<p>x</p>" in loaded.text


def test_403_without_windows_does_not_try_powershell(monkeypatch):
    """이 테스트 환경(Linux)에서는 기본적으로 PowerShell을 시도하지 않는다."""
    monkeypatch.setenv("CONFLUENCE_URL", "https://wiki.company.com")
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", "pat")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="denied")

    _patch_client(monkeypatch, handler)
    calls = _fake_ps_run(monkeypatch)
    with pytest.raises(RuntimeError, match="접근 권한"):
        load_confluence("123")
    assert calls == []


def test_powershell_fallback_failure_still_surfaces_original_403(monkeypatch):
    monkeypatch.setenv("CONFLUENCE_URL", "https://wiki.company.com")
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", "pat")
    monkeypatch.setattr("doc2report.sources.confluence.platform.system", lambda: "Windows")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="blocked")

    _patch_client(monkeypatch, handler)
    _fake_ps_run(monkeypatch, returncode=1, stderr="powershell.exe를 찾을 수 없음")

    with pytest.raises(RuntimeError, match="접근 권한"):
        load_confluence("123")


def test_ps_escape_handles_embedded_single_quotes():
    assert _ps_escape("Bearer it's-a-token") == "Bearer it''s-a-token"
