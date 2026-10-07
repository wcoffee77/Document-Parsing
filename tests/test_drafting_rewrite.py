"""줄글 → 정식보고서 다듬기(B안, 2026-10-03 사용자): LLM이 말투를 다듬고 배열, 파이썬이 사실을 지킨다."""

import json
import re
from pathlib import Path

import pytest

from doc2report.drafting import draft, parse_rewrite, rewrite_text, tidy_labels
from doc2report.drafting import AUDIT_SYSTEM
from doc2report.transform.factcheck import check, missing_numbers

SAMPLES = Path(__file__).resolve().parents[1] / "samples" / "drafting"
TEXT1 = (SAMPLES / "줄글_1_충원현황.txt").read_text(encoding="utf-8")
TEXT2 = (SAMPLES / "줄글_2_유연근무검토.txt").read_text(encoding="utf-8")

# 정답 1(사용자가 직접 고친 보고서)을 LLM 응답 모양으로 옮긴 것 — 줄마다 근거 문장 번호를 붙였다.
ANSWER1 = {"title": "R&D 인력 충원 현황", "lines": [
    {"m": "□", "text": "채용 목표 : 총 40명", "src": [1]},
    {"m": "□", "text": "채용 현황(9월 말) : 입사 확정 27명(67.5%), 처우 협의 中 6명, 후보 탐색 中 7명", "src": [1, 2]},
    {"m": "※", "text": "전년도 동기 달성률 72%", "src": [2]},
    {"m": "-", "text": "직군별 세부 현황", "src": [3, 4]},
    {"m": "∙", "text": "공정 : 15명 中 12명 확보", "src": [3]},
    {"m": "∙", "text": "설계 : 14명 中 8명 확보", "src": [4]},
    {"m": "※", "text": "설계 직군 경우, 경력자 부족(공석 3개월 이상), 경쟁사(2개) 채용으로 난이도 高",
     "src": [5, 6]},
    {"m": "□", "text": "추진 방향", "src": [7, 8]},
    {"m": "-", "text": "헤드헌팅 수수료 상향 추진 (기존 25% → 30%)", "src": [7]},
    {"m": "*", "text": "금주 의뢰 완료", "src": [7]},
    {"m": "-", "text": "사내 추천 보상금 한시적 인상 검토 (기존 300만원 → 500만원)", "src": [7]},
    {"m": "→", "text": "설계 인력 4명 추가 채용 목표(~10.15일)", "src": [8]},
    {"m": "※", "text": "차주 경영진 보고時 구체적 대응 방안 및 지원책 논의 예정", "src": [8]}],
    "dropped": []}


def _answer(data):
    calls = []

    def ask(_system, user):
        if _system == AUDIT_SYSTEM:
            return '{"missing":[]}'
        calls.append(user)
        return json.dumps(data, ensure_ascii=False)
    return ask, calls


# ── 사실 검증기 ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("number", [1, 2, 3, 4, 5])
def test_factcheck_accepts_the_human_answers_except_invented_deadline(number):
    source = next(SAMPLES.glob(f"줄글_{number}_*.txt")).read_text(encoding="utf-8")
    answer = next(SAMPLES.glob(f"정답_{number}_*.txt")).read_text(encoding="utf-8").splitlines()
    flagged = [line for line in answer[2:] if line.strip() and not re.match(r"\d+\.", line.strip())
               and check(line, source, year=2026)]
    if number == 3:   # 정답 3의 "(~12월말)"은 원문에 없는 기한 — 사람은 넣을 수 있지만 도구는 막아야 한다
        assert len(flagged) == 1 and "12월말" in flagged[0]
    else:
        assert flagged == []


def test_factcheck_notation_changes_are_allowed():
    src = "10월 15일까지 4명, 300만 원에서 500만 원으로, 약 1억 2천만 원, 경쟁사 두 곳, 9월 둘째 주, 8월 22일부터 이틀간"
    assert check("기한 ~10.15일, 300만원 → 500만원, 1억 2천만원, 경쟁사(2개), 9월 2주차, 8.22(토) ~23(일)",
                 src, year=2026) == []


def test_factcheck_catches_changed_facts():
    src = "설계는 14명을 계획했는데 8명밖에 확보하지 못했습니다. 비용은 4억 원입니다. 9월 5일 확정 예정."
    assert any("숫자" in p for p in check("설계 14명 中 7명 확보", src))
    assert any("금액" in p for p in check("비용 5억원", src))
    assert any("요일" in p for p in check("9.5(금) 확정", src, year=2026))            # 2026-09-05는 토요일
    assert any("방향" in p for p in check("주거비 하락", "현지 주거비가 22% 올랐습니다")) # 올랐다 → 하락
    assert any("확정" in p for p in check("보상 인상 확정", "보상 인상안을 검토하고 있습니다"))
    assert any("한자" in p for p in check("인원 多", "인원이 많습니다"))
    assert any("영문" in p for p in check("KPI 반영", "평가에 반영"))


def test_missing_numbers_lists_what_the_report_left_out():
    assert missing_numbers("40명 중 27명, 7명은 탐색 중", "입사 확정 27명 / 총 40명") == ["7"]


def test_uncovered_numbers_flags_dropped_baselines_per_cited_sentence():
    from doc2report.transform.factcheck import uncovered_by_source

    sents = ["작년 재택근무 확대는 24%였고 올해는 31%입니다",
             "등급 비율은 S 10%, A 30%, B 50%, C 10%입니다",
             "작년 5,200만 원보다 500만 원 늘었습니다",
             "3천만 원 이상 지급"]
    lines = [([1], "재택근무 확대 31%"), ([2], "S 10% / A 30% / C 10%"),
             ([3], "500만원 증가"), ([4], "3,000만원 이상 지급")]
    got = uncovered_by_source(sents, lines)
    assert got == {1: ["24"], 2: ["50"], 3: ["5200"]}   # 4번은 3천만↔3,000만 같은 값이라 통과


def test_uncovered_numbers_ignores_dropped_sentences_and_accepts_other_lines():
    from doc2report.transform.factcheck import uncovered_by_source

    sents = ["작년 24%, 올해 31%", "비고 7명"]
    assert uncovered_by_source(sents, [([1], "작년 24%"), ([1], "올해 31%")]) == {}
    assert uncovered_by_source(sents, [([1], "작년 24%, 올해 31%")]) == {}   # 2번은 생략


# ── 다듬기 흐름 ───────────────────────────────────────────────────────────

def test_rewrite_uses_llm_lines_and_keeps_them_when_facts_check_out():
    ask, calls = _answer(ANSWER1)
    result = draft(TEXT1, ask=ask, year=2026)
    assert result.mode == "rewrite" and len(calls) == 1
    assert not [n for n in result.notes if "실패" in n]
    lines = result.text.splitlines()
    assert any(l.startswith("□ 채용 목표") and l.endswith(": 총 40명") for l in lines)
    assert "→ 설계 인력 4명 추가 채용 목표(~10.15일)" in lines
    assert "* 금주 의뢰 완료" in lines
    assert result.title == "R&D 인력 충원 현황"
    assert not any("수치 누락" in n for n in result.notes)   # 인용한 문장의 숫자는 모두 남음


