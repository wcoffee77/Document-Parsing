"""python-docx가 직접 다루지 못하는 OOXML 조작을 한곳에 모은 헬퍼.

한글 글꼴 지정(w:eastAsia), 고정 표 레이아웃, 머리행 반복, 셀 여백 등은
python-docx API에 없어서 XML을 직접 손대야 한다. 흩어지면 유지보수가 어려워지므로
docx 스키마를 아는 코드는 이 파일에만 둔다.

주의: OOXML은 자식 요소 순서가 스키마로 고정되어 있다. 순서를 어기면 Word가
파일 열기를 거부하므로, 새 요소는 반드시 _ordered()로 제 위치에 끼워 넣는다.
"""

from __future__ import annotations

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.oxml.shared import OxmlElement
from docx.shared import Emu, Pt, RGBColor

from ..profile import FontSpec, TableRules
from ..units import emu_to_dxa, emu_to_eighth_pt, emu_to_pt

ALIGN_VALUES = {
    "left": WD_ALIGN_PARAGRAPH.LEFT, "왼쪽": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER, "가운데": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT, "오른쪽": WD_ALIGN_PARAGRAPH.RIGHT,
    "both": WD_ALIGN_PARAGRAPH.JUSTIFY, "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
    "양쪽": WD_ALIGN_PARAGRAPH.JUSTIFY,
    "distribute": WD_ALIGN_PARAGRAPH.DISTRIBUTE, "배분": WD_ALIGN_PARAGRAPH.DISTRIBUTE,
}
_TABLE_JC = {"left": "left", "center": "center", "right": "right",
             "왼쪽": "left", "가운데": "center", "오른쪽": "right"}

# ECMA-376이 정한 자식 요소 순서 (필요한 부분만 발췌)
_SEQ: dict[str, tuple[str, ...]] = {
    "w:pPr": (
        "w:pStyle", "w:keepNext", "w:keepLines", "w:pageBreakBefore", "w:framePr",
        "w:widowControl", "w:numPr", "w:suppressLineNumbers", "w:pBdr", "w:shd", "w:tabs",
        "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap", "w:overflowPunct",
        "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN", "w:bidi", "w:adjustRightInd",
        "w:snapToGrid", "w:spacing", "w:ind", "w:contextualSpacing", "w:mirrorIndents",
        "w:suppressOverlap", "w:jc", "w:textDirection", "w:textAlignment",
        "w:textboxTightWrap", "w:outlineLvl", "w:divId", "w:cnfStyle", "w:rPr", "w:sectPr",
    ),
    "w:pBdr": ("w:top", "w:left", "w:bottom", "w:right", "w:between", "w:bar"),
    "w:rPr": (
        "w:rStyle", "w:rFonts", "w:b", "w:bCs", "w:i", "w:iCs", "w:caps", "w:smallCaps",
        "w:strike", "w:dstrike", "w:outline", "w:shadow", "w:emboss", "w:imprint",
        "w:noProof", "w:snapToGrid", "w:vanish", "w:webHidden", "w:color", "w:spacing",
        "w:w", "w:kern", "w:position", "w:sz", "w:szCs", "w:highlight", "w:u", "w:effect",
        "w:bdr", "w:shd", "w:fitText", "w:vertAlign", "w:rtl", "w:cs", "w:em", "w:lang",
        "w:eastAsianLayout", "w:specVanish", "w:oMath",
    ),
    "w:tblPr": (
        "w:tblStyle", "w:tblpPr", "w:tblOverlap", "w:bidiVisual", "w:tblStyleRowBandSize",
        "w:tblStyleColBandSize", "w:tblW", "w:jc", "w:tblCellSpacing", "w:tblInd",
        "w:tblBorders", "w:shd", "w:tblLayout", "w:tblCellMar", "w:tblLook",
    ),
    "w:tblBorders": ("w:top", "w:start", "w:left", "w:bottom", "w:end", "w:right",
                     "w:insideH", "w:insideV"),
    "w:tcBorders": ("w:top", "w:start", "w:left", "w:bottom", "w:end", "w:right",
                    "w:insideH", "w:insideV", "w:tl2br", "w:tr2bl"),
    "w:tblCellMar": ("w:top", "w:start", "w:left", "w:bottom", "w:end", "w:right"),
    "w:tcPr": (
        "w:cnfStyle", "w:tcW", "w:gridSpan", "w:hMerge", "w:vMerge", "w:tcBorders",
        "w:shd", "w:noWrap", "w:tcMar", "w:textDirection", "w:tcFitText", "w:vAlign",
        "w:hideMark",
    ),
    "w:trPr": (
        "w:cnfStyle", "w:divId", "w:gridBefore", "w:gridAfter", "w:wBefore", "w:wAfter",
        "w:cantSplit", "w:trHeight", "w:tblHeader", "w:tblCellSpacing", "w:jc", "w:hidden",
    ),
}


