"""정식보고서 실사용 5차(2026-10-01) — 좁히기 여유·단락 뒤 간격·표 맞춤·표현 줄임."""

import re

import pytest
from docx import Document as OpenDocx
from docx.shared import Pt

from doc2report.layout.lines import fit_text
from doc2report.parsers.markdown import parse_markdown
from doc2report.pipeline import convert
from doc2report.profile import load_profile
from doc2report.render import docx_writer

from test_formal_lines import _FakeMeasurer, fake_fonts  # noqa: F401


def test_condense_pad_adds_margin_but_never_exceeds_max():
    widths = [10.0] * 11
    text = "가" * 10 + " " + "나"
    base = dict(first_room=105.0, cont_room=105.0, max_condense=1.0, step=0.1)
    plain = fit_text("가" * 11, [10.0] * 11, **base)
    padded = fit_text("가" * 11, [10.0] * 11, pad=0.1, **base)
    assert plain[0].steps == 5 and padded[0].steps == 6                  # 5/11=0.45pt → 0.5pt, 여유 +0.1pt
    capped = fit_text("가" * 11, [10.0] * 11, first_room=100.0, cont_room=100.0, max_condense=1.0, step=0.1, pad=0.5)
    assert capped[0].steps == 10                                         # 최대 1.0pt를 넘기지 않는다


def _convert(tmp_path, text, name="s.txt", **kw):
    src = tmp_path / name
    src.write_text(text, encoding="utf-8")
    out = tmp_path / "o.docx"
    result = convert(str(src), out, "formal", polish="none", **kw)
    return OpenDocx(str(out)), result


_MEMO = """보고
2026. 10. 1

1. 배경
□ 첫째 항목
* 주석 설명
□ 둘째 항목
※ 참고 사항
□ 셋째 항목
  - 하위 항목
2. 현황
□ 다음 절 항목
  - 마지막 하위 항목
3. 계획
□ 계획 항목
"""


def test_gaps_use_space_after_not_space_before(tmp_path, fake_fonts):
    doc, _ = _convert(tmp_path, _MEMO)
    paragraphs = {p.text.strip(): p for p in doc.paragraphs}
    gap = Pt(18)
    assert paragraphs["□ 첫째 항목"].paragraph_format.space_after >= gap        # 주석(상자) 뒤 18pt를 윗줄이 가진다
    assert paragraphs["※ 참고 사항"].paragraph_format.space_after == Pt(6)     # □ → ※ → □ 같은 계통이라 6pt
    assert paragraphs["- 마지막 하위 항목"].paragraph_format.space_after == gap  # 새 절 앞 18pt
    for text in ("2. 현황", "3. 계획"):
        before = paragraphs[text].paragraph_format.space_before
        assert not before                                                        # 단락 앞 간격은 안 쓴다


def test_note_line_is_smaller_than_body(tmp_path, fake_fonts):
    doc, _ = _convert(tmp_path, _MEMO)
    note = next(p for p in doc.paragraphs if "참고 사항" in p.text)
    assert all(r.font.size == Pt(14) for r in note.runs if r.text.strip())   # 본문 ※ 14pt (2026-10-03 사용자)


_TABLES = """1. 현황
□ 표를 본다
구분\t목표\t실적\t달성률\t비고
신입\t120\t131\t109%\t석사 이상 비중이 높고 지원자 풀이 넓어 초과 달성하였음
경력\t80\t49\t61%\t공정개발 직군 지원자가 부족하여 채용 일정이 계속 지연되고 있음
"""


def test_data_columns_are_equal_and_note_column_is_small(tmp_path):
    doc, result = _convert(tmp_path, _TABLES)
    widths = [c.width for c in doc.tables[0].rows[0].cells]
    assert len(set(widths[:4])) == 1                                             # 구분·목표·실적·달성률 폭 동일
    assert widths[4] <= sum(widths) * 0.305                                      # 비고는 표 폭의 30% 이내
    assert any("참고 열" in n for n in result.notes)
    sizes = {(ri, ci): fmt for (ri, ci), fmt in next(iter(result.layouts.values())).cell_font.items()}
    assert sizes and all(ci == 4 for (_, ci) in sizes)                           # 글자를 줄이는 건 비고 열뿐