def test_invented_fact_is_retried_then_replaced_by_the_original_sentence():
    bad = json.loads(json.dumps(ANSWER1, ensure_ascii=False))
    bad["lines"][5]["text"] = "설계 : 14명 中 9명 확보"            # 원문은 8명
    calls = []

    def ask(system, user):
        if system == AUDIT_SYSTEM:
            return '{"missing":[]}'
        calls.append((system, user))
        if "고칠 줄:" in user:
            return "설계 : 14명 中 9명 확보"          # 줄 단위 다시 쓰기에서도 끝내 틀리게 답함
        return json.dumps(bad, ensure_ascii=False)

    result = draft(TEXT1, ask=ask, year=2026)
    assert "[검증에서 걸린 것" in calls[1][1] and "9" in calls[1][1]            # 수정본 요청
    assert sum("고칠 줄:" in u for _, u in calls) == 2                            # 줄 단위 다시 쓰기 2회
    assert "9명" not in result.text
    assert "∙ 설계는 14명을 계획했는데 8명밖에 확보하지 못하였음" in result.text.splitlines()   # 원문 문장, 끝만 규칙으로 개조식
    assert any("원문 문장으로 대체" in n for n in result.notes)


def test_polite_endings_and_missing_sentences_ask_for_one_more_try():
    data = json.loads(json.dumps(ANSWER1, ensure_ascii=False))
    data["lines"][0]["text"] = "채용 목표는 총 40명입니다"
    data["lines"] = [line for line in data["lines"] if line["src"] != [8]]
    for line in data["lines"]:
        line["src"] = [i for i in line["src"] if i != 8]
    ask, calls = _answer(data)
    result = draft(TEXT1, ask=ask, year=2026)
    assert len(calls) == 2 and "습니다" in calls[1] and "[8]" in calls[1]
    assert any("생략한 원문 문장 [8]" in n for n in result.notes)


def test_bad_json_to_the_end_falls_back_to_rule_converted_sentences():
    ask, calls = _answer({"lines": [{"m": "?", "src": [1]}]})
    result = draft(TEXT1, ask=ask, year=2026)
    assert result.mode == "fallback"                       # 배치 모드(원문 서술체 그대로)로 가지 않는다
    assert "9월 말 기준으로 올해 R&D 경력 채용 계획 40명" in result.text      # 원문 문장 + 규칙 교정
    assert "습니다" not in result.text and any("형식 오류가 끝내" in n for n in result.notes)


def test_plain_text_answer_is_rescued_into_json():
    """2026-10-07 실측: LLM이 JSON 대신 'ㅁ 배경 및 이슈 - …' 같은 보고서 글로 답함 → 그 글을 JSON으로 옮겨 받는다."""
    good = json.dumps(ANSWER1, ensure_ascii=False)
    systems = []

    def ask(system, user):
        systems.append(system)
        if system == AUDIT_SYSTEM:
            return '{"missing":[]}'
        if system.startswith("당신은 보고서 정리 담당"):
            assert "ㅁ 채용 현황" in user                     # LLM이 쓴 글을 그대로 넘긴다
            return good
        return "ㅁ 채용 현황\n - 입사 확정 27명"

    result = draft(TEXT1, ask=ask, year=2026)
    assert result.mode == "rewrite" and any("JSON으로 옮김" in n for n in result.notes)
    assert not any("형식 오류" in n for n in result.notes)


def test_two_options_become_a_table_with_multiline_cells(tmp_path):
    data = {"title": "R&D 조직 유연근무제 확대 관련", "lines": [
        {"m": "1.", "text": "배경", "src": [1]},
        {"m": "□", "text": "R&D 조직 구성원(312명) 대상 설문결과, 근무시간 경직성 관련 불만 高", "src": [1, 2]},
        {"m": "-", "text": "출퇴근 시간 자율화(58%), 재택근무 확대(24%) 등 희망", "src": [2]},
        {"m": "※", "text": "現 시차출퇴근제는 시간 선택 폭이 1시간으로 체감 효과 작다는 의견", "src": [3]},
        {"m": "2.", "text": "검토 방안", "src": [4]},
        {"m": "표", "rows": [["구분", "(1안) 시차출퇴근제 시간 선택폭 확대\n(1시간 → 2시간)", "(2안) 선택적 근로시간제 도입"],
                             ["장점", "- 취업규칙 변경을 통해 즉시 시행 가능", "- 정산기간 기준 근로시간 관리 가능"],
                             ["단점", "- 유연성 확보 효과 제한적",
                              "- 근로기준법상 서면 합의 필요\n- 급여 시스템 개편 비용 발생(약 1억 2천만원)\n- 노조 협의 필요(내년 2분기 시행 可)"]],
         "src": [3, 5, 6, 7, 8]},
        {"m": "3.", "text": "추진 방향", "src": [9]},
        {"m": "□", "text": "1안 우선 추진, 2안은 법무 검토 및 노조 협의 거쳐 내년 상반기 도입 추진", "src": [9]},
        {"m": "※", "text": "법적 해석은 법무팀 확인 필요", "src": [10]}], "dropped": []}
    ask, _ = _answer(data)
    result = draft(TEXT2, ask=ask, year=2026)
    assert not [n for n in result.notes if "대체" in n], result.notes
    lines = result.text.splitlines()
    assert "1. 배 경" in lines and "2. 검토 방안" in lines and "3. 추진 방향" in lines   # 두 글자 절 제목은 띄운다
    assert any(line.startswith("장점\t") for line in lines)
    assert "<br>" in result.text

    from docx import Document as OpenDocx

    from doc2report.pipeline import convert_many

    src = tmp_path / "x_구조.txt"
    src.write_text(result.text, encoding="utf-8")
    out = tmp_path / "x.docx"
    convert_many([str(src)], out, "formal", title=result.title, section_titles=False)
    table = OpenDocx(str(out)).tables[0]
    cell = table.rows[2].cells[2]
    assert [p.text for p in cell.paragraphs if p.text.strip()][:2] == [
        "- 근로기준법상 서면 합의 필요", "- 급여 시스템 개편 비용 발생(약 1억 2천만원)"]


def test_label_tidy_spaces_two_letter_labels_and_aligns_colons():
    rewrite = parse_rewrite(json.dumps({"lines": [
        {"m": "-", "text": "리더십 진단/코칭 : 일대일 코칭", "src": [1]},
        {"m": "-", "text": "사업부장 멘토링 : 총 3개월간", "src": [1]},
        {"m": "-", "text": "기간 : 8.22", "src": [1]},
        {"m": "①", "text": "보조금 기준 상향 : 비용 발생", "src": [1]},
        {"m": "②", "text": "주거비 실비 지원 : 관리 부담", "src": [1]}]}, ensure_ascii=False), 1)
    tidy_labels(rewrite.lines)
    text = rewrite_text(rewrite).splitlines()
    assert text[0] == "- 리더십 진단/코칭 : 일대일 코칭"
    assert text[1] == "- 사업부장 멘토링  : 총 3개월간"          # 폭(전각 2칸) 맞춰 쌍점 세로 정렬
    assert text[2].startswith("- 기 간 ")                         # 두 글자 항목명은 띄운다
    from doc2report.drafting import _display_width
    assert len({_display_width(line.split(" : ")[0]) for line in text[:3]}) == 1
    assert text[3] == "① 보조금 기준 상향 : 비용 발생" and text[4] == "② 주거비 실비 지원 : 관리 부담"