def _ordered(parent, tag: str):
    """스키마 순서를 지켜 자식 요소를 가져오거나 만든다."""
    found = parent.find(qn(tag))
    if found is not None:
        return found
    element = OxmlElement(tag)
    sequence = _SEQ.get(_localname(parent))
    if sequence is None or tag not in sequence:
        parent.append(element)
        return element
    successors = sequence[sequence.index(tag) + 1 :]
    for sibling in parent:
        if _localname_of(sibling) in successors:
            sibling.addprevious(element)
            return element
    parent.append(element)
    return element


def _localname(element) -> str:
    return "w:" + element.tag.split("}")[-1]


def _localname_of(element) -> str:
    try:
        return "w:" + element.tag.split("}")[-1]
    except Exception:
        return ""


# ── 런 / 문단 ───────────────────────────────────────────────────────────


def apply_run_format(run, spec: FontSpec) -> None:
    font = run.font
    if spec.latin:
        font.name = spec.latin  # ascii + hAnsi
    if spec.size:
        font.size = Pt(emu_to_pt(spec.size))
    if spec.bold is not None:
        font.bold = spec.bold
    if spec.italic is not None:
        font.italic = spec.italic
    if spec.underline is not None:
        font.underline = spec.underline
    if spec.color:
        font.color.rgb = RGBColor.from_string(spec.color.lstrip("#").upper())
    if spec.east_asia:
        # 한글 글꼴은 python-docx API에 없어 rFonts에 직접 넣는다.
        rfonts = run._element.get_or_add_rPr().get_or_add_rFonts()
        rfonts.set(qn("w:eastAsia"), spec.east_asia)
        if not spec.latin:
            rfonts.set(qn("w:ascii"), spec.east_asia)
            rfonts.set(qn("w:hAnsi"), spec.east_asia)
    if spec.char_scale and abs(spec.char_scale - 1.0) > 1e-6:
        # 장평 — python-docx API에 없다. 값은 백분율 정수(90 = 90%).
        scale = _ordered(run._element.get_or_add_rPr(), "w:w")
        scale.set(qn("w:val"), str(int(round(spec.char_scale * 100))))


_VML_NS = ('xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office" '
           'xmlns:w10="urn:schemas-microsoft-com:office:word"')
_SHAPETYPE = ('<v:shapetype id="_x0000_t202" coordsize="21600,21600" o:spt="202" path="m,l,21600r21600,l21600,xe">'
              '<v:stroke joinstyle="miter"/><v:path gradientshapeok="t" o:connecttype="rect"/></v:shapetype>')


def add_text_box(paragraph, *, runs: list[tuple[str, bool]], spec: FontSpec, x: int, y: int,
                 width: int, height: int, number: int) -> None:
    """윗줄(paragraph)에 붙은 **글자 앞** 텍스트 상자 — 정식보고서의 주석(2026-10-01 사용자).

    VML(Word 2007부터 읽고 저장 때 새 형식으로 바꾼다)로 쓴다. 테두리·배경색 없음, 안쪽 여백 0.
    x는 본문 왼쪽 끝에서, y는 윗줄 문단 맨 위에서 상자 맨 위·왼쪽까지의 거리(EMU).
    runs = [(글자, 굵게)]. 같은 문서의 두 번째 상자부터는 도형 형식 정의를 다시 넣지 않는다."""
    from xml.sax.saxutils import escape

    def pt(value: int) -> str:
        return f"{emu_to_pt(value):.2f}pt"

    run_xml = ""
    for text, bold in runs:
        props = ""
        if spec.east_asia or spec.latin:
            props += (f'<w:rFonts w:ascii="{spec.latin or spec.east_asia}" w:hAnsi="{spec.latin or spec.east_asia}" '
                      f'w:eastAsia="{spec.east_asia or spec.latin}"/>')
        if bold or spec.bold:
            props += "<w:b/>"
        if spec.color:
            props += f'<w:color w:val="{spec.color.lstrip("#").upper()}"/>'
        if spec.size:
            half = int(round(emu_to_pt(spec.size) * 2))
            props += f'<w:sz w:val="{half}"/><w:szCs w:val="{half}"/>'
        run_xml += (f'<w:r><w:rPr>{props}</w:rPr><w:t xml:space="preserve">{escape(text)}</w:t></w:r>')
    line = int(round((spec.line_spacing or 1.0) * 240))
    body = (f'<w:p><w:pPr><w:spacing w:before="0" w:after="0" w:line="{line}" w:lineRule="auto"/>'
            f'<w:jc w:val="left"/></w:pPr>{run_xml}</w:p>')
    shape = (f'<v:shape id="TextBox{number}" o:spid="_x0000_s{1025 + number}" type="#_x0000_t202" '
             f'style="position:absolute;margin-left:{pt(x)};margin-top:{pt(y)};width:{pt(width)};'
             f'height:{pt(height)};z-index:{251658240 + number};mso-position-horizontal-relative:margin;'
             f'mso-position-vertical-relative:text" filled="f" stroked="f">'
             f'<v:textbox inset="0,0,0,0"><w:txbxContent>{body}</w:txbxContent></v:textbox>'
             f'<w10:wrap type="none"/></v:shape>')
    holder = parse_xml(f'<w:r {nsdecls("w")} {_VML_NS}><w:pict>{_SHAPETYPE if number == 1 else ""}{shape}</w:pict></w:r>')
    paragraph._p.append(holder)


