"""설치·환경 진단 (2026-09-30 사용자: 팀원이 사내 PC 설치에서 고생하지 않게)."""

from __future__ import annotations

import subprocess
import sys

from doc2report import account, doctor


def test_doctor_runs_offline_and_reports_every_area(monkeypatch):
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", "super-secret-token-xyz")
    checks = doctor.run(network=False)
    text = doctor.report(checks)
    titles = " ".join(c.title for c in checks)
    for area in ("파이썬", "패키지", "Word 문서", "결과 저장 폴더", "PDF", "사용자", "포트"):
        assert area in titles, area
    assert "super-secret-token-xyz" not in text  # 진단 파일은 담당자에게 보내므로 토큰이 들어가면 안 된다
    assert text.splitlines()[-1].startswith("요약:")


def test_doctor_step_error_becomes_a_failure_line_not_a_crash():
    def broken():
        raise RuntimeError("boom")

    [check] = doctor._safe(broken)
    assert check.level == doctor.FAIL and "boom" in check.detail


def test_proxy_warning_when_llm_host_is_not_excepted(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://user:pw@squid.corp:8000")
    monkeypatch.setenv("DOC2REPORT_LLM_BASE_URL", "http://10.1.2.3:8000/v1")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    check = doctor._proxy()
    assert check.level == doctor.WARN and "10.1.2.3" in check.detail
    assert "pw" not in check.detail  # 프록시 주소의 계정·비밀번호는 가린다


def test_registered_llm_host_is_added_to_no_proxy(monkeypatch):
    monkeypatch.setitem(account._ORIGINAL_ENV, "NO_PROXY", "localhost")
    acc = account.update({"name": "a", "llm_base_url": "http://10.1.2.3:8000/v1", "llm_model": "m"}, None)
    account.apply(acc)
    try:
        import os

        assert os.environ["NO_PROXY"] == "localhost,10.1.2.3"
    finally:
        account.apply(None)
    import os

    assert os.environ["NO_PROXY"] == "localhost"


def test_python_dash_m_entry_point():
    out = subprocess.run([sys.executable, "-m", "doc2report", "--help"], capture_output=True, text=True,
                         env={**__import__("os").environ, "PYTHONPATH": "src", "PYTHONUTF8": "1"})
    assert out.returncode == 0 and "doctor" in out.stdout