def test_format_error_does_not_use_up_the_revision_chance():
    """2026-10-05 실측: 첫 응답이 JSON이 아니면 그 복구에 기회를 써서 사실 문제를 다시 고쳐 쓰게 못 했다."""
    bad = json.loads(json.dumps(ANSWER1, ensure_ascii=False))
    bad["lines"][5]["text"] = "설계 : 14명 中 9명 확보"
    replies = iter(["(설명만 있고 JSON 없음)", json.dumps(bad, ensure_ascii=False),
                    json.dumps(ANSWER1, ensure_ascii=False)])
    calls = []

    def ask(system, user):
        if system == AUDIT_SYSTEM:
            return '{"missing":[]}'
        calls.append(user)
        return next(replies)

    result = draft(TEXT1, ask=ask, year=2026)
    assert len(calls) == 3 and "[검증에서 걸린 것" in calls[2]      # 형식 오류 뒤에도 수정본을 요청했다
    assert "∙ 설계 : 14명 中 8명 확보" in result.text.splitlines()
    assert not any("원문 문장으로 대체" in n for n in result.notes)
    assert any("형식 오류 1회" in n and "응답" in n for n in result.notes)      # 진단: 응답 길이·앞부분


def test_line_repair_fixes_a_line_the_revision_missed():
    bad = json.loads(json.dumps(ANSWER1, ensure_ascii=False))
    bad["lines"][5]["text"] = "설계 : 14명 中 9명 확보"

    def ask(system, user):
        if "고칠 줄:" in user:
            return "설계 : 14명 中 8명 확보"
        return json.dumps(bad, ensure_ascii=False)

    result = draft(TEXT1, ask=ask, year=2026)
    assert "∙ 설계 : 14명 中 8명 확보" in result.text.splitlines()
    assert any("줄 단위 다시 쓰기로 해결" in n for n in result.notes)


def test_factcheck_catches_the_distortions_found_in_the_first_onprem_run():
    """2026-10-05 온프렘 실측(eval_1·5)에서 사람이 읽어 찾은 왜곡 4건 — 검증기가 모두 잡아야 하고, 바르게 고친 줄은 통과."""
    s8 = TEXT1.split("\n", 2)[2].split(". ")[-1]
    cases = [
        ("목표 미달 시 연말 목표 달성 어려움, 차주 경영진 보고 필요", s8, "가능성"),
        ("개인 부담액 : 연 3,000만원 이상 발생 사례 다수", "일부는 연 3천만 원 이상을 개인 부담하고 있습니다.", "일부↔다수"),
        ("A사 : 연차 물가 연동 조정", "A사는 매년 물가 연동으로 조정합니다.", "연차"),
        ("최종 비용은 환율 변동에 따라 상이", "최종 비용은 환율에 따라 달라질 수 있습니다.", "가능성"),
        ("아날로그 설계 경력자 부족으로 3개월 공석 2개", "경력자가 없어서 3개월 넘게 공석인 포지션이 두 개 있습니다.", "범위"),
    ]
    for line, source, kind in cases:
        assert any(kind in p for p in check(line, source)), (line, check(line, source))
    fixed = [
        ("목표 미달 시 연말 목표 달성 차질 우려", s8),
        ("개인 부담액 : 연 3,000만원 이상 발생 사례 일부", "일부는 연 3천만 원 이상을 개인 부담하고 있습니다."),
        ("최종 비용은 환율에 따라 변동 가능", "최종 비용은 환율에 따라 달라질 수 있습니다."),
        ("아날로그 설계 경력자 부족으로 3개월 이상 공석 2개", "경력자가 없어서 3개월 넘게 공석인 포지션이 두 개 있습니다."),
        ("연차 물가 연동 : 장기적 형평성 확보 가능하나 지표 선정 난이도 高",
         "매년 물가 연동으로 바꾸는 방법은 장기적으로 형평은 맞지만 연동 지표 선정이 어렵습니다."
         .replace("매년", "연차")),                                              # 양쪽을 다 옮긴 대비는 통과
        ("본업 부담 완화를 위해 팀장별 주 4시간 업무 조정 요청",
         "걱정되는 것은 과제 수행 기간에 본업 부담이 커질 수 있다는 점이라 팀장들에게 주당 4시간 정도 업무 조정을 요청할 계획입니다."),
    ]
    for line, source in fixed:
        assert check(line, source) == [], (line, check(line, source))


def test_repair_numbers_rewrites_the_line_until_missing_numbers_are_in():
    from doc2report.drafting import Line, Rewrite, _repair_numbers

    sents = ["예산은 코칭 4,500만 원과 워크숍 1,200만 원을 합쳐 5,700만 원입니다"]
    rw = Rewrite("t", [Line("-", "예산 : 5,700만원", [1])], [])
    seen = []

    def ask(_system, user):
        seen.append(user)
        return "- 예산 : 5,700만원 (코칭 4,500 + 워크숍 1,200)" if len(seen) == 2 else "예산 : 5,700만원"

    notes = _repair_numbers(rw, sents, ask, 2026)
    assert rw.lines[0].text == "예산 : 5,700만원 (코칭 4,500 + 워크숍 1,200)" and len(seen) == 2
    assert any("보강" in n for n in notes)


def test_repair_numbers_rejects_invented_numbers_and_keeps_line():
    from doc2report.drafting import Line, Rewrite, _repair_numbers

    sents = ["작년 5,200만 원보다 500만 원 늘었습니다"]
    rw = Rewrite("t", [Line("-", "500만원 증가", [1])], [])
    _repair_numbers(rw, sents, lambda *_: "작년 5,300만원 대비 500만원 증가", 2026)
    # LLM이 만든 5,300은 채택하지 않고, 원문 어구 그대로 괄호로 붙인다(2026-10-08: 빠져서는 안 되는 수치)
    assert "5,300" not in rw.lines[0].text and rw.lines[0].text == "500만원 증가 (작년 5,200만원)"


def test_review_flags_numeric_sentence_sent_to_dropped():
    from doc2report.drafting import Line, Rewrite, review

    sents = ["응답자 312명 중 58%가 선호", "소감 없음"]
    rw = Rewrite("t", [Line("-", "기타", [2])], [1])
    _, style = review(rw, sents, "t", 2026)
    assert any("dropped로 보냄" in s for s in style)


def test_audit_adds_missing_information_as_a_child_line():
    from doc2report.drafting import Line, Rewrite, _audit_content

    sents = ["설문에서 근무시간 경직성 불만이 높게 나왔습니다", "서면 합의가 필요하고 정산기간을 정해야 합니다"]
    rw = Rewrite("t", [Line("□", "근무시간 불만 高", [1]), Line("-", "서면 합의 필요", [2])], [])

    def ask(system, user):
        if system == AUDIT_SYSTEM:
            return '{"missing":[{"sent":2,"info":"정산기간 결정"}]}'
        return "정산기간 결정 필요"

    notes = _audit_content(rw, sents, ask, 2026)
    assert [l.text for l in rw.lines] == ["근무시간 불만 高", "서면 합의 필요", "정산기간 결정 필요"]
    assert rw.lines[2].m == "∙" and rw.lines[2].src == [2]
    assert any("보강" in n for n in notes)


