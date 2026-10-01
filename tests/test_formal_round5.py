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
    assert paragraphs["※ 참고 사항"].paragraph_format.space_after == gap         # ※ 뒤 18pt
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


def test_table_starts_at_the_line_above(tmp_path):
    doc, _ = _convert(tmp_path, _TABLES)
    xml = doc.element.xml
    assert re.search(r'<w:tblInd w:w="\d+" w:type="dxa"/>', xml)                 # □ 줄의 왼쪽 끝(앞 공백 1칸)


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
