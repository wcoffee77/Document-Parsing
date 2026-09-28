"""제목 접기(fold_headings_into_levels) — 특히 Confluence 문서에 흔한, 제목에
이미 번호가 박혀 있는 경우("## 1. 추진 배경")를 다룬다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document as DocxDocument

from doc2report.ir import Document, Heading, Run
from doc2report.pipeline import convert
from doc2report.profile import load_profile
from doc2report.transform.structure import fold_headings_into_levels

FIXTURE = Path(__file__).parent / "fixtures" / "sample_report.md"


@pytest.fixture
def profile():
    return load_profile("default")


def test_existing_heading_number_is_not_duplicated():
    """"## 1. 추진 배경"처럼 제목에 이미 번호가 있으면 프로파일이 매기는 말머리와
    겹치지 않도록 원래 번호를 뗀다 ("1.\\t1. 추진 배경"이 아니라 "1.\\t추진 배경")."""
    doc = Document(blocks=[Heading(level=2, runs=[Run("1. 추진 배경")])])
    folded, changes = fold_headings_into_levels(doc)
    assert folded.blocks[0].runs[0].text == "추진 배경"
    assert len(changes) == 1
    assert changes[0].before == "1. 추진 배경"
    assert changes[0].after == "추진 배경"


def test_heading_without_number_is_untouched():
    doc = Document(blocks=[Heading(level=2, runs=[Run("추진 배경")])])
    folded, changes = fold_headings_into_levels(doc)
    assert folded.blocks[0].runs[0].text == "추진 배경"
    assert changes == []


def test_sample_report_headings_are_not_double_numbered(tmp_path, profile):
    out = tmp_path / "sample.docx"
    convert(str(FIXTURE), out, profile)
    docx = DocxDocument(str(out))
    numbered = [p.text for p in docx.paragraphs if p.text.startswith(("1.\t", "2.\t", "3.\t", "4.\t"))]
    assert numbered, "번호 매겨진 단계가 있어야 한다"
    for text in numbered:
        marker, _, rest = text.partition("\t")
        assert not rest.startswith(marker), f"제목 번호가 겹침: {text!r}"


@pytest.mark.parametrize("text", ["1.1. 추진 배경", "1.추진 배경", "(1) 추진 배경", "2) 추진 배경"])
def test_other_manual_number_styles_are_stripped(text):
    doc = Document(blocks=[Heading(level=2, runs=[Run(text)])])
    folded, _ = fold_headings_into_levels(doc)
    assert folded.blocks[0].runs[0].text == "추진 배경"


@pytest.mark.parametrize("text", ["1.5배 향상 방안", "2026년 계획", "3D 설계"])
def test_headings_that_merely_start_with_a_number_are_kept(text):
    doc = Document(blocks=[Heading(level=2, runs=[Run(text)])])
    folded, changes = fold_headings_into_levels(doc)
    assert folded.blocks[0].runs[0].text == text
    assert changes == []


def test_quote_under_table_becomes_small_star_note(tmp_path, profile):
    """표 아래 설명(인용문)은 '* '로 시작하는 표 주석이 되고, 글자는 table_note 크기."""
    out = tmp_path / "sample.docx"
    convert(str(FIXTURE), out, profile)
    docx = DocxDocument(str(out))
    note = next(p for p in docx.paragraphs if "측정 기준은" in p.text)
    assert note.text.startswith(f"{profile.tables.note_marker} ")
    assert all(int(run.font.size) == profile.font("table_note").size for run in note.runs)
    # 주석은 표에 붙어 있고, '표 뒤 간격'은 그 다음 항목이 가져간다.
    assert int(note.paragraph_format.space_before or 0) < profile.tables.space_after
    following = next(p for p in docx.paragraphs if p.text.startswith("4.\t"))
    assert int(following.paragraph_format.space_before or 0) >= profile.tables.space_after


def test_star_paragraph_under_table_is_a_note():
    from doc2report.ir import Cell, Paragraph, Row, Table
    from doc2report.transform.structure import attach_table_notes

    table = Table(rows=[Row(cells=[Cell(blocks=[Paragraph(runs=[Run("a")])])])])
    doc = Document(blocks=[table, Paragraph(runs=[Run("※ 단위: 천원")]),
                           Paragraph(runs=[Run("본문")])])
    attached, changes = attach_table_notes(doc, ["*", "※"], "*")
    assert [len(b.notes) if isinstance(b, Table) else None for b in attached.blocks] == [1, None]
    assert table.notes[0][0].text == "단위: 천원"
    assert changes[0].after == "* 단위: 천원"