def test_table_left_edge_is_the_line_above_via_right_alignment(tmp_path):
    from doc2report.profile import load_profile

    doc, result = _convert(tmp_path, _TABLES)
    layout = next(iter(result.layouts.values()))
    prof = load_profile("formal")
    assert layout.indent > 0                                                     # □ 줄의 왼쪽 끝(앞 공백 1칸)
    widths = sum(c.width for c in doc.tables[0].rows[0].cells)
    assert abs(widths - (prof.page.usable_width - layout.indent)) < 3000         # 폭 = 윗줄 글자 시작 ~ 오른쪽 여백
    assert 'w:jc w:val="right"' in doc.element.xml


def test_markdown_date_line_survives():
    blocks = parse_markdown("# 제목\n\n2026. 10. 1\n\n본문\n").blocks
    assert [b.runs[0].text for b in blocks] == ["2026. 10. 1", "본문"]


_LONG = "□ " + "가나다라마바사아 " * 4 + "가나다라마바사아"


def test_orphan_is_shortened_by_llm_or_reported(tmp_path, fake_fonts):
    prof = load_profile("formal")
    from doc2report.ir import Document, Heading, Paragraph, Run
    from doc2report.layout.table_fit import plan_tables

    per = prof.font("body").size
    rules = prof.text
    text = ""
    for n in range(8, 40):                                       # 좁히기 한도로도 못 넣고 한 어절만 다음 줄로 넘어가는 길이
        text = "□ " + " ".join(["가나다"] * n)
        widths = [per * (0.5 if c == " " else 1.0) for c in text]
        lines = fit_text(text, widths, first_room=prof.page.usable_width, cont_room=prof.page.usable_width,
                         max_condense=rules.condense_max, step=rules.condense_step, margin=rules.fit_margin,
                         pad=rules.condense_pad,
                         weights=[rules.condense_space_weight if c == " " else rules.condense_wide_weight for c in text])
        if len(lines) == 2 and lines[1].end - lines[1].start <= rules.orphan_max:
            break
    else:
        pytest.fail("테스트 문장을 못 만듦")
    body = text[2:]
    doc = Document(blocks=[Heading(level=2, runs=[Run("배경")]), Paragraph(runs=[Run("□ " + body)])])

    def render(shortener):
        out = tmp_path / "o.docx"
        r = docx_writer.DocxRenderer(prof, plan_tables(doc, prof), shortener=shortener)
        r.save(doc, out)
        return r, [p.text for p in OpenDocx(str(out)).paragraphs if "가" in p.text]

    r, lines = render(None)
    assert len(lines) == 2 and any("두세 글자" in n for n in r.notes)            # 못 줄이면 리포트에 남긴다
    r, lines = render(lambda text, limit: text[:limit - 1])
    assert len(lines) == 1 and any("표현 줄임" in n for n in r.notes)            # 줄이면 한 줄


def test_note_right_below_a_table_is_close_to_it(tmp_path, fake_fonts):
    doc, _ = _convert(tmp_path, _TABLES + "※ 표를 부연하는 설명\n□ 다음 항목\n")
    paragraphs = {p.text.strip(): p for p in doc.paragraphs}
    note = paragraphs["※ 표를 부연하는 설명"]
    assert note.paragraph_format.space_before == Pt(6)                       # 표 뒤 18pt가 아니라 6pt
    assert all(r.font.size == Pt(12) for r in note.runs if r.text.strip())   # 12pt
    assert note.paragraph_format.space_after == Pt(6)                        # □ → 표 → ※ → □ 같은 계통이라 ※ 뒤 6pt
    assert paragraphs["□ 다음 항목"].paragraph_format.space_before in (None, Pt(0))


def test_header_row_has_a_1_5pt_bottom_rule_instead_of_shading(tmp_path):
    doc, _ = _convert(tmp_path, _TABLES)
    table = doc.tables[0]
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    header = table.rows[0]._tr.tc_lst[0].tcPr.find(f"{ns}tcBorders").find(f"{ns}bottom")
    body = table.rows[1]._tr.tc_lst[0].tcPr.find(f"{ns}tcBorders").find(f"{ns}top")
    assert header.get(f"{ns}sz") == body.get(f"{ns}sz") == "12"                  # 1.5pt = 12/8pt
    assert "w:shd" not in table.rows[0].cells[0]._tc.xml                        # 음영은 없다
    assert table.rows[2]._tr.tc_lst[0].tcPr.find(f"{ns}tcBorders") is None      # 다른 행은 그대로


