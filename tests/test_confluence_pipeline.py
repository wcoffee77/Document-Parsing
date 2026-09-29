"""Confluence storage 문서가 나머지 파이프라인(문구 다듬기 → 단계 접기 → 표 맞춤 →
렌더)까지 실제 Confluence 계정 없이 끝까지 도는지 확인한다.

실제 Confluence REST API 호출(sources/confluence.py::load_confluence)은 사내 인증
정보와 네트워크가 있어야 해서 여기서는 검증하지 못한다 — parse_confluence_storage가
돌려주는 IR부터 그 뒤 단계를 그대로 태운다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document as DocxDocument

from doc2report.layout.flow import plan_flow
from doc2report.layout.table_fit import plan_tables
from doc2report.parsers.confluence_storage import parse_confluence_storage
from doc2report.profile import load_profile
from doc2report.render.docx_writer import DocxRenderer
from doc2report.transform import apply_text_rules
from doc2report.transform.structure import fold_headings_into_levels
from doc2report.units import emu_to_mm

FIXTURE = Path(__file__).parent / "fixtures" / "confluence_sample.xhtml"


@pytest.fixture(scope="module")
def profile():
    return load_profile("default")


@pytest.fixture(scope="module")
def docx(tmp_path_factory, profile):
    xhtml = FIXTURE.read_text(encoding="utf-8")
    parsed = parse_confluence_storage(xhtml, title="분기 개선 보고")
    doc = parsed.document

    transformed = apply_text_rules(doc, profile)
    doc = transformed.document
    doc, _ = fold_headings_into_levels(doc)

    layouts = plan_tables(doc, profile)
    flow = plan_flow(doc, profile, layouts)
    renderer = DocxRenderer(profile, layouts, flow)

    out = tmp_path_factory.mktemp("confluence") / "out.docx"
    renderer.save(doc, out)
    return DocxDocument(str(out)), layouts, profile


def test_wide_confluence_table_fits_the_page(docx):
    document, layouts, profile = docx
    usable = profile.page.usable_width
    assert layouts, "표가 하나 이상 인식되어야 한다"
    for layout in layouts.values():
        assert layout.total_width <= usable + 1, (
            f"표 폭 {emu_to_mm(layout.total_width):.1f}mm이 "
            f"사용 가능 폭 {emu_to_mm(usable):.1f}mm을 넘음"
        )


def test_merged_cells_survive_into_the_docx_table(docx):
    """colspan/rowspan이 실제 Word 표 병합으로 반영되는지 — python-docx는 병합된
    셀들을 같은 _tc(그리드 셀) 객체로 노출한다."""
    document, layouts, profile = docx
    table = document.tables[0]
    # colspan=2였던 "응답시간" 헤더: 두 그리드 열이 같은 셀을 가리켜야 한다.
    header = table.rows[0].cells
    assert header[1]._tc is header[2]._tc
    # rowspan=2였던 "조회 API": 두 그리드 행이 같은 셀을 가리켜야 한다.
    body_col0 = [table.rows[1].cells[0], table.rows[2].cells[0]]
    assert body_col0[0]._tc is body_col0[1]._tc
    assert body_col0[0].text == "조회 API"


def test_panel_code_and_nested_list_all_made_it_through(docx):
    document, _, _ = docx
    texts = [p.text for p in document.paragraphs]
    assert any("검토 필요" in t for t in texts)  # "검토가 필요합니다" → 명사 종결
    assert any("SELECT idx_name" in t for t in texts)
    assert any(t.startswith("□\t") and "2차 성능 시험" in t for t in texts)
    assert any(t.startswith("-\t") and "10월 중 실시" in t for t in texts)


def test_bracket_table_caption_keeps_brackets_alignment_and_drops_prefix(tmp_path, profile):
    """표 앞 "【사업현황】"(왼쪽 정렬로 작성)이 "<표 1> 사업현황"처럼 꺾쇠가
    벗겨지거나 가운데 정렬로 강제되면 안 된다 — 꺾쇠·정렬 모두 원문 그대로,
    앞에 붙던 "-"만 없어져야 한다(2026-09-29 사용자 요청)."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    from doc2report.transform.structure import attach_table_captions

    xhtml = """
    <p style="text-align: left;">【사업현황】</p>
    <table><tbody><tr><td>A</td><td>1</td></tr></tbody></table>
    """
    parsed = parse_confluence_storage(xhtml, title="캡션 테스트")
    doc = parsed.document
    transformed = apply_text_rules(doc, profile)
    doc, _ = attach_table_captions(transformed.document)
    doc, _ = fold_headings_into_levels(doc)

    layouts = plan_tables(doc, profile)
    flow = plan_flow(doc, profile, layouts)
    renderer = DocxRenderer(profile, layouts, flow)
    out = tmp_path / "caption.docx"
    renderer.save(doc, out)

    document = DocxDocument(str(out))
    caption = next(p for p in document.paragraphs if "사업현황" in p.text)
    assert caption.text == "【사업현황】"
    assert caption.alignment == WD_ALIGN_PARAGRAPH.LEFT
