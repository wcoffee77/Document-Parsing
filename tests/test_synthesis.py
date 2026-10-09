"""다문서 종합(D단계, 2026-10-08) — 입력 풀기, 지시문, 사실 검증, LLM 없을 때 기본 구조."""

import json
import re
import tempfile
from pathlib import Path

import pytest

from doc2report.drafting import REWRITE_SYSTEM
from doc2report.pipeline import load_document
from doc2report.synthesis import (SYNTH_RULES, SourceDoc, flatten, order_docs, prepare, split_typed_marker,
                                  synthesize)

ROOT = Path(__file__).resolve().parents[1]

DOC1 = """부품 수급 현황
2026. 9. 12
1. 현 황
 □ 리드타임 : 26주 (전년 동기 18주)
   - 8월 전력 제한 영향
 □ 재고 : 안전재고 대비 2.5주분
2. 계획
 □ 대체 공급사 검증 착수 (9월 중)
"""
DOC2 = """부품 대응 계획
2026. 10. 2
1. 현 황
 □ A사 리드타임 : 28주로 연장
 □ 재고 : 안전재고 대비 2.1주분
2. 대응
 □ 긴급 발주 : 200개
 ※ 재무 승인 필요
"""


def _doc(text, name):
    path = Path(tempfile.mkdtemp()) / f"{name}.txt"
    path.write_text(text, encoding="utf-8")
    loaded, _ = load_document(str(path))
    return flatten(loaded, name)


def _fake(reply):
    calls = []

    def ask(system, user):
        calls.append((system, user))
        return reply if isinstance(reply, str) else reply(system, user)
    ask.calls = calls
    return ask


def test_typed_markers_are_split_into_mark_depth_and_body():
    assert split_typed_marker(" □ 재고 : 180개") == ("□", "재고 : 180개", 0)
    assert split_typed_marker("   - 세부 내용") == ("-", "세부 내용", 1)
    assert split_typed_marker("     ∙ 더 세부") == ("∙", "더 세부", 2)
    assert split_typed_marker("1. 현 황") == ("1.", "현 황", 0)
    assert split_typed_marker("-5% 개선")[0] == ""            # 공백 없는 하이픈은 말머리가 아니라 음수
    assert split_typed_marker("그냥 문장") == ("", "그냥 문장", 0)


def test_flatten_keeps_sections_as_context_not_sentences():
    doc = _doc(DOC1, "d1")
    kinds = [k for k, *_ in doc.items]
    assert doc.title == "부품 수급 현황" and doc.date == "2026. 9. 12"
    assert kinds.count("절") == 2 and kinds.count("문장") == 4
    assert all(not text.startswith(("□", "-")) for _, _, _, text in doc.items)


def test_prepare_orders_by_date_and_numbers_sentences_across_documents():
    newer, older = _doc(DOC2, "d2"), _doc(DOC1, "d1")
    prep = prepare([newer, older])
    assert [name for name, _, _ in prep.ranges] == ["부품 수급 현황", "부품 대응 계획"]      # 날짜 오름차순
    assert prep.ranges[0][1] == 1 and prep.ranges[1][1] == prep.ranges[0][2] + 1
    assert prep.year == 2026 and "문서 2" in prep.user and "(2026. 10. 2)" in prep.user


def test_system_prompt_replaces_keep_everything_rule_with_synthesis_rules():
    prep = prepare([_doc(DOC1, "d1"), _doc(DOC2, "d2")], (1, 2))
    assert "정보를 빼지 않는다" in REWRITE_SYSTEM and "정보를 빼지 않는다" not in prep.system
    assert "가장 나중 문서의 값" in prep.system and "주제별로 새로 구성" in prep.system
    assert "{low}" not in prep.system and "{pages}" not in prep.system
    assert "[출력 형식" in prep.system                                # 형식 지시는 여전히 맨 끝


def _answer(prep):
    """LLM이 최신 값(28주, 2.1주분)만 쓰고 변화를 괄호로 남긴 정상 응답 — 문장 번호는 prepare가 정한 대로."""
    s = {text: i for i, text in enumerate(prep.sentences, 1)}
    find = lambda part: next(i for text, i in s.items() if part in text)  # noqa: E731
    return json.dumps({"title": "부품 공급 현황 및 대응", "lines": [
        {"m": "1.", "text": "현 황", "src": [find("26주"), find("28주")]},
        {"m": "□", "text": "리드타임 : 28주 (기존 26주)", "src": [find("26주"), find("28주")]},
        {"m": "□", "text": "재고 : 안전재고 대비 2.1주분", "src": [find("2.5주분"), find("2.1주분")]},
        {"m": "1.", "text": "대응", "src": [find("200개")]},
        {"m": "□", "text": "긴급 발주 200개 (재무 승인 必)", "src": [find("200개"), find("재무")]}],
        "dropped": [find("전력")]}, ensure_ascii=False)


