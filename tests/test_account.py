"""사용자 등록 — 토큰은 사용자 폴더에 봉인해 보관, 화면에는 끝 4자리만, 서버는 열쇠·Host로 잠근다
(2026-09-30 사용자: git으로 팀에 공유 — 각자 토큰, 도용 방지)."""

from __future__ import annotations

import json
import os
import platform
import threading
import urllib.error
import urllib.request

import pytest

from doc2report import account
from doc2report.web import server as srv

TOKEN = "PAT-secret-value-1234abcd"


def _form(**extra):
    return {"name": "홍길동", "confluence_url": "https://wiki.example/rest/api/",
            "confluence_token": TOKEN, "llm_base_url": "http://llm.example:8000/v1",
            "llm_model": "thinkingcap", **extra}


def test_saved_file_has_no_plain_token_and_round_trips(monkeypatch):
    for env in account.ENV_KEYS.values():
        monkeypatch.delenv(env, raising=False)
    acc = account.update(_form(), None)
    account.save(acc)
    raw = account.path().read_text(encoding="utf-8")
    assert TOKEN not in raw and "confluence_token" not in json.loads(raw)["values"]
    assert str(account.path()).startswith(os.environ["DOC2REPORT_HOME"])  # 저장소 폴더가 아니라 사용자 폴더
    loaded = account.load()
    assert loaded.values["confluence_token"] == TOKEN and loaded.name == "홍길동"


def test_blank_secret_keeps_the_old_one_and_new_token_resets_verification():
    acc = account.update(_form(), None)
    acc.verified_as = "홍길동 (hong)"
    same = account.update({"name": "홍길동", "confluence_token": ""}, acc)
    assert same.values["confluence_token"] == TOKEN and same.verified_as == "홍길동 (hong)"
    changed = account.update({"name": "홍길동", "confluence_token": "another-token-9999"}, acc)
    assert changed.verified_as == ""  # 토큰이 바뀌면 주인을 다시 확인해야 한다
    with pytest.raises(ValueError):
        account.update({"name": " "}, None)
    with pytest.raises(ValueError):
        account.update({"name": "a", "llm_base_url": "http://x/v1"}, None)  # 모델명 없음


def test_apply_overrides_script_env_and_delete_restores_it(monkeypatch):
    monkeypatch.setitem(account._ORIGINAL_ENV, "CONFLUENCE_API_TOKEN", "from-script")
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", "from-script")
    acc = account.update(_form(), None)
    account.save(acc)
    account.apply(acc)
    assert os.environ["CONFLUENCE_API_TOKEN"] == TOKEN
    summary = account.summary(acc)
    assert summary["confluence"]["secret"] == "…abcd" and summary["confluence"]["source"] == "등록 사용자"
    assert TOKEN not in json.dumps(summary)
    account.delete()
    assert os.environ["CONFLUENCE_API_TOKEN"] == "from-script" and not account.path().exists()


@pytest.mark.skipif(platform.system() != "Windows", reason="DPAPI는 Windows에만 있다")
def test_windows_dpapi_seal():
    sealed = account._seal(TOKEN)
    assert sealed.startswith("dpapi:") and account._unseal(sealed) == TOKEN


# ── 서버: 열쇠·Host·등록 API ────────────────────────────────────────────


@pytest.fixture
def locked_server(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "confluence_whoami", lambda: "홍길동 (hong.gd)")
    server, app = srv.create_server("127.0.0.1", 0, tmp_path / "out", access_key="k" * 40)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", server.server_address[1], app
    server.shutdown()
    server.server_close()
    account.apply(None)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _req(url, *, body=None, cookie=None, host=None):
    headers = {"X-Doc2Report": "1", "Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    if host:
        headers["Host"] = host
    data = json.dumps(body).encode() if body is not None else None
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(urllib.request.Request(url, data=data, headers=headers), timeout=10) as res:
            return res.status, res.headers, res.read()
    except urllib.error.HTTPError as err:
        return err.code, err.headers, err.read()


def test_without_key_only_the_page_and_version_are_served(locked_server):
    base, _, _ = locked_server
    assert _req(base + "/")[0] == 200  # 화면은 떠야 잠김 안내를 보여 준다
    status, _, body = _req(base + "/api/status")
    assert json.loads(body) == {"version": srv.API_VERSION, "locked": True}
    assert _req(base + "/api/profiles")[0] == 401
    assert _req(base + "/api/convert", body={"inputs": []})[0] == 401
    assert _req(base + "/api/account", body=_form())[0] == 401


def test_key_link_sets_cookie_and_unlocks(locked_server):
    base, port, _ = locked_server
    assert _req(base + "/?k=wrong")[0] == 200  # 틀린 열쇠는 무시(잠긴 화면)
    status, headers, _ = _req(base + "/?k=" + "k" * 40)
    assert status == 302 and headers["Location"] == "/"
    cookie = headers["Set-Cookie"].split(";")[0]
    assert cookie.startswith(f"d2r_key_{port}=") and "HttpOnly" in headers["Set-Cookie"]
    data = json.loads(_req(base + "/api/status", cookie=cookie)[2])
    assert "account" in data and not data["account"]["registered"]


def test_foreign_host_header_is_rejected(locked_server):
    base, port, _ = locked_server
    cookie = f"d2r_key_{port}=" + "k" * 40
    assert _req(base + "/api/status", cookie=cookie, host=f"evil.example:{port}")[0] == 403
    assert _req(base + "/api/status", cookie=cookie, host=f"localhost:{port}")[0] == 200


def test_register_verify_and_delete_through_http(locked_server):
    base, port, app = locked_server
    cookie = f"d2r_key_{port}=" + "k" * 40
    status, _, body = _req(base + "/api/account", body=_form(), cookie=cookie)
    data = json.loads(body)
    assert status == 200 and data["account"]["confluence"]["verified_as"] == "홍길동 (hong.gd)"
    st = json.loads(_req(base + "/api/status", cookie=cookie)[2])
    assert st["account"]["name"] == "홍길동" and st["llm"]["model"] == "thinkingcap"
    assert TOKEN not in json.dumps(st)  # 토큰은 화면으로 돌아가지 않는다
    assert json.loads(_req(base + "/api/account/delete", body={}, cookie=cookie)[2])["ok"]
    assert app.account is None and not account.path().exists()


def test_shutdown_for_takeover_still_works_without_key(locked_server):
    base, port, _ = locked_server
    assert srv._take_over(port) == "stopped"
