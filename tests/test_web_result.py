"""결과 화면 정리(2026-10-12 사용자): 문서 + 확인이 필요한 항목만 보이고, 나머지는 작업 기록 파일에."""

import re
from pathlib import Path

from doc2report.web.attention import classify
from doc2report.web.jobs import REPORT_SUFFIX, JobRunner

STATIC = Path(__file__).resolve().parents[1] / "src" / "doc2report" / "web" / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
JS = (STATIC / "app.js").read_text(encoding="utf-8")

# 실제 파이프라인이 남기는 형태의 메모(문구는 코드의 notes.append 그대로)
BENIGN = [
    "글꼴(바탕체) 파일이 없어 고정폭 모델(한글 1em·영문/숫자/공백 0.5em, 원숫자·※·→ 같은 기호는 1em 추정)로 줄 맞춤함 — Word에서 줄바꿈 위치 확인 필요",
    "표 1 위치: right 정렬, 왼쪽 끝 0.0mm(윗줄 글자 시작), 폭 170.0mm",
    "표 1: 표 글자 크기 12pt → 11pt 하향",
    "표 2: 열 3: 글자 크기를 10pt로 열 전체 통일",
    "구조 보정: 대안 비교 표의 행·열을 바꿈(대안이 열, 장점·단점 등이 행)",
    "규칙 교정(서술체 → 개조식): '확보하지 못하였습니다' → '확보하지 못하였음'",
    "날짜에 요일 붙임: 10.15 → 10.15(수)",
    "자동 판단: 제목·말머리가 있는 문단이 적어 말머리를 새로 붙임",
    "[요약] 여러 번 실행(2회) 후 1번째 결과 채택 — 남은 문제 점수: 1번째 0, 2번째 1",
    "[요약] LLM 구조 응답 1차 실패: JSON을 찾지 못함",
    "지면에 여유가 있어(약 73% 쪽) 단락 간격과 행 높이를 넉넉히 적용함",
    "생략한 원문 문장 [3]: 그건 그렇고 점심은 뭘 먹을지",
    "수치 누락 줄 단위 보강: '인원 12명' → '인원 : 12명'",
    "내용 누락 보강: 문장 [4] — 정산기간 → '정산기간 : 월 단위'",
    "주석 2개를 텍스트 상자로 넣음 (윗줄 아래에 띄움 — Word에서 위치 확인)",
    "연결 페이지 '하위 문서'를 함께 불러옴 (id=123)",
]


def test_benign_notes_are_hidden_but_counted():
    items, hidden = classify(BENIGN)
    assert items == [] and hidden == len(BENIGN)


def test_important_notes_become_plain_sentences():
    notes = [
        "LLM 요약에 실패해 원문 문장을 그대로 늘어놓은 기본 구조로 만들었습니다 — 요약·재구성이 아닙니다",
        "[요약] 사실 검증 실패 → 원문 문장으로 대체(문장 끝만 규칙으로 개조식, 숫자 1개)",
        "[요약] 사실 검증 실패 → 원문 문장으로 대체(문장 끝만 규칙으로 개조식, 날짜 1개)",
        "[요약] 수치 누락(인용한 문장 [7] 기준): 12, 30 — 입사 12명",
        "[요약] 이해 불가 의심(고치지 못함): 3번째 줄 — 주체가 없음",
        "[요약] 내용 누락 의심(보강 실패): 문장 [4] — 정산기간",
        "'하위 문서'을(를) 불러오지 못함: 403",
        "첨부파일 내려받기 실패(a.png): 시간 초과",
        "PDF 만들기 실패 — Word 문서만 저장함: Word 없음",
        "표 2: 한 쪽보다 커서 쪽 사이 잘림을 막지 못함(행은 중간에서 안 잘림)",
    ]
    items, hidden = classify(notes)
    texts = [i["text"] for i in items]
    assert items[0]["level"] == "bad" and "원문 문장을 그대로 늘어놓았습니다" in texts[0]       # 가장 심각한 것이 앞
    assert any("사실이 달라질 우려" in t and "2곳" in t for t in texts)                      # 같은 종류는 건수로 묶는다
    assert any("수치가 보고서에 빠졌을 수" in t for t in texts)
    assert any("이해가 어렵거나 내용이 빠졌을 수 있는 곳이 2곳" in t for t in texts)
    assert any("불러오지 못한 것이 2건" in t for t in texts)
    assert any("PDF 변환에 실패" in t for t in texts) and any("한 쪽보다 큰 표" in t for t in texts)
    assert len(items) == 7 and hidden == 0
    assert not any("[" in t or "src" in t for t in texts)                                   # 내부 표기가 새지 않는다