def test_cli_has_llm_and_shorten_flags():
    from typer.testing import CliRunner

    from doc2report.cli import app

    out = CliRunner().invoke(app, ["convert", "--help"]).output
    assert "--llm" in out and "--shorten" in out


def test_formal_does_not_merge_short_list_items(tmp_path, fake_fonts):
    src = tmp_path / "m.md"
    src.write_text("## 비교\n\n- A사 솔루션: 기능 우수\n- B사 솔루션: 비용 낮음\n", encoding="utf-8")
    out = tmp_path / "o.docx"
    convert(str(src), out, "formal", polish="none")
    texts = [p.text.strip() for p in OpenDocx(str(out)).paragraphs]
    assert "□ A사 솔루션: 기능 우수" in texts and "□ B사 솔루션: 비용 낮음" in texts   # 둘로 남는다("및"으로 안 합침)


def test_tab_rows_with_trimmed_trailing_cells_stay_in_the_table(tmp_path):
    doc, _ = _convert(tmp_path, "1. 현황\n□ 표\n등급\t비율\t지급률\t비고\nS\t10%\t150%\t최상위\nA\t30%\t120%\nB\t40%\t100%\t기준\n")
    assert len(doc.tables) == 1 and len(doc.tables[0].rows) == 4
    assert [c.text for c in doc.tables[0].rows[2].cells] == ["A", "30%", "120%", ""]
    assert not any("\t" in p.text for p in doc.paragraphs)


def test_note_column_font_alone_shrinks_so_table_stays_at_body_size(tmp_path):
    from doc2report.pipeline import convert

    src = tmp_path / "t.md"
    src.write_text("## 현황\n\n| 직군 | 합격 | 입사 | 입사율 | 비고 |\n|---|---|---|---|---|\n"
                   "| 공정개발 | 40 | 33 | 83% | 처우 협상 지연 2건 |\n"
                   "| 소자 | 32 | 22 | 69% | " + "경쟁사 중복 합격자의 포기가 다수이며 근무지 선호 차이가 주된 사유 " * 2 + " |\n",
                   encoding="utf-8")
    result = convert(str(src), tmp_path / "o.docx", "formal", polish="none")
    layout = next(iter(result.layouts.values()))
    assert layout.font_size == Pt(12)                                           # 표 전체는 12pt 그대로
    assert {ci for (_, ci) in layout.cell_font} == {4} and all(f[0] == Pt(10) for f in layout.cell_font.values())


def test_annotation_box_is_at_least_5mm_per_line(tmp_path, fake_fonts):
    doc, _ = _convert(tmp_path, _MEMO)
    xml = doc.element.xml
    heights = [float(h) for h in re.findall(r"height:([\d.]+)pt", xml)]
    assert heights and min(heights) >= 14.1                                      # 5mm = 14.17pt


def test_note_gap_depends_on_whether_the_system_continues(tmp_path, fake_fonts):
    text = ("1. 배경\n□ 가\n  - 문장1\n※ 같은 계통 설명\n  - 문장2\n  - 문장3\n※ 체계가 바뀌는 설명\n□ 문장4\n")
    doc, _ = _convert(tmp_path, text)
    paragraphs = {p.text.strip(): p for p in doc.paragraphs}
    assert paragraphs["※ 같은 계통 설명"].paragraph_format.space_after == Pt(6)      # - → ※ → -
    assert paragraphs["※ 체계가 바뀌는 설명"].paragraph_format.space_after in (Pt(12), Pt(18))  # - → ※ → □ 올라감


def test_paren_and_circled_numbers_are_one_level_below_the_section_number(tmp_path, fake_fonts):
    text = "1. 배경\n(1) 첫째\n- 하위\n· 더 하위\n① 둘째\n- 하위2\n"
    doc, _ = _convert(tmp_path, text)
    texts = [p.text.rstrip() for p in doc.paragraphs]
    assert " (1) 첫째" in texts and "   - 하위" in texts and "     · 더 하위" in texts   # □처럼 1칸, - 3칸, · 5칸
    assert " ① 둘째" in texts and "   - 하위2" in texts


def test_report_tells_where_each_table_starts(tmp_path):
    _, result = _convert(tmp_path, _TABLES)
    assert any("위치: right 정렬" in n and "윗줄 글자 시작" in n for n in result.notes)


def _lines(tmp_path, text):
    doc, _ = _convert(tmp_path, text)
    return [p.text.rstrip() for p in doc.paragraphs if p.text.strip() != "- 이 상 -"]   # 맺음말은 빼고 본다


