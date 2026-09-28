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


def test_callout_after_table_is_pushed_down(tmp_path, profile):
    """표 바로 뒤에 오는 인용문(Callout)도 표에 붙지 않고 간격이 확보된다."""
    out = tmp_path / "sample.docx"
    convert(str(FIXTURE), out, profile)
    docx = DocxDocument(str(out))
    quote = next(p for p in docx.paragraphs if p.text.startswith("측정 기준은"))
    assert int(quote.paragraph_format.space_before or 0) >= profile.tables.space_after