def set_char_spacing(run, twips: int) -> None:
    """글자 간격(1/20pt). 음수는 좁힘 — 줄이 아슬아슬하게 넘칠 때 줄 바뀜을 막는다."""
    spacing = _ordered(run._element.get_or_add_rPr(), "w:spacing")
    spacing.set(qn("w:val"), str(twips))


def apply_paragraph_format(paragraph, spec: FontSpec, *, indent: bool = True) -> None:
    fmt = paragraph.paragraph_format
    if spec.align:
        alignment = ALIGN_VALUES.get(spec.align.lower())
        if alignment is not None:
            fmt.alignment = alignment
    if spec.space_before is not None:
        fmt.space_before = Emu(spec.space_before)
    if spec.space_after is not None:
        fmt.space_after = Emu(spec.space_after)
    if spec.line_spacing:
        fmt.line_spacing = spec.line_spacing
    if indent:
        if spec.indent is not None:
            fmt.left_indent = Emu(spec.indent)
        if spec.first_line_indent is not None:
            fmt.first_line_indent = Emu(spec.first_line_indent)
    if spec.keep_next is not None:
        fmt.keep_with_next = spec.keep_next
    if spec.page_break_before is not None:
        fmt.page_break_before = spec.page_break_before


def set_list_indent(paragraph, left: int, hanging: int | None) -> None:
    """목록 들여쓰기 — 말머리 뒤 본문이 가지런히 걸리도록 내어쓰기를 준다."""
    fmt = paragraph.paragraph_format
    fmt.left_indent = Emu(left + (hanging or 0))
    if hanging:
        fmt.first_line_indent = Emu(-hanging)


def add_border(paragraph, edge: str, width_emu: int, color: str, space: str = "1") -> None:
    borders = _ordered(paragraph._p.get_or_add_pPr(), "w:pBdr")
    element = _ordered(borders, f"w:{edge}")
    element.set(qn("w:val"), "single")
    element.set(qn("w:sz"), str(emu_to_eighth_pt(width_emu)))
    element.set(qn("w:space"), space)
    element.set(qn("w:color"), color.lstrip("#"))


def shade_paragraph(paragraph, fill: str) -> None:
    shd = _ordered(paragraph._p.get_or_add_pPr(), "w:shd")
    _set_shd(shd, fill)


def shade_cell(cell, fill: str) -> None:
    shd = _ordered(cell._tc.get_or_add_tcPr(), "w:shd")
    _set_shd(shd, fill)


def _set_shd(shd, fill: str) -> None:
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill.lstrip("#"))


# ── 표 ──────────────────────────────────────────────────────────────────


def set_fixed_layout(table, total_width: int, align: str, indent: int = 0) -> None:
    """Word의 자동 맞춤을 끄고 계산한 폭을 못 박는다."""
    table.autofit = False
    tbl_pr = table._tbl.tblPr
    _ordered(tbl_pr, "w:tblLayout").set(qn("w:type"), "fixed")
    width = _ordered(tbl_pr, "w:tblW")
    width.set(qn("w:w"), str(emu_to_dxa(total_width)))
    width.set(qn("w:type"), "dxa")
    value = _TABLE_JC.get((align or "center").lower())
    if value:
        _ordered(tbl_pr, "w:jc").set(qn("w:val"), value)
    if indent and (align or "").lower() == "left":
        # 왼쪽 정렬 표의 시작점 — 표 바로 윗줄 문장의 왼쪽 끝에 맞춘다(2026-10-01 사용자)
        ind = _ordered(tbl_pr, "w:tblInd")
        ind.set(qn("w:w"), str(emu_to_dxa(indent)))
        ind.set(qn("w:type"), "dxa")