def test_audit_rejects_unfaithful_repair_and_survives_bad_answers():
    from doc2report.drafting import Line, Rewrite, _audit_content

    sents = ["비용이 약 1억 2천만 원 들 것으로 보입니다"]
    rw = Rewrite("t", [Line("-", "비용 발생", [1])], [])
    notes = _audit_content(rw, sents, lambda s, u: '{"missing":[{"sent":1,"info":"금액"}]}' if s == AUDIT_SYSTEM else "비용 2억원", 2026)
    assert len(rw.lines) == 1 and any("보강 실패" in n for n in notes)
    rw2 = Rewrite("t", [Line("-", "비용 발생", [1])], [])
    assert any("건너뜀" in n for n in _audit_content(rw2, sents, lambda s, u: "아님", 2026))


def test_review_flags_over_compressed_report():
    from doc2report.drafting import Line, Rewrite, review

    sents = ["근로기준법상 서면 합의가 필요하고 정산기간과 총 근로시간을 정해야 하며 급여 시스템 개편 비용이 들 것으로 보입니다"]
    rw = Rewrite("t", [Line("-", "서면합의 필요", [1])], [])
    _, style = review(rw, sents, "t", 2026)
    assert any("과도하게 축약" in s for s in style)


def test_audit_rewrites_unclear_line_with_subject_and_reason():
    from doc2report.drafting import Line, Rewrite, _audit_content

    sents = ["프로젝트 마감 전후로 몰아서 일하는 R&D 특성에 더 잘 맞습니다"]
    rw = Rewrite("t", [Line("-", "몰아일 특성에 적합", [1])], [])

    def ask(system, user):
        if system == AUDIT_SYSTEM:
            return '{"missing":[],"unclear":[{"line":1,"sent":1,"why":"뜻 불분명"}]}'
        return "프로젝트 마감 전후 집중 근무하는 R&D 특성에 적합"

    notes = _audit_content(rw, sents, ask, 2026)
    assert rw.lines[0].text.startswith("프로젝트 마감") and any("풀어 씀" in n for n in notes)


# ── 2026-10-07 실측 후속: 형식 오류·줄임말·대안 표·지시문 오염 ─────────────────

def test_coined_words_catch_cut_and_paste_abbreviations_without_flagging_gold_answers():
    from doc2report.transform.factcheck import coined_words

    source = (SAMPLES / "줄글_2_유연근무검토.txt").read_text(encoding="utf-8")
    assert coined_words("정산기간 기준으로 프로젝트 몰아일 특성 적합", source) == ["몰아일"]
    assert coined_words("현행 시차출퇴근제 선택폭 1시간으로 체감 효과 작음", source) == []
    for number in range(1, 6):                      # 사용자 정답 보고서에서는 하나도 안 걸려야 한다
        src = next(SAMPLES.glob(f"줄글_{number}_*.txt")).read_text(encoding="utf-8")
        answer = next(SAMPLES.glob(f"정답_{number}_*.txt")).read_text(encoding="utf-8")
        assert all(not coined_words(line, src) for line in answer.splitlines()), number


def test_review_asks_for_table_when_source_compares_alternatives():
    from doc2report.drafting import Line, Rewrite, has_alternatives, review, split_sentences

    sents = split_sentences(TEXT2)[1]
    assert has_alternatives(sents)
    assert not has_alternatives(split_sentences(TEXT1)[1])
    loose = Rewrite("t", [Line("-", "(1) 시차출퇴근 선택폭 확대", list(range(1, len(sents) + 1)))], [])
    _, style = review(loose, sents, "t", 2026)
    assert any("표도 ①② 줄도 없음" in s for s in style)
    table = Rewrite("t", [Line("표", "", list(range(1, len(sents) + 1)), [["구분", "(1안)", "(2안)"], ["장점", "a", "b"]])], [])
    _, style = review(table, sents, "t", 2026)
    assert not any("표도 ①② 줄도 없음" in s for s in style)


def test_surviving_coined_word_is_rewritten_line_by_line():
    from doc2report.drafting import CLARIFY_SYSTEM, Line, Rewrite, _repair_coined

    sents = ["프로젝트 마감 전후로 몰아서 일하는 R&D 특성에 더 잘 맞습니다"]
    rw = Rewrite("t", [Line("-", "프로젝트 몰아일 특성 적합", [1])], [])
    asked = []

    def ask(system, user):
        asked.append(system)
        return "프로젝트 마감 전후 집중 근무하는 R&D 특성에 적합"

    notes = _repair_coined(rw, sents, ask, 2026)
    assert asked == [CLARIFY_SYSTEM] and "몰아일" not in rw.lines[0].text
    assert any("줄임말 풀어 씀" in n for n in notes)


def test_output_format_is_the_last_thing_in_the_prompt():
    from doc2report.drafting import FORMAT_TAIL, system_prompt

    for holdout in (None, {2}, {5}):
        assert system_prompt(holdout).rstrip().endswith(FORMAT_TAIL.strip())


def test_prompts_do_not_contain_evaluation_answer_text():
    """지시문(규칙·예시)에 평가 문서의 원문·정답 글이 들어가면 채점이 오염된다(2026-10-07에 실제로 들어가 있었다).
    정답에서 뽑은 문장 변환 예시(examples)는 doc 꼬리표로 --holdout이 빼므로 여기서는 고정 지시문만 본다."""
    import re

    import doc2report.drafting as d

    generic = {"습니다", "합니다", "입니다", "겠습니다", "했습니다"}
    docs = [re.sub(r"\s", "", p.read_text(encoding="utf-8")) for p in SAMPLES.glob("*_*.txt")]
    for name in [n for n in dir(d) if n.endswith("SYSTEM") or n == "FORMAT_TAIL"]:
        prompt = re.sub(r"\s", "", getattr(d, name))
        for j in range(len(prompt) - 7):
            piece = prompt[j:j + 8]
            if re.fullmatch(r"[가-힣0-9,.:()]{8}", piece) and not any(g in piece for g in generic):
                assert not any(piece in doc for doc in docs), (name, piece)


def test_json_mode_falls_back_when_server_rejects_it(monkeypatch):
    import httpx

    from doc2report.transform import llm_polish

    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        if "response_format" in body:
            return httpx.Response(400, json={"error": "unsupported"})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": 1}'}, "finish_reason": "stop"}]})

    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(llm_polish, "_JSON_MODE_REJECTED", False)
    monkeypatch.setenv("DOC2REPORT_LLM_BASE_URL", "http://llm.test/v1")
    monkeypatch.setenv("DOC2REPORT_MODEL", "m")
    assert llm_polish.ask_json("s", "u") == '{"ok": 1}'
    assert "response_format" in bodies[0] and "response_format" not in bodies[1]
    assert llm_polish.ask_json("s", "u") == '{"ok": 1}' and len(bodies) == 3   # 거부된 뒤로는 묻지 않는다