def test_levels_follow_the_order_markers_appear(tmp_path, fake_fonts):
    # 1. □ - · → 0·1·3·5칸
    assert _lines(tmp_path, "1. 가\n□ 나\n- 다\n· 라\n")[-4:] == ["1. 가", " □ 나", "   - 다", "     · 라"]
    # 1. □ (1) - → (1)·① 이 끼면 한 단계씩 밀린다
    assert _lines(tmp_path, "1. 가\n□ 나\n(1) 다\n- 라\n")[-4:] == ["1. 가", " □ 나", "   (1) 다", "     - 라"]
    # 1. (1) □ - 도 마찬가지(나온 순서대로)
    assert _lines(tmp_path, "1. 가\n(1) 나\n□ 다\n- 라\n")[-4:] == ["1. 가", " (1) 나", "   □ 다", "     - 라"]
    # □ - 두 단계: □ 1칸, - 3칸 (1. 단계는 비워 둔다)
    assert _lines(tmp_path, "□ 가\n- 나\n")[-2:] == [" □ 가", "   - 나"]
    # □ ① - / ① □ - 세 단계: 1·3·5칸
    assert _lines(tmp_path, "□ 가\n① 나\n- 다\n")[-3:] == [" □ 가", "   ① 나", "     - 다"]
    assert _lines(tmp_path, "① 가\n□ 나\n- 다\n")[-3:] == [" ① 가", "   □ 나", "     - 다"]


def test_a_marker_seen_again_goes_back_to_its_level(tmp_path, fake_fonts):
    got = _lines(tmp_path, "1. 가\n□ 나\n(1) 다\n- 라\n(1) 마\n□ 바\n- 사\n2. 아\n")[-8:]
    assert got == ["1. 가", " □ 나", "   (1) 다", "     - 라", "   (1) 마", " □ 바", "   - 사", "2. 아"]


def test_gaps_same_level_6pt_up_12_or_18pt(tmp_path, fake_fonts):
    doc, _ = _convert(tmp_path, "1. 가\n□ 나\n- 다\n- 라\n□ 마\n- 바\n")
    after = {p.text.strip(): p.paragraph_format.space_after for p in doc.paragraphs}
    assert after["- 다"] == Pt(6)                          # - → - 같은 단계
    assert after["- 라"] in (Pt(12), Pt(18))               # - → □ 올라감
    assert after["□ 나"] == Pt(12)                         # 제목 같은 □("□ 나") 아래는 12pt (2026-10-03 사용자)


def test_balance_sbcs_dbcs_flag_only_in_formal():
    """한글·영문 폭 균형 호환 옵션은 정식보고서만 켠다(Confluence 변환은 그대로)."""
    from docx.oxml.ns import qn

    from doc2report.ir import Document, Paragraph, Run

    def flag(profile_name: str) -> bool:
        renderer = docx_writer.DocxRenderer(load_profile(profile_name))
        result = renderer.render(Document(blocks=[Paragraph([Run("가")])]))
        compat = result.document.settings.element.find(qn("w:compat"))
        return compat.find(qn("w:balanceSingleByteDoubleByteWidth")) is not None

    assert flag("formal") is True
    assert flag("confluence") is False


def test_condense_model_matches_word_measurements():
    """사용자 Word 실측(2026-10-02): 14pt 바탕체 한글 한 줄 34/35/36/38/40자 @ 간격 0/0.2/0.4/0.7/1.0pt."""
    prof = load_profile("formal")
    rules = prof.text
    size = 14.0
    room = prof.page.usable_width / 12700                      # pt
    weights_for = lambda text: [rules.condense_wide_weight] * len(text)

    def per_line(spacing: float) -> int:
        n = 20
        while True:
            text = "가" * (n + 1)
            lines = fit_text(text, [size] * len(text), first_room=room, cont_room=room,
                             max_condense=spacing, step=0.1, weights=weights_for(text))
            if len(lines) > 1:
                return n
            n += 1

    # 간격 한도(max_condense)가 곧 그 줄의 간격 — 넘치면 줄을 나누므로 한 줄 글자 수가 실측과 같아야 한다
    assert [per_line(c) for c in (0.0, 0.2, 0.4, 0.7, 1.0)] == [34, 35, 36, 38, 40]


