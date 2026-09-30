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


def test_powershell_fallback_is_noted_once_and_httpx_is_skipped_afterwards(monkeypatch):
    """페이지 + 첨부 목록 + 첨부 이미지마다 같은 안내가 리포트에 반복되던 문제(2026-09-29 사용자)
    — 한 번 막히면 나머지 요청은 처음부터 PowerShell로 가고 안내도 한 번만."""
    monkeypatch.setenv("CONFLUENCE_URL", "https://wiki.company.com")
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", "pat")
    monkeypatch.setattr("doc2report.sources.confluence.platform.system", lambda: "Windows")
    hits = []

    def handler(request: httpx.Request) -> httpx.Response:
        hits.append(str(request.url))
        raise httpx.ConnectError("CERTIFICATE_VERIFY_FAILED")

    _patch_client(monkeypatch, handler)
    responses = iter([
        _b64_json({"title": "t", "body": {"storage": {"value": "<p>x</p>"}}}),
        _b64_json({"results": [{"title": "a.png", "_links": {"download": "/download/a.png"}},
                               {"title": "b.png", "_links": {"download": "/download/b.png"}}]}),
        base64.b64encode(b"PNG-A").decode(),
        base64.b64encode(b"PNG-B").decode(),
    ])
    monkeypatch.setattr(
        "doc2report.sources.confluence.subprocess.run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout=next(responses), stderr=""),
    )

    loaded = load_confluence("123")

    assert len(hits) == 1  # 첫 요청만 httpx를 시도
    assert sum("PowerShell" in note for note in loaded.notes) == 1


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
    """Windows가 아니면 PowerShell을 시도하지 않는다(CI는 Windows에서도 돌므로 OS를 못 박는다)."""
    monkeypatch.setattr("doc2report.sources.confluence.platform.system", lambda: "Linux")
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


# ── SSL 인증서 문제 (2026-09-29, 사내 LLM이 진단: 사내 프록시 자체 CA를 certifi가 모름) ──


_CA_ENV_KEYS = ("CONFLUENCE_CA_BUNDLE", "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE")


def _clear_ca_env(monkeypatch) -> None:
    # 이 샌드박스 자체가 프록시용 SSL_CERT_FILE/REQUESTS_CA_BUNDLE을 미리 깔아 둬서
    # (에이전트 프록시 CA 번들), 그 값이 새어 들어오지 않게 테스트마다 먼저 지운다.
    for key in _CA_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


@pytest.mark.parametrize("env_key", _CA_ENV_KEYS)
def test_ca_bundle_env_var_is_used_when_file_exists(monkeypatch, tmp_path, env_key):
    """httpx는 REQUESTS_CA_BUNDLE을 자동으로 안 읽으므로 직접 확인해 verify=에 넘겨야 한다."""
    from doc2report.sources.confluence import _ssl_verify

    _clear_ca_env(monkeypatch)
    cert = tmp_path / "samsungsemi-prx.com.crt"
    cert.write_text("fake cert")
    monkeypatch.setenv(env_key, str(cert))

    notes: list[str] = []
    assert _ssl_verify(notes) == str(cert)
    assert any(env_key in note for note in notes)


def test_ca_bundle_env_var_pointing_to_missing_file_is_ignored(monkeypatch):
    from doc2report.sources.confluence import _ssl_verify

    _clear_ca_env(monkeypatch)
    monkeypatch.setenv("CONFLUENCE_CA_BUNDLE", "C:\\no\\such\\file.crt")
    notes: list[str] = []
    assert _ssl_verify(notes) is True
    assert any("찾을 수 없어" in note for note in notes)


def test_no_ca_bundle_env_defaults_to_true(monkeypatch):
    from doc2report.sources.confluence import _ssl_verify

    for key in ("CONFLUENCE_CA_BUNDLE", "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE"):
        monkeypatch.delenv(key, raising=False)
    notes: list[str] = []
    assert _ssl_verify(notes) is True
    assert notes == []