def test_split_clauses_keeps_numbers_particles_and_progressive_together():
    from doc2report.drafting import split_clauses

    assert split_clauses("다만 근로기준법상 서면 합의가 필요하고 정산기간과 총 근로시간을 정해야 하며, "
                         "연장근로 산정 방식이 바뀌어서 급여 시스템 개편 비용이 약 1억 2천만 원 들 것으로 보입니다.") == [
        "다만 근로기준법상 서면 합의가 필요하고", "정산기간과 총 근로시간을 정해야 하며",
        "연장근로 산정 방식이 바뀌어서", "급여 시스템 개편 비용이 약 1억 2천만 원 들 것으로 보입니다."]
    assert split_clauses("최근 설문에서 불만이 높게 나왔습니다.") == ["최근 설문에서 불만이 높게 나왔습니다."]
    assert split_clauses("현재는 시차출퇴근제만 운영하고 있는데 효과가 작다는 의견입니다.")[0] == "현재는 시차출퇴근제만 운영하고 있는데"


def test_audit_numbers_report_lines_and_accepts_clause_ids():
    from doc2report.drafting import Line, Rewrite, _audit_content

    sents = ["근로기준법상 서면 합의가 필요하고 정산기간과 총 근로시간을 정해야 합니다"]
    rw = Rewrite("t", [Line("-", "근로기준법상 서면 합의 필요", [1])], [])
    seen = {}

    def ask(system, user):
        if system == AUDIT_SYSTEM:
            seen["user"] = user
            return '{"missing":[{"clause":"1-2","info":"정산기간·총 근로시간 결정"}]}'
        return "정산기간 및 총 근로시간 사전 결정 필요"

    _audit_content(rw, sents, ask, 2026)
    assert "[1-2] 정산기간과 총 근로시간을 정해야 합니다" in seen["user"] and "1) - 근로기준법상" in seen["user"]
    assert rw.lines[-1].text == "정산기간 및 총 근로시간 사전 결정 필요"


def test_missing_clause_of_a_table_alternative_goes_into_its_cons_cell():
    from doc2report.drafting import Line, Rewrite, _audit_content

    sents = ["첫째는 배식 시간을 늘리는 것으로 노사 협의가 필요합니다",
             "둘째는 휴게실을 식당으로 바꾸는 것인데 공사 기간이 6주 걸리고 소방 점검을 다시 받아야 합니다"]
    table = Line("표", "", [1, 2], [["구분", "(1안) 배식 시간 연장", "(2안) 휴게실 식당 전환"],
                                   ["장점", "- 즉시 시행 可", "- 수용 인원 확대"],
                                   ["단점", "- 노사 협의 필요", "- 공사 기간 6주 소요"]])
    rw = Rewrite("t", [table], [])

    def ask(system, user):
        if system == AUDIT_SYSTEM:
            return '{"missing":[{"clause":"2-2","info":"소방 점검 재수검"}]}'
        return "휴게실 식당 전환 시 소방 점검 재수검 필요"

    notes = _audit_content(rw, sents, ask, 2026)
    assert len(rw.lines) == 1                                         # 표 아래 따로 줄을 만들지 않는다
    assert table.rows[2][2] == "- 공사 기간 6주 소요\n- 휴게실 식당 전환 시 소방 점검 재수검 필요"
    assert table.rows[2][1] == "- 노사 협의 필요" and any("표 칸" in n for n in notes)


def test_case2_replay_retry_names_missing_table_and_coined_word():
    """사용자가 보낸 2026-10-07 eval_2 결과(표 없음, '몰아일')를 1차 응답으로 재생 → 수정 요청에 두 문제가 다 들어가야 한다."""
    first = {"title": "유연근무제 확대 검토", "lines": [
        {"m": "□", "text": "현황 및 문제점", "src": [1, 2, 3]},
        {"m": "-", "text": "근무시간 경직성 불만 다수", "src": [1]},
        {"m": "-", "text": "출퇴근 자율화 선호 58%, 재택근무 확대 24% (응답자 312명)", "src": [2]},
        {"m": "-", "text": "현행 시차출퇴근제 출근 시각 선택폭 1시간으로 체감 효과 작음", "src": [3]},
        {"m": "□", "text": "대안 검토", "src": [4]},
        {"m": "-", "text": "(1) 시차 출퇴근 선택폭 2시간 확대 : 취업규칙 변경만으로 즉시 시행 가능하나 효과 제한적", "src": [5]},
        {"m": "-", "text": "(2) 선택적 근로시간 도입 : 정산기간 기준 근로시간 정산으로 프로젝트 몰아일 특성 적합", "src": [6]},
        {"m": "※", "text": "(2) 도입 시 서면 합의 필요, 급여 시스템 개편 비용 약 1.2억원 예상", "src": [7]},
        {"m": "□", "text": "추진 계획", "src": [9]},
        {"m": "-", "text": "(1) 올해 내 시행, (2) 내년 상반기 도입 추진", "src": [9]},
        {"m": "※", "text": "노조 협의 필요로 빨라야 내년 2분기 시행 가능, 법적 해석은 법무팀 확인 필요", "src": [8, 10]}],
        "dropped": []}
    requests = []

    def ask(system, user):
        if system == AUDIT_SYSTEM:
            return '{"missing":[]}'
        requests.append(user)
        return json.dumps(first, ensure_ascii=False)

    draft(TEXT2, ask=ask, year=2026)
    retry = requests[1]
    # "- (1) …"의 "(1)"은 2026-10-09부터 ①로 읽는다(겹친 말머리 정리) — 그래서 '표도 ①② 줄도 없음'은 더는 안 걸리고 번호 절·줄임말이 걸린다
    assert "몰아일" in retry and "번호 절이 없음" in retry


def test_coined_word_inside_a_table_cell_is_repaired_and_unrepairable_ones_are_reported():
    """2026-10-07 사용자 PC(커밋 12df22e) 재현: 표 칸 안 '몰아일'이 수리되지 않고 --report에도 안 나왔다."""
    from doc2report.drafting import CLARIFY_SYSTEM, Line, Rewrite, _repair_coined

    sents = ["프로젝트 마감 전후로 몰아서 일하는 R&D 특성에 더 잘 맞습니다"]

    def make():
        return Rewrite("t", [Line("표", "", [1], [["구분", "(1안)", "(2안)"],
                                                 ["장점", "- 즉시 시행 可", "- 취업규칙 변경\\n- 프로젝트 몰아일 특성에 적합".replace("\\n", "\n")]])], [])

    rw = make()
    notes = _repair_coined(rw, sents, lambda s, u: "프로젝트 마감 전후 집중 근무 특성에 적합" if s == CLARIFY_SYSTEM else "", 2026)
    assert rw.lines[0].rows[1][2] == "- 취업규칙 변경\n- 프로젝트 마감 전후 집중 근무 특성에 적합"
    assert any("줄임말 풀어 씀(표 칸)" in n for n in notes)
    rw = make()
    notes = _repair_coined(rw, sents, lambda s, u: "프로젝트 몰아일 특성에 적합", 2026)
    assert any("줄임말 남음(표 칸" in n for n in notes) and "몰아일" in rw.lines[0].rows[1][2]


def test_final_leftover_problems_are_listed_in_the_report():
    import json as _json

    from doc2report.drafting import draft

    bad = {"title": "t", "lines": [{"m": "-", "text": "채용 목표 : 총 40명", "src": [1]}], "dropped": [2, 3, 4, 5, 6, 7, 8]}

    def ask(system, user):
        return '{"missing":[]}' if system == AUDIT_SYSTEM else _json.dumps(bad, ensure_ascii=False)

    result = draft(TEXT1, ask=ask, year=2026)
    assert any(n.startswith("최종 점검에서 남음:") for n in result.notes)