def test_synthesis_uses_latest_values_and_does_not_demand_every_sentence():
    docs = [_doc(DOC1, "d1"), _doc(DOC2, "d2")]
    prep = prepare(docs)
    ask = _fake(_answer(prep))
    result = synthesize(docs, ask=ask, year=2026)
    assert result.mode == "rewrite" and len(ask.calls) == 1             # 한 번에 통과 — 빠진 문장 때문에 다시 묻지 않음
    assert "28주 (기존 26주)" in result.text
    assert any(n.startswith("종합: 원문 문장") for n in result.notes)
    assert not any("어느 줄의 src에도" in n for n in result.notes)


def test_invented_number_is_still_caught_and_replaced_by_source_sentence():
    docs = [_doc(DOC1, "d1"), _doc(DOC2, "d2")]
    prep = prepare(docs)
    bad = json.loads(_answer(prep))
    bad["lines"][1]["text"] = "리드타임 : 30주 (기존 26주)"                    # 원문에 없는 30주
    result = synthesize(docs, ask=_fake(json.dumps(bad, ensure_ascii=False)), year=2026)
    assert "30주" not in result.text
    assert any("원문 문장으로 대체" in n for n in result.notes)


def test_without_llm_falls_back_to_document_by_document_concatenation():
    def broken(system, user):
        raise RuntimeError("LLM 설정 없음")
    result = synthesize([_doc(DOC1, "d1"), _doc(DOC2, "d2")], ask=broken, year=2026)
    assert result.mode == "fallback" and not result.used_llm
    assert "1. 부품 수급 현황" in result.text and "2. 부품 대응 계획" in result.text
    assert any("규칙 기본 구조" in n for n in result.notes)


def test_single_document_is_summarized_with_its_own_prompt():
    """긴 문서 하나를 요약해 새 보고서로(2026-10-09 사용자: 자주 쓰는 기능) — 같은 엔진, 문서 간 병합 문구 대신 핵심 선별 문구."""
    docs = [_doc(DOC1, "d1")]
    prep = prepare(docs)
    assert "긴 문서 1개입니다" in prep.system and "여러 개(날짜 오름차순" not in prep.system
    assert "문서 1개," in prep.user
    ids = {s: i for i, s in enumerate(prep.sentences, 1)}
    find = lambda part: next(i for s, i in ids.items() if part in s)   # noqa: E731
    reply = json.dumps({"title": "부품 수급 요약", "lines": [
        {"m": "1.", "text": "현 황", "src": [find("26주")]},
        {"m": "□", "text": "리드타임 : 26주 (전년 동기 18주)", "src": [find("26주")]}], "dropped": []}, ensure_ascii=False)
    result = synthesize(docs, ask=_fake(reply), year=2026)
    assert result.mode == "rewrite" and "26주 (전년 동기 18주)" in result.text
    assert len(prepare([_doc(DOC1, "a"), _doc(DOC2, "b")]).system) != len(prep.system)   # 두 문서용 지시문은 따로


def test_no_documents_is_an_error():
    with pytest.raises(ValueError):
        synthesize([], ask=_fake("{}"))


def test_cli_has_summarize_and_synthesize_needs_two():
    from typer.testing import CliRunner

    from doc2report.cli import app
    runner = CliRunner()
    assert runner.invoke(app, ["summarize", "--help"]).exit_code == 0
    result = runner.invoke(app, ["synthesize", "only_one.docx"])
    assert result.exit_code != 0 and "summarize" in result.output


def test_undated_documents_keep_input_order():
    a = SourceDoc("가", "", None)
    b = SourceDoc("나", "2026. 1. 1", None)
    assert [d.title for d in order_docs([b, a])] == ["나", "가"]


def test_synthesis_prompt_example_is_not_taken_from_sample_documents():
    """종합 예시가 평가용 샘플(정답 포함)과 겹치면 평가가 오염된다 — 8자 창으로 확인."""
    example = SYNTH_RULES[SYNTH_RULES.index("[종합 예시]"):]
    plain = re.sub(r"\s", "", example)
    corpus = ""
    for path in list((ROOT / "samples" / "drafting").glob("*.txt")) + list((ROOT / "samples" / "synthesis").rglob("*.txt")):
        corpus += re.sub(r"\s", "", path.read_text(encoding="utf-8"))
    windows = {plain[i:i + 8] for i in range(len(plain) - 8)}
    shared = [w for w in windows if w in corpus and not re.search(r"[\d{}\[\]\":,]", w)]
    assert not shared, shared[:5]
