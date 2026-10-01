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
    assert all(r.font.size == Pt(12) for r in note.runs if r.text.strip())


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
                         pad=rules.condense_pad)
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
    return [p.text.rstrip() for p in doc.paragraphs]


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
    assert after["□ 나"] == Pt(6)                          # □ → - 내려감은 6pt 그대로