def test_odd_mark_with_text_is_coerced_not_a_format_error():
    from doc2report.drafting import parse_rewrite

    rw = parse_rewrite('{"title":"t","lines":[{"m":"대","text":"대 상 : 30명","src":[1]}],"dropped":[]}', 1)
    assert rw.lines[0].m == "-" and any("'대'" in w for w in rw.warnings)


def test_score_tool_ignores_section_numbers():
    import importlib.util
    import sys as _sys
    from pathlib import Path as _P

    spec = importlib.util.spec_from_file_location("score_drafting", _P(__file__).parent.parent / "tools" / "score_drafting.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = _P(__file__).parent / "_tmp_eval_2.txt"
    out.write_text("1. 배경\n□ 응답자 312명 中 58%\n3. 추진 방향\n- 올해 내 시행\n", encoding="utf-8")
    try:
        assert mod.summary(out, 2)["invented"] == 0
    finally:
        out.unlink()


def test_plan_turned_into_in_progress_is_caught_but_among_usage_is_not():
    source = "둘째 방안은 법무 검토와 노조 협의를 거쳐 내년 상반기에 도입하는 단계적 추진이 좋다고 봅니다. 처우 협의 중이며 6명입니다."
    assert any("협의 中" in p for p in check("내년 상반기 도입 (법무 검토 및 노조 협의 중)", source.split(". ")[0]))
    assert not check("처우 협의 中 6명", source.split(". ")[1])
    assert not [p for p in check("발표과제 중 우수과제는 반영 검토", "발표 과제 중 우수 과제는 반영을 검토하겠습니다") if "中" in p]


def test_audit_per_clause_listing_flags_null_clauses_but_skips_filler_clauses():
    from doc2report.drafting import CONTENT_REPAIR_SYSTEM, Line, Rewrite, _audit_content

    sents = ["방안은 크게 두 가지로 생각해 볼 수 있습니다.",
             "다만 근로기준법상 서면 합의가 필요하고 정산기간과 총 근로시간을 정해야 하며 급여 시스템 개편 비용이 듭니다"]
    rw = Rewrite("t", [Line("-", "정산기간 기준 근로시간 정산", [1, 2]), Line("-", "서면 합의 필요", [2])], [])

    def ask(system, user):
        if system == AUDIT_SYSTEM:
            assert "[2-2]" in user                    # 모든 절을 번호 붙여 보낸다
            return ('{"clauses":[{"id":"1-1","line":null},{"id":"2-1","line":2},'
                    '{"id":"2-2","line":null,"info":"정산기간·총 근로시간 결정"}],"unclear":[]}')
        assert system == CONTENT_REPAIR_SYSTEM
        return "정산기간·총 근로시간 결정 필요"

    notes = _audit_content(rw, sents, ask, 2026)
    texts = [l.text for l in rw.lines]
    assert "정산기간·총 근로시간 결정 필요" in texts and len(texts) == 3     # 군말 절(1-1)은 보강하지 않는다
    assert sum("내용 누락 보강" in n for n in notes) == 1


# ── 여러 번 실행·핵심 요약(draft --runs) ─────────────────────────────────────

def test_draft_best_picks_the_run_with_fewest_remaining_problems(monkeypatch):
    from doc2report import drafting
    from doc2report.drafting import DraftResult, draft_best

    def fake(notes, mode="rewrite"):
        return DraftResult(text="제목\n", structure=None, notes=notes, used_llm=True, mode=mode)

    runs = iter([fake(["LLM 다듬기 응답 형식 오류 1회: x", "줄임말 남음(고치지 못함) ['몰아일']: 가"]),
                 fake(["줄임말 남음(고치지 못함) ['몰아일']: 가"]),
                 fake(["최종 점검에서 남음: a", "최종 점검에서 남음: b"])])
    monkeypatch.setattr(drafting, "draft", lambda *a, **k: next(runs))
    best = draft_best("x", runs=3)
    assert best.notes[0].startswith("줄임말 남음") and "2번째 결과 채택" in best.notes[-1]


def test_draft_best_stops_early_when_clean_and_ignores_runs_for_place_mode():
    from doc2report.drafting import draft_best, problem_count

    ask, calls = _answer(ANSWER1)
    best = draft_best(TEXT1, runs=3, ask=ask, year=2026)
    if problem_count(best) == 0:
        assert len(calls) == 1


def test_brief_has_no_source_text_and_counts_problems():
    from doc2report.drafting import brief

    ask, _ = _answer(ANSWER1)
    result = draft(TEXT1, ask, year=2026)
    text = brief(result, TEXT1, 2026)
    assert "분량" in text and "수치왜곡 0" in text and "남은 문제" in text
    assert "채용 목표" not in text


# ── 구조 보정 (2026-10-08 사용자: 단독 □ 항목명, 표 행·열, 312명 누락) ─────────────────

def test_lone_bare_box_under_section_is_lifted_into_heading():
    from doc2report.drafting import Line, lift_lone_groups

    lines = [Line("1.", "배경", [1]), Line("□", "현황", [1, 2]), Line("-", "설문 결과 불만 高", [1]),
             Line("-", "출퇴근 시간 자율화(58%) 희망", [2]),
             Line("1.", "추진 방향", [9]), Line("□", "단계적 추진 계획", [9]), Line("-", "1안 우선 시행", [9]),
             Line("1.", "검토 방안", [4]), Line("표", "", [5], [["구분", "(1안)", "(2안)"], ["장점", "a", "b"]])]
    notes = lift_lone_groups(lines)
    marks = [(l.m, l.text) for l in lines if not l.is_table]
    # 첫 '-'가 현상, 나머지가 수치 근거 → 첫 줄을 □ 핵심 문장으로 올림 / 나란한 항목 → □를 빼고 절 제목에 합침
    assert marks[:3] == [("1.", "배경"), ("□", "설문 결과 불만 高"), ("-", "출퇴근 시간 자율화(58%) 희망")]
    assert ("1.", "추진 방향 (단계적 추진 계획)") in marks and ("-", "1안 우선 시행") in marks
    assert len(notes) == 2


def test_lone_box_label_is_not_appended_when_heading_already_joined():
    from doc2report.drafting import Line, lift_lone_groups

    lines = [Line("1.", "배경 및 현황", [1]), Line("□", "설문 결과", [1]), Line("-", "불만 응답 58%", [1]),
             Line("-", "재택근무 확대 24%", [1])]
    lift_lone_groups(lines)
    assert lines[0].text == "배경 및 현황" and [l.m for l in lines] == ["1.", "-", "-"]


def test_meaningful_or_plural_boxes_are_kept():
    from doc2report.drafting import Line, lift_lone_groups

    one = [Line("1.", "배경", [1]), Line("□", "R&D 조직 설문 결과(312명), 근무시간 경직성 관련 불만 高", [1, 2]),
           Line("-", "출퇴근 시간 자율화(58%) 희망", [2])]
    two = [Line("1.", "배경", [1]), Line("□", "현황", [1]), Line("-", "가", [1]), Line("□", "문제점", [2]), Line("-", "나", [2])]
    assert lift_lone_groups(one) == [] and len(one) == 3
    assert lift_lone_groups(two) == [] and len(two) == 5


def test_transposed_alternative_table_is_flipped():
    from doc2report.drafting import Line, orient_tables

    line = Line("표", "", [5, 6], [["구분", "장점", "단점"], ["(1안) 선택폭 확대", "즉시 시행 可", "효과 제한적"],
                                   ["(2안) 선택적 근로시간제", "R&D 특성 적합", "서면 합의 필요"]])
    assert orient_tables([line])
    assert line.rows[0] == ["구분", "(1안) 선택폭 확대", "(2안) 선택적 근로시간제"]
    assert line.rows[2][0] == "단점"
    assert orient_tables([line]) == []          # 이미 맞는 방향이면 그대로


def test_missing_respondent_count_is_appended_when_llm_repair_fails():
    from doc2report.drafting import Line, Rewrite, _repair_numbers, split_sentences

    _, sentences = split_sentences(TEXT2)
    rw = Rewrite("t", [Line("1.", "배경", [1, 2]), Line("-", "출퇴근 시간 자율화(58%), 재택근무 확대(24%) 희망", [2])], [])
    notes = _repair_numbers(rw, sentences, lambda s, u: "", 2026)
    assert "응답자 312명" in rw.lines[1].text and any("원문 어구로 보강" in n for n in notes)


# ── 2026-10-08 사용자 피드백 2차 (건2~5) ─────────────────────────────────────

def test_arrow_under_section_becomes_box_and_parallel_arrow_becomes_dash():
    from doc2report.drafting import Line, fix_arrows

    sents = ["업무 부담이 커질 수 있어 팀장들에게 주당 4시간 조정을 요청합니다.",
             "우수 과제는 내년 계획에 반영하는 방안도 같이 검토하겠습니다.",
             "1안을 올해 먼저 시행합니다."]
    lines = [Line("1.", "추진 방향", [3]), Line("→", "1안 올해 우선 시행", [3]),
             Line("-", "팀장 대상 주당 4시간 업무 조정 요청", [1]), Line("→", "우수 과제 내년 계획 반영 검토", [2])]
    notes = fix_arrows(lines, sents)
    assert [l.m for l in lines] == ["1.", "□", "-", "-"] and len(notes) == 2


def test_real_result_arrow_is_kept():
    from doc2report.drafting import Line, fix_arrows

    lines = [Line("□", "개선 방향", [1]), Line("-", "실습 시간 부족 의견 다수", [1]), Line("→", "차년도 실습 1일 확대 검토", [2])]
    fix_arrows(lines, ["실습 시간이 부족하다는 의견이 많았습니다.", "내년에는 실습을 하루 더 늘리는 방안을 검토하겠습니다."])
    assert lines[2].m == "→"


def test_line_repeating_the_title_is_dropped():
    from doc2report.drafting import Line, Rewrite, drop_title_echoes

    rw = Rewrite("하반기 신입 연수 프로그램 추진 계획",
                 [Line("□", "운영 개요", [1]), Line("-", "신입 연수 프로그램 하반기 운영", [1]),
                  Line("□", "대상", [2]), Line("-", "대 상 : 신입 40명", [2])], [])
    notes = drop_title_echoes(rw, "하반기 신입 연수 프로그램 추진 계획")
    assert [l.text for l in rw.lines] == ["대상", "대 상 : 신입 40명"] and 1 in rw.dropped and notes


def test_three_option_table_becomes_ordinal_list():
    from doc2report.drafting import Line, tables_to_ordinals

    table = Line("표", "", [6, 7], [["구분", "(1안) 기준 상향", "(2안) 물가 연동", "(3안) 실비 지원"],
                                   ["비용", "- 연 4억원 증가", "-", "-"],
                                   ["고려 사항", "", "- 지표 선정 어려움", "- 관리 부담\n- 비용 통제 어려움"]])
    lines = [table]
    assert tables_to_ordinals(lines)
    shown = [(l.m, l.text) for l in lines]
    assert shown[0] == ("①", "기준 상향") and ("-", "비용 : 연 4억원 증가") in shown
    assert ("③", "실비 지원") in shown and ("-", "고려 사항 : 관리 부담, 비용 통제 어려움") in shown
    rich = [Line("표", "", [1], [["구분", "(1안) A", "(2안) B"], ["장점", "- a\n- b", "- c\n- d"], ["단점", "- e\n- f", "- g\n- h"]])]
    assert tables_to_ordinals(rich) == [] and rich[0].is_table          # 내용이 많은 두 안은 표 그대로
    pros_cons = [Line("표", "", [1], [["구분", "(1안) A", "(2안) B"], ["장점", "- a", "- c"], ["단점", "- e", "- g"]])]
    assert tables_to_ordinals(pros_cons) == [] and pros_cons[0].is_table    # 장·단점 비교는 칸이 한 줄씩이어도 표(2026-10-09 문서 2)
    simple = [Line("표", "", [1], [["구분", "(1안) A", "(2안) B"], ["내용", "- a", "- c"], ["비용", "- e", "- g"]])]
    assert tables_to_ordinals(simple) and simple[0].m == "①"                # 장·단점 비교가 아니고 간단하면 ①② 줄


def test_weekday_is_added_only_to_real_dates():
    from doc2report.drafting import Line, add_weekdays

    sents = ["최종 등급은 9월 5일 인사위원회에서 확정합니다.", "만족도는 4.3점입니다."]
    lines = [Line("-", "최종 등급 확정 : 9.5 인사위원회", [1]), Line("-", "만족도 4.3점", [2]),
             Line("-", "기한 (~9.5일)", [1])]
    add_weekdays(lines, sents, 2026)
    assert lines[0].text == "최종 등급 확정 : 9.5(토) 인사위원회"
    assert lines[1].text == "만족도 4.3점" and lines[2].text == "기한 (~9.5일)"


def test_strong_cue_alone_marks_alternative_document():
    from doc2report.drafting import has_alternatives, split_sentences

    found = {n: has_alternatives(split_sentences(next(SAMPLES.glob(f"줄글_{n}_*.txt")).read_text(encoding="utf-8"))[1])
             for n in range(1, 6)}
    assert found == {1: False, 2: True, 3: False, 4: False, 5: True}


def test_weekday_added_to_range_end_date():
    from doc2report.drafting import Line, add_weekdays

    sents = ["캘리브레이션을 8월 22일부터 이틀간 진행했습니다."]
    lines = [Line("-", "기 간 : 8.22 ~ 23 (2일간)", [1]), Line("-", "기 간 : 8.22(토) ~ 23", [1])]
    add_weekdays(lines, sents, 2026)
    assert lines[0].text == "기 간 : 8.22(토) ~ 23(일) (2일간)"
    assert lines[1].text == "기 간 : 8.22(토) ~ 23(일)"


# ── 2026-10-09 사용자 피드백 3차 ─────────────────────────────────────────────

def test_duplicate_marker_in_text_is_resolved():
    raw = json.dumps({"title": "t", "lines": [
        {"m": "-", "text": "→ 3개월 이상 공석 포지션 2개 발생", "src": [1]},
        {"m": "-", "text": "※ 현 시차출퇴근제는 효과가 작다는 의견", "src": [1]},
        {"m": "-", "text": "- 이중 대시", "src": [1]},
        {"m": "-", "text": "-5% 하락", "src": [1]}], "dropped": []}, ensure_ascii=False)
    from doc2report.drafting import parse_rewrite

    rewrite = parse_rewrite(raw, 1)
    assert [(l.m, l.text) for l in rewrite.lines] == [
        ("→", "3개월 이상 공석 포지션 2개 발생"), ("※", "현 시차출퇴근제는 효과가 작다는 의견"),
        ("-", "이중 대시"), ("-", "-5% 하락")]


def test_dash_before_first_square_in_a_section_is_promoted():
    from doc2report.drafting import Line, fix_level_order

    lines = [Line("1.", "배경 및 현황", [1]), Line("-", "물가 상승으로 불만", [1]), Line("□", "보조금 부족으로 부담 증가", [1]),
             Line("-", "주거비 22% 상승", [1]), Line("□", "경쟁사 지원 현황", [2]), Line("-", "A사 연동", [2]),
             Line("1.", "검토 방안", [3]), Line("-", "나란한 항목", [3]), Line("-", "나란한 항목 2", [3])]
    fix_level_order(lines)
    assert [l.m for l in lines] == ["1.", "□", "□", "-", "□", "-", "1.", "-", "-"]   # □ 없는 절은 그대로


def test_date_dots_are_removed_in_ranges_and_singles():
    from doc2report.drafting import Line, normalize_dates

    sents = ["캘리브레이션을 8월 22일부터 이틀간 진행했습니다. 최종 등급은 9월 5일에 확정합니다."]
    lines = [Line("-", "8.22.~23. 진행", [1]), Line("-", "최종 확정 9.5. 인사위원회", [1]), Line("-", "만족도 4.3점", [1]),
             Line("-", "기 간 : 8.22.(토) ~ 23.", [1])]
    normalize_dates(lines, sents)
    assert [l.text for l in lines] == ["8.22 ~ 23 진행", "최종 확정 9.5 인사위원회", "만족도 4.3점", "기 간 : 8.22(토) ~ 23"]


# ── 2026-10-09 4차: 표 행 3개로, 화살표는 꼭 필요할 때만 ──────────────────────────

def test_thin_cons_rows_are_merged_but_other_rows_are_kept():
    from doc2report.drafting import Line, consolidate_table_rows

    table = Line("표", "", [4, 5], [
        ["구분", "(1안) 선택 폭 확대", "(2안) 선택적 근로시간제"],
        ["내용", "- 출근 선택 폭 1시간 → 2시간", "- 정산기간 기준 근로시간 관리"],
        ["장점", "- 즉시 시행 可", "- R&D 특성에 적합"],
        ["단점", "- 효과 제한적", "- 근로자대표 서면 합의 필요"],
        ["비용", "- 추가 비용 없음", "- 급여 시스템 개편 약 1.2억원"],
        ["일정", "- 올해 內", "- 내년 2분기 이후"]])
    lines = [table]
    assert consolidate_table_rows(lines)
    rows = lines[0].rows
    assert [r[0] for r in rows] == ["구분", "내용", "장점", "단점/고려 사항"]       # 내용·장점은 그대로
    assert rows[3][2].split("\n") == ["- 근로자대표 서면 합의 필요", "- 비용 : 급여 시스템 개편 약 1.2억원", "- 일정 : 내년 2분기 이후"]


def test_rows_with_enough_content_stay_separate():
    from doc2report.drafting import Line, consolidate_table_rows

    table = Line("표", "", [4, 5], [
        ["구분", "(1안) A", "(2안) B"],
        ["효과", "- 가\n- 나", "- 다\n- 라"],
        ["비용", "- 약 1억원\n- 인건비 별도", "- 약 2억원\n- 설비 별도"],
        ["위험", "- 일정 지연\n- 인력 이탈", "- 협의 난항\n- 법적 검토"]])
    lines = [table]
    assert consolidate_table_rows(lines) == [] and [r[0] for r in lines[0].rows] == ["구분", "효과", "비용", "위험"]


def test_non_comparison_table_is_left_alone():
    from doc2report.drafting import Line, consolidate_table_rows

    table = Line("표", "", [1], [["구분", "2025", "2026"], ["매출", "100", "120"], ["비용", "80", "90"], ["이익", "20", "30"]])
    lines = [table]
    assert consolidate_table_rows(lines) == [] and len(lines[0].rows) == 4


def test_arrow_without_causal_source_becomes_explanation_dot():
    from doc2report.drafting import Line, restrict_arrows

    sents = ["과제는 5명씩 6개 팀으로 12월 중순에 발표합니다.", "팀장들에게 주당 4시간 업무 조정을 요청할 계획입니다.",
             "경력자가 부족해서 공석이 3개월 넘게 이어지고 있습니다."]
    lines = [Line("1.", "추진", [1]), Line("-", "실제 과제 수행 : 6개팀(5명/팀)", [1]), Line("→", "팀장 주당 4시간 업무 조정 요청", [2]),
             Line("-", "경력자 부족", [3]), Line("→", "3개월 이상 공석 포지션 2개", [3]), Line("→", "또 다른 화살표", [3])]
    restrict_arrows(lines, sents)
    assert [l.m for l in lines] == ["1.", "-", "∙", "-", "→", "∙"]    # 인과 근거가 있는 첫 → 하나만 남김


def test_ordinals_are_compacted_into_one_line_each():
    from doc2report.drafting import Line, compact_ordinals

    lines = [Line("1.", "검토 방안", [1]),
             Line("①", "기준표 일괄 상향", [2]), Line("-", "내용 : 기준표 일괄 상향", [2]), Line("-", "장점 : 즉시 반영 可", [2]),
             Line("-", "단점 : 연 4억원 추가", [2]),
             Line("②", "물가 연동 방식 전환", [3]), Line("-", "내용 : 물가 연동 방식으로 전환", [3]),
             Line("-", "장점 : 형평 확보", [3]), Line("-", "단점 : 연동 지표 선정 어려움, 관리 부담, 연 1회 점검 필요, 노조 협의 및 취업규칙 개정 필요", [3])]
    compact_ordinals(lines)
    shown = [(l.m, l.text) for l in lines]
    assert shown[1] == ("①", "기준표 일괄 상향 : 즉시 반영 可, 연 4억원 추가")          # 이름 되풀이 줄 삭제 + 장·단점 한 줄 요약
    assert shown[2][0] == "②" and len(shown) == 5                                       # ②는 길어서 항목 줄 유지('내용' 줄만 삭제)
    assert not any(t.startswith("내용") for _, t in shown)


def test_dash_before_paren_number_becomes_ordinal():
    raw = json.dumps({"title": "t", "lines": [{"m": "-", "text": "(1) 방안 : 올해 시행", "src": [1]},
                                               {"m": "□", "text": "② 방안 : 내년 도입", "src": [1]}], "dropped": []}, ensure_ascii=False)
    from doc2report.drafting import parse_rewrite

    assert [(l.m, l.text) for l in parse_rewrite(raw, 1).lines] == [("①", "방안 : 올해 시행"), ("②", "방안 : 내년 도입")]
