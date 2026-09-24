"""지면 여유 판단 — "공간이 충분하면 넉넉하게" 규칙의 근거."""

from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document as DocxDocument
from docx.oxml.ns import qn

from doc2report.ir import Document, ListItem, Run
from doc2report.layout.flow import plan_flow
from doc2report.pipeline import convert
from doc2report.profile import load_profile

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def profile():
    return load_profile("default")


def test_short_document_has_room_to_breathe(profile):
    doc = Document(blocks=[ListItem(depth=0, runs=[Run("짧은 항목")]),
                           ListItem(depth=1, runs=[Run("하위 항목")])],
                   title="짧은 보고서")
    plan = plan_flow(doc, profile, {})
    assert plan.pages == 1
    assert plan.relaxed is True
    assert plan.notes


def test_nearly_full_page_stays_tight(tmp_path, profile):
    """쪽을 거의 채운 문서는 간격을 늘리지 않는다 (늘리면 쪽이 넘어가므로).

    company_format.md는 실제 Word 렌더에서 한 쪽의 90% 가까이 찬다.
    """
    result = convert(str(FIXTURES / "company_format.md"), tmp_path / "c.docx", profile)
    assert result.flow.relaxed is False

    docx = DocxDocument(str(tmp_path / "c.docx"))
    spacings = {int(p.paragraph_format.space_after or 0) for p in docx.paragraphs
                if p.text.startswith(("1.\t", "□\t", "-\t"))}
    assert profile.numbering_level(0).space_after_level_change in spacings
    assert profile.numbering_level(0).space_after_level_change_max not in spacings


def test_estimate_is_close_to_reality(tmp_path, profile):
    """어림한 쪽 수가 실제 렌더 결과와 맞아야 판단을 믿을 수 있다."""
    out = tmp_path / "company.docx"
    result = convert(str(FIXTURES / "company_format.md"), out, profile)
    assert result.flow.pages == 1  # Word 렌더 결과도 1쪽 (tools/score_corpus.py로 확인)
    assert result.flow.estimated_height < profile.page.usable_height


def test_relaxed_document_gets_taller_rows(tmp_path, profile):
    out = tmp_path / "wide.docx"
    result = convert(str(FIXTURES / "wide_table.md"), out, profile)
    assert result.flow.relaxed is True

    table = DocxDocument(str(out)).tables[0]
    height = table.rows[0]._tr.find(qn("w:trPr")).find(qn("w:trHeight"))
    assert int(height.get(qn("w:val"))) == pytest.approx(
        profile.tables.row_height_relaxed / 635, abs=1)


def test_relaxed_document_gets_wider_gaps(tmp_path, profile):
    out = tmp_path / "wide.docx"
    convert(str(FIXTURES / "wide_table.md"), out, profile)
    docx = DocxDocument(str(out))
    spacings = {int(p.paragraph_format.space_after or 0) for p in docx.paragraphs
                if p.text.startswith(("1.\t", "□\t", "-\t"))}
    assert profile.numbering_level(0).space_after_level_change_max in spacings