def test_unknown_failure_notes_are_not_hidden():
    # 새 메모 유형이 생겨도 실패·누락을 뜻하면 숨기지 않는다("기타 확인")
    items, hidden = classify(["새 점검 X 실패: 알 수 없는 사유", "그냥 참고 정보", "새 점검 Y 누락 의심"])
    assert [i["text"].startswith("기타 확인:") for i in items] == [True, True] and hidden == 1


def test_other_items_are_capped():
    items, _ = classify([f"새 점검 {n} 실패" for n in range(7)])
    assert len(items) == 4 and "4건 더" in items[-1]["text"]


def _paste(text):
    return {"inputs": [{"type": "text", "text": text, "title": "시험 보고"}],
            "options": {"task": "convert", "preset": "formal", "formats": ["md"]}}


def test_job_result_has_attention_and_always_writes_work_log(tmp_path):
    job = JobRunner(tmp_path / "out", tmp_path / "up").run_sync(_paste("1. 배경\n□ 내용입니다\n- 세부"))
    assert job.state == "done", job.error
    r = job.result
    assert isinstance(r["attention"], list) and isinstance(r["hidden_notes"], int)
    assert [f["kind"] for f in r["files"]] == ["docx", "md", "report"]
    log = (tmp_path / "out" / f"{r['stem']}{REPORT_SUFFIX}.md").read_text(encoding="utf-8")
    for heading in ("# 작업 기록 —", "## 확인이 필요한 항목", "## 변환 상세", "## 진행 기록"):
        assert heading in log
    assert "서식 변환" in log and "문서 만드는 중" in log                                    # 진행 기록이 파일에 남는다


def test_work_log_is_saved_even_if_report_option_is_off(tmp_path):
    payload = _paste("1. 배경\n□ 내용입니다")
    payload["options"]["report"] = False                                                    # 예전 화면이 보내던 값
    job = JobRunner(tmp_path / "out", tmp_path / "up").run_sync(payload)
    assert [f["kind"] for f in job.result["files"]][-1] == "report"


def test_empty_input_is_flagged_in_attention(tmp_path):
    job = JobRunner(tmp_path / "out", tmp_path / "up").run_sync(_paste("​\n  \n"))
    assert job.state == "done"
    assert any("변환할 내용이 없습니다" in a["text"] for a in job.result["attention"])


def test_job_json_has_stage_fields(tmp_path):
    job = JobRunner(tmp_path / "out", tmp_path / "up").run_sync(_paste("1. 배경\n□ 내용"))
    data = job.to_json()
    assert data["stage"] == "save" and [k for k, _ in data["stages"]] == ["read", "build", "save"]
    assert data["detail"] == "완료"


def test_screen_hides_developer_details():
    # 화면에는 문서·확인 항목·작업 기록 링크만 — 예전 노출 항목(핵심 요약·메모·문구 수정 표)이 다시 들어오지 않게
    for gone in ("핵심 요약", "레이아웃·입력 메모", "자동 판단 결과", "summary-box", "문구 수정 내역"):
        assert gone not in JS, gone
    assert 'id="out-report"' not in HTML and "작업 기록" in JS
    assert 'id="steps"' in HTML and "progress-log" not in HTML + JS
    assert re.search(r"API_VERSION = 15", JS)
