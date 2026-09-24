"""렌더링 결과가 실제 docx XML에 반영되는지 — 서식이 바뀔 때 회귀를 잡는 그물."""

from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document as DocxDocument
from docx.oxml.ns import qn

from doc2report.pipeline import convert
from doc2report.profile import load_profile
from doc2report.units import emu_to_dxa, emu_to_pt

FIXTURE = Path(__file__).parent / "fixtures" / "sample_report.md"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("render") / "report.docx"
    result = convert(str(FIXTURE), out, "default")
    return result, DocxDocument(str(out))


def test_document_opens_and_has_content(built):
    _, docx = built
    assert len(docx.paragraphs) > 5
    assert len(docx.tables) == 1


def test_page_setup_matches_profile(built):
    _, docx = built
    profile = load_profile("default")
    section = docx.sections[0]
    # docx는 길이를 twips로 저장하므로 1 twip(635 EMU) 범위의 반올림 오차를 허용한다.
    assert abs(int(section.page_width) - profile.page.width) <= 635
    assert abs(int(section.top_margin) - profile.page.margin.top) <= 635
    assert abs(int(section.left_margin) - profile.page.margin.left) <= 635


def test_table_never_exceeds_usable_width(built):
    result, docx = built
    profile = load_profile("default")
    limit = emu_to_dxa(profile.page.usable_width)
    for table in docx.tables:
        widths = [int(col.get(qn("w:w")))
                  for col in table._tbl.find(qn("w:tblGrid")).findall(qn("w:gridCol"))]
        assert sum(widths) <= limit, f"표 폭 {sum(widths)} > 사용가능폭 {limit}"


def test_table_layout_is_fixed_and_header_repeats(built):
    _, docx = built
    tbl_pr = docx.tables[0]._tbl.tblPr
    assert tbl_pr.find(qn("w:tblLayout")).get(qn("w:type")) == "fixed"
    first_row = docx.tables[0].rows[0]._tr
    assert first_row.find(qn("w:trPr")).find(qn("w:tblHeader")) is not None


def test_korean_font_is_written_to_east_asia_attribute(built):
    _, docx = built
    profile = load_profile("default")
    body = profile.font("body")
    found = set()
    for paragraph in docx.paragraphs:
        for run in paragraph.runs:
            rpr = run._element.find(qn("w:rPr"))
            if rpr is None:
                continue
            fonts = rpr.find(qn("w:rFonts"))
            if fonts is not None and fonts.get(qn("w:eastAsia")):
                found.add(fonts.get(qn("w:eastAsia")))
    assert body.east_asia in found


def test_body_font_size_matches_profile(built):
    _, docx = built
    profile = load_profile("default")
    expected = emu_to_pt(profile.font("body").size)
    sizes = [emu_to_pt(int(run.font.size))
             for paragraph in docx.paragraphs for run in paragraph.runs
             if run.font.size and paragraph.text.strip()]
    assert expected in sizes


def test_list_markers_come_from_profile(built):
    _, docx = built
    profile = load_profile("default")
    markers = {level.marker for level in profile.numbering if level.marker}
    texts = [p.text for p in docx.paragraphs]
    assert any(any(text.startswith(m) for m in markers) for text in texts)


def test_changes_are_reported(built):
    result, _ = built
    assert result.changes
    assert "개조식" in result.report()
