"""웹 화면의 요약·종합 보고서(2026-10-09 사용자) — 입력 1개 = 요약, 2개 이상 = 종합, 요청사항 반영."""

import json
import re
from pathlib import Path

import pytest

from doc2report.transform import llm_polish
from doc2report.web import jobs as jobs_mod
from doc2report.web.jobs import JobRunner, _pages

ROOT = Path(__file__).resolve().parents[1]
DOC1 = (ROOT / "samples/synthesis/set_A/A1_핵심부품_수급현황.txt").read_text(encoding="utf-8")
DOC3 = (ROOT / "samples/synthesis/set_A/A3_재고비용_대응계획.txt").read_text(encoding="utf-8")


@pytest.fixture
def fake_llm(monkeypatch):
    """원문 문장 번호를 읽어 한 줄짜리 정상 보고서를 돌려주는 가짜 LLM. 받은 지시문·메시지를 기록한다."""
    calls = []

    def answer(system, user):
        calls.append((system, user))
        if "[출력 형식" not in system:          # 줄 맞춤용 표현 줄임 등 다른 호출
            return ""
        sentences = dict(re.findall(r"\[(\d+)\] (?:[□\-∙※*→①-⑳] )?(.+)", user))
        n = next(k for k, s in sentences.items() if "28주" in s or "26주" in s)
        text = "리드타임 : 28주" if "28주" in sentences[n] else "리드타임 : 26주 (전년 동기 18주)"
        return json.dumps({"title": "RF 매칭 모듈 공급 현황", "lines": [
            {"m": "1.", "text": "현 황", "src": [int(n)]},
            {"m": "□", "text": text, "src": [int(n)]}], "dropped": []}, ensure_ascii=False)

    monkeypatch.setattr(llm_polish, "ask_json", answer)
    monkeypatch.setattr(llm_polish, "ask_chat", answer)
    monkeypatch.setattr(jobs_mod, "llm_status", lambda: {"configured": True})
    return calls


def _payload(texts, **options):
    return {"inputs": [{"type": "text", "text": t, "title": f"문서{i}"} for i, t in enumerate(texts, 1)],
            "options": {"task": "synthesize", "preset": "formal", "date": "today", **options}}


def test_one_input_is_summarized(tmp_path, fake_llm):
    job = JobRunner(tmp_path / "out", tmp_path / "up").run_sync(_payload([DOC1]))
    assert job.state == "done", job.error
    r = job.result
    assert r["task"] == "synthesize" and r["kind"] == "요약" and r["mode"] == "rewrite"
    assert r["files"][0]["name"].endswith(".docx") and r["stem"].endswith("RF_매칭_모듈_공급_현황")
    assert "분량" in r["summary"] and "수치왜곡 0" in r["summary"]     # 첫 문장의 숫자를 왜곡으로 잘못 세지 않는다
    assert "긴 문서 1개입니다" in fake_llm[0][0]


def test_web_has_no_request_box_and_ignores_stale_request(tmp_path, fake_llm):
    """2026-10-09 사용자: 요청사항은 해석이 어긋나(경과를 과하게 줄이고 엉뚱한 항목을 표로) 웹에서 뺐다 — 예전 화면이 보내도 무시한다."""
    from pathlib import Path as P
    static = P(jobs_mod.__file__).parent / "static"
    assert "syn-request" not in (static / "index.html").read_text(encoding="utf-8")
    assert "syn-request" not in (static / "app.js").read_text(encoding="utf-8")
    job = JobRunner(tmp_path / "out", tmp_path / "up").run_sync(_payload([DOC1, DOC3], request="경과는 최소한으로", pages="2-3"))
    assert job.state == "done", job.error
    r = job.result
    assert r["kind"] == "종합" and r["pages"] == "2-3" and "request" not in r
    system, user = fake_llm[0]
    assert "[사용자 요청사항" not in system and "경과는 최소한으로" not in user


def test_synthesis_needs_llm(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs_mod, "llm_status", lambda: {"configured": False})
    job = JobRunner(tmp_path / "out", tmp_path / "up").run_sync(_payload([DOC1]))
    assert job.state == "error" and "LLM" in job.error


def test_runs_are_capped_and_stop_when_clean(tmp_path, fake_llm):
    job = JobRunner(tmp_path / "out", tmp_path / "up").run_sync(_payload([DOC1], runs=9))
    assert job.state == "done", job.error
    tries = [m for m in job.messages if "보고서 쓰는 중" in m]
    assert tries and tries[0].endswith("걸릴 수 있음") and "(1/3회)" in tries[0]


def test_request_is_trimmed_and_capped():
    from doc2report.synthesis import MAX_REQUEST_CHARS, clean_request
    assert clean_request("  a\n\n  b  ") == "a\n  b"
    assert len(clean_request("가" * 5000)) == MAX_REQUEST_CHARS
    assert clean_request(None) == ""


@pytest.mark.parametrize("value, expected", [("1-2", (1, 2)), ("3", (3, 3)), ("3-5", (3, 5)), ("", (1, 2)),
                                             ("9-1", (1, 2)), ("abc", (1, 2))])
def test_pages_option(value, expected):
    assert _pages(value, (1, 2)) == expected


def test_screen_has_task_switch_and_page_options():
    html = (ROOT / "src/doc2report/web/static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "src/doc2report/web/static/app.js").read_text(encoding="utf-8")
    assert 'name="task" value="synthesize"' in html and 'id="syn-pages"' in html
    assert 'task: radio("task")' in js