def test_shortened_sentence_is_written_even_when_it_needs_no_condensing(tmp_path, fake_fonts):
    """LLM이 줄인 문장이 좁히지 않아도 한 줄에 들어가면, 예전엔 계획이 None이라 **원문(긴 문장)이 그대로** 나왔다
    (2026-10-02 사용자: 줄바꿈 조치도 왼쪽 끝 맞춤도 안 된 채 쭉 내려써짐)."""
    from doc2report.ir import Document, Heading, Paragraph, Run
    from doc2report.layout.table_fit import plan_tables

    prof = load_profile("formal")
    per = prof.font("body").size
    text = ""
    for n in range(8, 40):                                       # 좁히기 한도로도 못 넣고 두세 글자만 다음 줄로 넘어가는 길이
        text = "□ " + " ".join(["가나다"] * n)
        widths = [per * (0.5 if c == " " else 1.0) for c in text]
        lines = fit_text(text, widths, first_room=prof.page.usable_width, cont_room=prof.page.usable_width,
                         max_condense=prof.text.condense_max, step=prof.text.condense_step,
                         margin=prof.text.fit_margin, pad=prof.text.condense_pad,
                         weights=[prof.text.condense_space_weight if c == " " else prof.text.condense_wide_weight for c in text])
        if len(lines) == 2 and lines[1].end - lines[1].start <= prof.text.orphan_max:
            break
    else:
        pytest.fail("테스트 문장을 못 만듦")
    doc = Document(blocks=[Heading(level=2, runs=[Run("배경")]), Paragraph(runs=[Run(text)])])
    out = tmp_path / "o.docx"
    docx_writer.DocxRenderer(prof, plan_tables(doc, prof), shortener=lambda original, limit: "가나다 가나다").save(doc, out)
    body = [p.text for p in OpenDocx(str(out)).paragraphs if "가" in p.text]
    assert len(body) == 1 and "가나다 가나다" in body[0] and len(body[0]) < len(text) // 2    # 줄인 글이 나온다


def test_width_model_matches_word_measurements_for_ascii_space_and_mixed():
    """사용자 Word 실측(2026-10-02, 14pt 바탕체, 본문 폭 481.89pt): 숫자·대문자·소문자·% 100자는 간격 0에 68자, 1.0pt에 80자(폭 0.5em,
    효과 1배) / 한글+공백 번갈아 23자·28자(공백 폭 0.5em, 효과 2배) / 한글 24+영문숫자 16자 @0, 27+20 @1.0(한글↔영문 경계 1/4em)."""
    from doc2report.layout.lines import apply_autospace
    from doc2report.layout.measure import is_wide

    rules = load_profile("formal").text
    room, size = load_profile("formal").page.usable_width / 12700, 14.0

    def count(text, spacing):
        widths = [size if is_wide(c) else size / 2 for c in text]
        widths = apply_autospace(text, widths, rules.autospace * size, is_wide,
                                 lambda c: c.isascii() and c.isalnum())
        total = 0.0
        for i, c in enumerate(text):
            weight = rules.condense_wide_weight if is_wide(c) else rules.condense_space_weight if c == " " else 1.0
            total += widths[i] - weight * spacing
            if total > room:
                return i
        return len(text)

    assert (count("1234567890" * 10, 0), count("1234567890" * 10, 1.0)) == (68, 80)
    assert (count("ABCDEFGHIJ" * 10, 0), count("%" * 100, 1.0)) == (68, 80)
    # 공백은 어절 경계에서만 끊는다 — 한글 수는 "가 " 번갈아 글자에서 센다
    spaced = "가 " * 60
    assert (count(spaced, 0) + 1) // 2 == 23 and (count(spaced, 1.0) + 1) // 2 == 28
    mixed = "".join("가나다라마" + "ab12" for _ in range(14))
    assert count(mixed, 0) == 40 and count(mixed, 1.0) == 47


def test_autospace_applies_to_latin_and_digits_not_symbols():
    """한글 5자 + 기호 1자 되풀이는 간격 0에 첫 줄 37자(2026-10-03 실측) — 기호 경계에는 1/4em이 안 붙는다."""
    from doc2report.layout.lines import apply_autospace
    from doc2report.layout.measure import is_wide

    prof = load_profile("formal")
    room, size = prof.page.usable_width / 12700, 14.0
    for mark in "%,.(":
        text = ("가나다라마" + mark) * 14
        widths = [size if is_wide(c) else size / 2 for c in text]
        widths = apply_autospace(text, widths, prof.text.autospace * size, is_wide, lambda c: c.isascii() and c.isalnum())
        total, n = 0.0, 0
        for w in widths:
            total += w
            if total > room:
                break
            n += 1
        assert n == 37


