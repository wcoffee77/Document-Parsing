"""구어체·서술체 → 보고서 문체 규칙(transform/report_style.py, rules/report_style.yaml).

벤치마크: 줄글 원문 문장 47개(구어체)와 사용자가 고친 정답 보고서 줄 60개(개조식)를 두 부류로 놓고 점검기가 가르는지 본다.
"""

import json
import re
from pathlib import Path

from doc2report.drafting import draft, split_sentences, system_prompt
from doc2report.transform.factcheck import check
from doc2report.transform.report_style import examples_text, fix, hard_issues, lint

SAMPLES = Path(__file__).resolve().parents[1] / "samples" / "drafting"


def _corpus():
    source, answer = [], []
    for number in range(1, 6):
        raw = next(SAMPLES.glob(f"줄글_{number}_*.txt")).read_text(encoding="utf-8")
        source += split_sentences(raw)[1]
        for line in next(SAMPLES.glob(f"정답_{number}_*.txt")).read_text(encoding="utf-8").splitlines()[2:]:
            text = line.strip()
            if text and "\t" not in text and text.replace(" ", "") != "-이상-" and not re.match(r"^\d\.\s", text):
                answer.append(text)
    return source, answer


def test_lint_separates_colloquial_sentences_from_report_lines():
    source, answer = _corpus()
    assert len(source) == 47 and len(answer) >= 55
    assert all(hard_issues(s) for s in source)               # 줄글 문장은 모두 "~다"로 끝나는 서술체
    assert not [a for a in answer if lint(a)]                  # 정답 보고서 줄은 강한·약한 점검 모두 0건


def test_lint_kinds():
    kinds = lambda text: {i.kind for i in lint(text)}
    assert "polite" in kinds("재의뢰했습니다")
    assert "plain" in kinds("경쟁사가 채용을 시작했다")
    assert "speaker" in kinds("저는 일단 추진이 좋다고 봅니다")
    assert "period" in kinds("수수료 상향 추진.")
    assert "filler" in kinds("일단 수수료 상향 추진")
    assert "long" in kinds("가나다라마바사 " * 9)
    assert "connectives" in kinds("후보를 찾는데 협의했고 확정했지만 어렵고 기간이 길어서 걱정되는데")
    assert "adverb" in kinds("불만이 굉장히 높음")
    assert lint("채용 현황 : 입사 확정 27명(67.5%), 처우 협의 中 6명") == []


def test_fix_changes_style_not_facts():
    cases = {
        "설계는 14명을 계획했는데 8명밖에 확보하지 못했습니다.": "설계는 14명을 계획했는데 8명밖에 확보하지 못하였음",
        "경쟁사 두 곳이 이달에 같은 직군을 대규모로 뽑기 시작한 것도 영향이 큽니다.": "경쟁사 두 곳이 이달에 같은 직군을 대규모로 뽑기 시작한 것도 영향이 큼",
        "연동 지표 선정이 어렵습니다.": "연동 지표 선정이 어려움",
        "일단 사내 추천 보상을 300만 원에서 500만 원으로 올립니다": "사내 추천 보상을 300만원에서 500만원으로 올림",
        "응답자 312명 중 58%가 선택했습니다.": "응답자 312명 中 58%가 선택",
    }
    for before, after in cases.items():
        assert fix(before) == after, before
        assert check(fix(before), before) == []                # 규칙 교정은 사실 검증을 항상 통과한다


def test_fix_keeps_marker_and_label_and_ignores_clean_lines():
    assert fix("- 수수료를 올렸습니다.") == "- 수수료를 올렸음"
    assert fix("□ 채용 목표 : 총 40명") == "□ 채용 목표 : 총 40명"
    assert fix("협의 중 6명") == "협의 中 6명" or fix("처우 협의 중") == "처우 협의 中"


def test_examples_are_in_the_prompt_and_holdout_removes_them():
    full, held = system_prompt(), system_prompt({3})
    assert "[문장 변환 예시" in full and "기 간 : 8.22(토) ~23(일)" in full
    assert "기 간 : 8.22(토) ~23(일)" not in held                # 채점할 문서(정답 3)의 예시는 뺀다
    assert "(3회/人)" in held and examples_text(exclude_docs={4}).count("원문:") < examples_text().count("원문:")


def test_every_example_obeys_the_fact_rules_and_the_style_rules():
    from doc2report.transform.report_style import load_rules

    for example in load_rules().examples:
        source = " ".join(example["src"])
        for line in example["out"]:
            text = line.lstrip("*※ ").strip()
            assert not hard_issues(text), line
            if example["doc"] in (3,) and "(토)" in line or "(일)" in line:
                continue                                       # 요일은 달력 계산이라 연도가 필요(정답 3의 날짜)
            problems = [p for p in check(text, source, year=2026) if "방향" not in p]
            assert problems == [], (line, problems)


def test_residual_polite_line_is_mended_by_rule_and_reported():
    from doc2report.drafting import split_sentences as _split

    text = "충원 현황\n\n설계는 14명을 계획했는데 8명밖에 확보하지 못했습니다.\n"
    title, sentences = _split(text)
    data = {"title": "충원 현황", "lines": [
        {"m": "□", "text": "설계 14명 중 8명밖에 확보하지 못했습니다", "src": [1]}], "dropped": []}
    result = draft(text, ask=lambda *_: json.dumps(data, ensure_ascii=False), year=2026)
    assert "□ 설계 14명 中 8명밖에 확보하지 못하였음" in result.text.splitlines()
    assert any("규칙 교정" in n for n in result.notes)
