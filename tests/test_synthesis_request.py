"""웹 실측(2026-10-09): '경과는 최소한으로, 대안은 표로 비교' 요청에서 비교 표가 빠지고 대응 계획이 줄었다 + 제목이 두 줄로 넘어감."""

import json

from doc2report.drafting import Line, Rewrite, SynthSpec, fit_title, review, title_char_hint, title_fits
from doc2report.synthesis import REQUEST_RULES, prepare, synthesize

from test_synthesis import DOC1, DOC2, _doc, _fake

REQUEST = "경과는 최소한으로, 대안은 표로 비교"


def test_request_mentioning_table_requires_a_table():
    docs = [_doc(DOC1, "d1"), _doc(DOC2, "d2")]
    assert prepare(docs, request=REQUEST).need_table == "요청사항에 표가 있음"
    assert prepare(docs).need_table == ""        # 요청도 비교표도 없으면 요구 안 함


def test_review_flags_missing_table_when_required():
    lines = [Line("1.", "현황", [1]), Line("□", "리드타임 : 28주", [1])]
    rewrite = Rewrite("보고", lines, [])
    sentences = ["리드타임이 28주다."]
    _, style = review(rewrite, sentences, "보고", 2026, synth=SynthSpec(need_table="요청사항에 표가 있음"))
    assert any("비교 표가 없음" in s for s in style)
    table = Line("표", "", [1], rows=[["구분", "A", "B"], ["가", "28주", "26주"]])
    _, style = review(Rewrite("보고", [lines[0], table], []), sentences, "보고", 2026, synth=SynthSpec(need_table="요청사항에 표가 있음"))
    assert not any("비교 표가 없음" in s for s in style)


def test_request_rules_limit_cuts_to_what_was_named():
    assert "그 말이 가리킨 부분에만" in REQUEST_RULES and "대응 계획" in REQUEST_RULES
    assert "반드시 {\"m\": \"표\"" in REQUEST_RULES
    system = prepare([_doc(DOC1, "d1"), _doc(DOC2, "d2")], request=REQUEST).system
    assert REQUEST in system


def test_llm_that_skips_the_table_is_asked_again():
    seen = []

    def reply(system, user):
        seen.append(user)
        lines = [{"m": "1.", "text": "현황", "src": [1]}, {"m": "□", "text": "리드타임 : 26주", "src": [1]}]
        if "비교 표가 없음" in user:
            lines.append({"m": "표", "rows": [["구분", "기존", "변경"], ["리드타임", "- 26주", "- 28주"]], "src": [1, 5]})
        return json.dumps({"title": "공급 현황", "lines": lines, "dropped": []}, ensure_ascii=False)

    result = synthesize([_doc(DOC1, "d1"), _doc(DOC2, "d2")], ask=_fake(reply), request=REQUEST)
    assert len(seen) >= 2 and "비교 표가 없음" in seen[1]
    assert "리드타임\t" in result.text      # 표가 들어감


def test_title_must_fit_on_one_line():
    assert title_fits("공급 현황 요약")
    long = "식각장비 RF 모듈 핵심부품 수급 리스크 대응을 위한 대체 공급사 검토 및 재고·비용 대응 계획 종합"
    assert not title_fits(long)
    assert 8 <= title_char_hint() <= 24


def test_long_title_is_shortened_by_llm_then_by_words():
    notes = []
    long = "식각장비 RF 모듈 핵심부품 수급 리스크 대응을 위한 대체 공급사 검토 및 재고·비용 대응 계획 종합"
    short = fit_title(long, lambda system, user: "RF 부품 수급 리스크 대응", notes)
    assert short == "RF 부품 수급 리스크 대응" and any("제목이 한 줄을 넘어 줄임" in n for n in notes)
    notes = []
    cut = fit_title(long, lambda system, user: long, notes)        # LLM이 못 줄이면 어절 단위로 자른다
    assert title_fits(cut) and cut and long.startswith(cut) and any("어절 단위" in n for n in notes)
    assert fit_title("짧은 제목", None, []) == "짧은 제목"


def test_review_flags_two_line_title_for_reask():
    long = "식각장비 RF 모듈 핵심부품 수급 리스크 대응을 위한 대체 공급사 검토 및 재고·비용 대응 계획 종합"
    rewrite = Rewrite(long, [Line("1.", "현황", [1]), Line("□", "리드타임 : 28주", [1])], [])
    _, style = review(rewrite, ["리드타임이 28주다."], long, 2026)
    assert any("title이 한 줄을 넘음" in s for s in style)