def set_header_rule(table, header_rows: int, width: int, color: str) -> None:
    """머리행과 내용을 가르는 굵은 선 — 머리행 아래 테두리(음영 대신). 머리행 칸의 아래 테두리와 다음 행 칸의
    위 테두리를 같이 지정해 Word가 어느 쪽을 고르든 같은 굵기가 되게 한다(2026-10-01 사용자: 1.5pt)."""
    rows = table.rows
    if not width or header_rows <= 0 or header_rows >= len(rows):
        return
    size = str(emu_to_eighth_pt(width))
    for row_index, edge in ((header_rows - 1, "bottom"), (header_rows, "top")):
        for tc in rows[row_index]._tr.tc_lst:
            borders = _ordered(tc.get_or_add_tcPr(), "w:tcBorders")
            element = _ordered(borders, f"w:{edge}")
            element.set(qn("w:val"), "single")
            element.set(qn("w:sz"), size)
            element.set(qn("w:space"), "0")
            element.set(qn("w:color"), color.lstrip("#"))


def set_table_borders(table, rules: TableRules) -> None:
    if not rules.border_width:
        return
    borders = _ordered(table._tbl.tblPr, "w:tblBorders")
    size = str(emu_to_eighth_pt(rules.border_width))
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        element = _ordered(borders, f"w:{edge}")
        element.set(qn("w:val"), "single")
        element.set(qn("w:sz"), size)
        element.set(qn("w:space"), "0")
        element.set(qn("w:color"), rules.border_color.lstrip("#"))


def set_cell_margins(table, x: int, y: int) -> None:
    margins = _ordered(table._tbl.tblPr, "w:tblCellMar")
    for tag, value in (("top", y), ("left", x), ("bottom", y), ("right", x)):
        element = _ordered(margins, f"w:{tag}")
        element.set(qn("w:w"), str(emu_to_dxa(value)))
        element.set(qn("w:type"), "dxa")


def set_cell_width(cell, width: int) -> None:
    element = _ordered(cell._tc.get_or_add_tcPr(), "w:tcW")
    element.set(qn("w:w"), str(emu_to_dxa(width)))
    element.set(qn("w:type"), "dxa")


def set_grid(table, widths: list[int]) -> None:
    """tblGrid를 계산된 폭으로 다시 쓴다 (Word가 첫 렌더에 참조)."""
    grid = table._tbl.find(qn("w:tblGrid"))
    if grid is None:
        grid = OxmlElement("w:tblGrid")
        table._tbl.tblPr.addnext(grid)
    for child in list(grid):
        grid.remove(child)
    for width in widths:
        col = OxmlElement("w:gridCol")
        col.set(qn("w:w"), str(emu_to_dxa(width)))
        grid.append(col)


def set_vertical_align(cell, value: str) -> None:
    mapped = {"top": "top", "center": "center", "가운데": "center",
              "bottom": "bottom"}.get((value or "center").lower(), "center")
    _ordered(cell._tc.get_or_add_tcPr(), "w:vAlign").set(qn("w:val"), mapped)


def mark_header_row(row) -> None:
    """페이지가 넘어가도 머리행을 반복."""
    _ordered(row._tr.get_or_add_trPr(), "w:tblHeader")


def forbid_row_split(row) -> None:
    _ordered(row._tr.get_or_add_trPr(), "w:cantSplit")


def set_min_row_height(row, height: int) -> None:
    """행 최소 높이. atLeast라 내용이 많으면 알아서 더 늘어난다."""
    element = _ordered(row._tr.get_or_add_trPr(), "w:trHeight")
    element.set(qn("w:hRule"), "atLeast")
    element.set(qn("w:val"), str(emu_to_dxa(height)))


# ── 구역(페이지 설정) ───────────────────────────────────────────────────


def apply_page_setup(section, page) -> None:
    from docx.enum.section import WD_ORIENT

    landscape = page.width > page.height
    section.orientation = WD_ORIENT.LANDSCAPE if landscape else WD_ORIENT.PORTRAIT
    section.page_width = Emu(page.width)
    section.page_height = Emu(page.height)
    section.top_margin = Emu(page.margin.top)
    section.bottom_margin = Emu(page.margin.bottom)
    section.left_margin = Emu(page.margin.left)
    section.right_margin = Emu(page.margin.right)
    if page.margin.header is not None:
        section.header_distance = Emu(page.margin.header)
    if page.margin.footer is not None:
        section.footer_distance = Emu(page.margin.footer)