def test_ca_bundle_path_is_actually_passed_to_httpx_client(monkeypatch, tmp_path):
    """verify= 계산만 맞고 실제로 안 넘어가면 소용없으니 httpx.Client 생성 자체를 확인한다."""
    cert = tmp_path / "ca.crt"
    cert.write_text("fake cert")
    monkeypatch.setenv("CONFLUENCE_URL", "https://wiki.company.com")
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", "pat")
    monkeypatch.setenv("CONFLUENCE_CA_BUNDLE", str(cert))

    seen = {}
    real_client = httpx.Client

    def fake_client(*args, **kwargs):
        seen["verify"] = kwargs.get("verify")
        kwargs["transport"] = httpx.MockTransport(
            lambda r: httpx.Response(200, json={"results": []})
            if r.url.path.endswith("/child/attachment") else _page_response(r)
        )
        return real_client(*args, **kwargs)

    monkeypatch.setattr("doc2report.sources.confluence.httpx.Client", fake_client)
    load_confluence("123")

    assert seen["verify"] == str(cert)


def test_ssl_error_on_windows_falls_back_to_powershell(monkeypatch):
    """SSL 인증서 검증 실패는 403과 달리 응답 없이 예외로 터진다 — 따로 잡아야 한다."""
    monkeypatch.setenv("CONFLUENCE_URL", "https://wiki.company.com")
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", "pat")
    monkeypatch.setattr("doc2report.sources.confluence.platform.system", lambda: "Windows")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("SSL: CERTIFICATE_VERIFY_FAILED")

    _patch_client(monkeypatch, handler)
    responses = iter([
        _b64_json({"title": "t", "body": {"storage": {"value": "<p>ssl 우회 성공</p>"}}}),
        _b64_json({"results": []}),
    ])
    monkeypatch.setattr(
        "doc2report.sources.confluence.subprocess.run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout=next(responses), stderr=""),
    )

    loaded = load_confluence("123")
    assert "ssl 우회 성공" in loaded.text
    assert any("SSL/연결 오류" in note for note in loaded.notes)


def test_ssl_error_without_windows_raises_clear_message_with_ca_bundle_hint(monkeypatch):
    monkeypatch.setenv("CONFLUENCE_URL", "https://wiki.company.com")
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", "pat")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("SSL: CERTIFICATE_VERIFY_FAILED")

    _patch_client(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="CONFLUENCE_CA_BUNDLE"):
        load_confluence("123")


def test_ssl_error_with_powershell_also_failing_reports_both(monkeypatch):
    monkeypatch.setenv("CONFLUENCE_URL", "https://wiki.company.com")
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", "pat")
    monkeypatch.setattr("doc2report.sources.confluence.platform.system", lambda: "Windows")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("SSL: CERTIFICATE_VERIFY_FAILED")

    _patch_client(monkeypatch, handler)
    _fake_ps_run(monkeypatch, returncode=1, stderr="powershell.exe를 찾을 수 없음")

    with pytest.raises(RuntimeError, match="PowerShell.*대체 시도도 실패"):
        load_confluence("123")


def test_powershell_fallback_never_puts_the_token_on_the_command_line(monkeypatch):
    """명령 문자열은 스크립트 블록 로깅·프로세스 목록에 남을 수 있어 토큰은 환경변수로만 넘긴다."""
    from doc2report.sources.confluence import _powershell_get

    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"], seen["env"] = cmd, kwargs.get("env") or {}
        return subprocess.CompletedProcess(cmd, 0, stdout=base64.b64encode(b"ok").decode(), stderr="")

    monkeypatch.setattr("doc2report.sources.confluence.subprocess.run", fake_run)
    assert _powershell_get("https://wiki/x", {"Authorization": "Bearer top-secret-pat"}) == b"ok"
    assert "top-secret-pat" not in " ".join(seen["cmd"])
    assert "$env:D2R_HEADER_0" in seen["cmd"][-1]
    assert seen["env"]["D2R_HEADER_0"] == "Bearer top-secret-pat"
