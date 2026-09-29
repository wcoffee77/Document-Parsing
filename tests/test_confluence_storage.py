"""Confluence storage format(XHTML) → IR 파서.

실제 Confluence 인스턴스 없이 검증해야 하므로, REST API가 돌려주는 body.storage.value와
같은 모양의 XHTML을 고정 값으로 넣어 확인한다. 가장 중요한 것은 표의 병합 셀
(rowspan/colspan) — 마크다운 경유로는 표현할 수 없어 CLAUDE.md에도 "실제로 타본 적이
없다"고 적혀 있던 부분이다.
"""

from __future__ import annotations

from doc2report.ir import Callout, CodeBlock, Heading, Image, ListItem, Paragraph, Table, plain
from doc2report.parsers.confluence_storage import parse_confluence_storage


def test_heading_and_paragraph_with_inline_formatting():
    xhtml = """
    <h2>추진 배경</h2>
    <p>응답 지연이 <strong>지속적으로</strong> 발생했고 <em>피크 시간대</em>에 특히
    심했다. 자세한 내용은 <a href="https://example.com/x">여기</a> 참고.</p>
    """
    parsed = parse_confluence_storage(xhtml, title="문서 제목")
    doc = parsed.document
    assert doc.title == "문서 제목"
    assert isinstance(doc.blocks[0], Heading)
    assert plain(doc.blocks[0].runs) == "추진 배경"

    para = doc.blocks[1]
    assert isinstance(para, Paragraph)
    bold_run = next(r for r in para.runs if "지속적으로" in r.text)
    assert bold_run.bold
    italic_run = next(r for r in para.runs if "피크 시간대" in r.text)
    assert italic_run.italic
    link_run = next(r for r in para.runs if r.text == "여기")
    assert link_run.href == "https://example.com/x"


def test_first_h1_becomes_title_when_not_given():
    xhtml = "<h1>보고서 제목</h1><p>본문</p>"
    parsed = parse_confluence_storage(xhtml)
    assert parsed.document.title == "보고서 제목"
    assert len(parsed.document.blocks) == 1


def test_nested_list_with_inline_formatting_and_no_p_wrapper():
    """Confluence는 <li>텍스트</li>처럼 <p> 없이 바로 인라인을 넣는 경우가 흔하다."""
    xhtml = """
    <ul>
      <li>인덱스 재설계
        <ul>
          <li>복합 인덱스 <strong>3건</strong> 추가</li>
        </ul>
      </li>
      <li>캐시 도입</li>
    </ul>
    """
    parsed = parse_confluence_storage(xhtml)
    items = [b for b in parsed.document.blocks if isinstance(b, ListItem)]
    assert [i.depth for i in items] == [0, 1, 0]
    assert plain(items[0].runs) == "인덱스 재설계"
    assert plain(items[2].runs) == "캐시 도입"
    bold_run = next(r for r in items[1].runs if r.bold)
    assert bold_run.text == "3건"


def test_table_with_colspan_and_rowspan_is_preserved():
    """마크다운 경유로는 표현할 수 없는 병합 셀 — storage 경로의 핵심 이유."""
    xhtml = """
    <table>
      <tbody>
        <tr><th colspan="2">개선 결과</th><th>담당</th></tr>
        <tr><td rowspan="2">조회 API</td><td>3200ms → 480ms</td><td>플랫폼팀</td></tr>
        <tr><td>85% 개선</td><td>-</td></tr>
      </tbody>
    </table>
    """
    parsed = parse_confluence_storage(xhtml)
    table = next(b for b in parsed.document.blocks if isinstance(b, Table))
    assert table.header_rows == 1
    assert table.rows[0].cells[0].colspan == 2
    assert table.rows[0].cells[0].is_header
    assert table.rows[1].cells[0].rowspan == 2
    assert table.col_count == 3


def test_cell_with_br_becomes_separate_paragraphs_not_merged():
    """<br>만으로 줄을 나눈 셀(<p> 없이)이 한 줄로 뭉개지면 안 된다 —
    실제 사내 Confluence 문서 변환에서 "ㅇㅇㅇㅁㅁㅁㄷㄷㄷ"처럼 겹쳐 나온 버그."""
    xhtml = "<table><tbody><tr><td>ㅇㅇㅇ<br/>ㅁㅁㅁ<br/>ㄷㄷㄷ</td></tr></tbody></table>"
    parsed = parse_confluence_storage(xhtml)
    table = next(b for b in parsed.document.blocks if isinstance(b, Table))
    cell = table.rows[0].cells[0]
    paragraphs = [b for b in cell.blocks if isinstance(b, Paragraph)]
    assert [plain(p.runs) for p in paragraphs] == ["ㅇㅇㅇ", "ㅁㅁㅁ", "ㄷㄷㄷ"]


def test_paragraph_with_br_splits_into_separate_paragraphs():
    xhtml = "<p>ㅇㅇㅇ<br/>ㅁㅁㅁ</p>"
    parsed = parse_confluence_storage(xhtml)
    paragraphs = [b for b in parsed.document.blocks if isinstance(b, Paragraph)]
    assert [plain(p.runs) for p in paragraphs] == ["ㅇㅇㅇ", "ㅁㅁㅁ"]


def test_table_without_header_row_has_zero_header_rows():
    xhtml = "<table><tbody><tr><td>a</td><td>b</td></tr></tbody></table>"
    parsed = parse_confluence_storage(xhtml)
    table = next(b for b in parsed.document.blocks if isinstance(b, Table))
    assert table.header_rows == 0
    assert not table.rows[0].cells[0].is_header


def test_info_panel_becomes_callout():
    xhtml = """
    <ac:structured-macro ac:name="warning">
      <ac:rich-text-body><p>운영 중 변경 금지</p></ac:rich-text-body>
    </ac:structured-macro>
    """
    parsed = parse_confluence_storage(xhtml)
    callout = parsed.document.blocks[0]
    assert isinstance(callout, Callout)
    assert callout.kind == "warning"
    assert plain(callout.blocks[0].runs) == "운영 중 변경 금지"


def test_code_macro_becomes_code_block():
    xhtml = """
    <ac:structured-macro ac:name="code">
      <ac:parameter ac:name="language">sql</ac:parameter>
      <ac:plain-text-body><![CDATA[SELECT 1 FROM dual;]]></ac:plain-text-body>
    </ac:structured-macro>
    """
    parsed = parse_confluence_storage(xhtml)
    code = parsed.document.blocks[0]
    assert isinstance(code, CodeBlock)
    assert code.lang == "sql"
    assert code.text == "SELECT 1 FROM dual;"


def test_image_attachment_reference():
    xhtml = """
    <ac:image ac:width="400">
      <ri:attachment ri:filename="구조도.png" />
    </ac:image>
    """
    parsed = parse_confluence_storage(xhtml)
    image = next(b for b in parsed.document.blocks if isinstance(b, Image))
    assert image.src == "구조도.png"
    assert image.width_px == 400


def test_unknown_macro_without_body_is_reported_not_silently_dropped():
    """설계 원칙: 조용히 버리지 않고 --report로 검수 가능하게 남긴다."""
    xhtml = '<ac:structured-macro ac:name="jira-issue" />'
    parsed = parse_confluence_storage(xhtml)
    assert parsed.document.blocks == []
    assert any("jira-issue" in note for note in parsed.notes)