def _spacing_after(tmp_path, blocks, relaxed):
    from doc2report.ir import Document
    from doc2report.layout.flow import FlowPlan

    prof = load_profile("formal")
    out = tmp_path / "o.docx"
    docx_writer.DocxRenderer(prof, {}, FlowPlan(relaxed=relaxed)).save(Document(blocks=blocks), out)
    return {p.text.strip(): (p.paragraph_format.space_after.pt if p.paragraph_format.space_after is not None else None)
            for p in OpenDocx(str(out)).paragraphs}


def test_dot_level_spacing_rules(tmp_path):
    """2026-10-03 사용자: "- · -"에서 · 뒤는 12pt(18pt는 너무 큼), · 목록끼리는 단락 뒤 간격 없이 줄간격만."""
    from doc2report.ir import ListItem, Run

    def item(text, depth):
        return ListItem(runs=[Run(text)], depth=depth, marker={2: "-", 3: "·", 1: "□"}[depth])

    blocks = [item("대시1", 2), item("점1", 3), item("점2", 3), item("대시2", 2), item("점3", 3), item("네모", 1)]
    for relaxed in (False, True):
        after = _spacing_after(tmp_path, blocks, relaxed)
        assert after["- 대시1"] == (6 if relaxed else 0)    # - → · 내려감: 여유 6pt, 빡빡하면 0
        assert after["· 점1"] == 0                         # · → · : 간격 없음
        assert after["· 점2"] == 12                        # · → - : 12pt (여유 모드에서도 18pt로 늘리지 않는다)
    after = _spacing_after(tmp_path, blocks, True)
    assert after["· 점3"] == 18                            # · → □ 로 올라갈 때는 여유 모드의 18pt
    assert _spacing_after(tmp_path, blocks, False)["· 점3"] == 12


def test_note_gap_follows_level_it_belongs_to(tmp_path):
    """2026-10-03 사용자: ※ 뒤 간격은 ※가 속한 계층 기준 — ·→2.는 큰 변화라 18pt 유지, ·→-는 6pt(여유 시 12pt)."""
    from doc2report.ir import ListItem, Run

    def item(text, depth, marker):
        return ListItem(runs=[Run(text)], depth=depth, marker=marker)

    to_section = [item("점", 3, "·"), item("참고1", 3, "※"), item("절", 0, "2.")]
    to_dash = [item("점", 3, "·"), item("참고2", 3, "※"), item("대시", 2, "-")]
    for relaxed in (False, True):
        assert _spacing_after(tmp_path, to_section, relaxed)["※ 참고1"] == 18
    assert _spacing_after(tmp_path, to_dash, False)["※ 참고2"] == 6
    assert _spacing_after(tmp_path, to_dash, True)["※ 참고2"] == 12


def test_heading_like_square_gets_12pt_but_sentence_square_6pt(tmp_path, fake_fonts):
    """2026-10-03 사용자: "□ 추진 방향"(제목 같은 □) 아래 -는 12pt, "□ 요지 문장, …" 아래는 6pt."""
    doc, _ = _convert(tmp_path, "□ 추진 방향\n- 가\n□ 채용 현황 : 입사 확정 27명, 처우 협의 6명\n- 나\n")
    after = {p.text.strip(): p.paragraph_format.space_after for p in doc.paragraphs}
    assert after["□ 추진 방향"] == Pt(12)
    assert after["□ 채용 현황 : 입사 확정 27명, 처우 협의 6명"] == Pt(6)


def test_end_mark_is_added_once_right_aligned(tmp_path, fake_fonts):
    """2026-10-03: 정답 5건 모두 문서 끝에 오른쪽 "- 이 상 -". 원문 끝에 이미 있으면 한 번만."""
    for text in ("□ 가\n", "□ 가\n- 이 상 -\n"):
        doc, _ = _convert(tmp_path, text)
        marks = [p for p in doc.paragraphs if p.text.strip() == "- 이 상 -"]
        assert len(marks) == 1 and doc.paragraphs[-1].text.strip() == "- 이 상 -"
        assert marks[0].alignment == 2   # WD_ALIGN_PARAGRAPH.RIGHT
