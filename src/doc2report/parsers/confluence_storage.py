"""Confluence storage format(XHTML) → IR.

Markdown 경유(마크다운 내보내기 → 마크다운 파서)와 달리 Confluence REST API가 주는
`body.storage`를 곧장 읽는다. 가장 큰 차이는 표다 — GFM 마크다운 표에는 병합 셀
(colspan/rowspan) 문법이 없어 마크다운을 거치면 정보가 사라지지만, storage format은
HTML 표 그대로라 병합 정보를 IR의 Cell.colspan/rowspan에 그대로 옮길 수 있다.
Confluence는 표 폭에 제약이 없어(자유롭게 열을 늘리고 줄을 병합) 이 경로가 특히 중요하다.

매크로(`ac:structured-macro`)는 이름으로 분기한다: info/note/warning류는 Callout,
code는 CodeBlock, 나머지는 알려진 하위 구조(rich-text-body)가 있으면 그 안만 펼치고
없으면 건너뛴다 (노트에 남긴다).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lxml import etree

from ..ir import (
    Block,
    Callout,
    Cell,
    CodeBlock,
    Document,
    Heading,
    HorizontalRule,
    Image,
    ListItem,
    Paragraph,
    Row,
    Run,
    Table,
)

AC_NS = "http://www.atlassian.com/schema/confluence/4/ac/"
RI_NS = "http://www.atlassian.com/schema/confluence/4/ri/"

_KIND_BY_MACRO = {
    "info": "info", "tip": "info", "note": "note",
    "warning": "warning", "caution": "warning", "important": "note",
}

_INLINE_TAGS = {"strong", "b", "em", "i", "u", "code", "a", "span", "br", "sup", "sub"}


@dataclass
class ParsedConfluence:
    document: Document
    notes: list[str] = field(default_factory=list)  # 건너뛴 매크로·요소 (--report에 남긴다)


def parse_confluence_storage(
    xhtml: str, *, source: str | None = None, title: str | None = None
) -> ParsedConfluence:
    """title을 주면 그대로 문서 제목으로 쓴다 (Confluence 페이지 제목은 본문과 별도
    메타데이터라 storage XHTML 안에 없는 게 보통이다). 안 주면 본문 첫 H1을 제목으로
    승격한다 — Markdown 문서와 동일한 규칙."""
    root = _fragment_root(xhtml)
    blocks, notes = _children_blocks(root)
    if title is None and blocks and isinstance(blocks[0], Heading) and blocks[0].level == 1:
        from ..ir import plain

        title = plain(blocks[0].runs)
        blocks = blocks[1:]
    doc = Document(blocks=blocks, title=title, source=source)
    return ParsedConfluence(document=doc, notes=notes)


def _fragment_root(xhtml: str):
    wrapped = (
        f'<root xmlns:ac="{AC_NS}" xmlns:ri="{RI_NS}">{xhtml}</root>'
    )
    parser = etree.XMLParser(recover=True, resolve_entities=False)
    root = etree.fromstring(wrapped.encode("utf-8"), parser=parser)
    if root is None:
        raise ValueError("Confluence storage XHTML을 해석하지 못했습니다.")
    return root


def _local(el) -> str:
    return etree.QName(el).localname


def _is_ac(el, name: str) -> bool:
    return el.tag == f"{{{AC_NS}}}{name}"


# ── 블록 ────────────────────────────────────────────────────────────────


def _children_blocks(el) -> tuple[list[Block], list[str]]:
    blocks: list[Block] = []
    notes: list[str] = []
    for child in el:
        sub, sub_notes = _block(child)
        blocks.extend(sub)
        notes.extend(sub_notes)
    return blocks, notes


def _block(el) -> tuple[list[Block], list[str]]:
    if _is_ac(el, "structured-macro"):
        return _macro(el)

    tag = _local(el)

    if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        runs, images = _inline(el)
        return [Heading(level=int(tag[1]), runs=runs), *images], []

    if tag == "p":
        lines, images = _inline_lines(el)
        return _paragraphs_from_lines(lines, images, align=_align_of(el)), []

    if tag in {"ul", "ol"}:
        return _list(el, depth=0, ordered=(tag == "ol")), []

    if tag == "table":
        return [_table(el)], []

    if tag == "blockquote":
        inner, notes = _children_blocks(el)
        return [Callout(kind="quote", blocks=inner)], notes

    if tag == "hr":
        return [HorizontalRule()], []

    if _is_ac(el, "image"):
        image = _image(el)
        return ([image] if image else []), []

    if tag in ("div", "root", "layout", "layout-section", "layout-cell"):
        return _children_blocks(el)

    # 알 수 없는 블록 요소는 건너뛰되, 무엇을 놓쳤는지는 남긴다.
    if el.text and el.text.strip():
        return [Paragraph(runs=[Run(el.text.strip())])], []
    return [], [f"알 수 없는 요소를 건너뜀: <{tag}>"]


def _macro(el) -> tuple[list[Block], list[str]]:
    name = el.get("ac:name") or el.get("{%s}name" % AC_NS) or ""
    body = _macro_child(el, "rich-text-body")

    if name in _KIND_BY_MACRO:
        inner, notes = _children_blocks(body) if body is not None else ([], [])
        return [Callout(kind=_KIND_BY_MACRO[name], blocks=inner)], notes

    if name == "code":
        text_body = _macro_child(el, "plain-text-body")
        text = (text_body.text or "") if text_body is not None else ""
        lang = None
        for param in el.findall(f"{{{AC_NS}}}parameter"):
            if param.get("ac:name") == "language" or param.get("{%s}name" % AC_NS) == "language":
                lang = (param.text or "").strip() or None
        return [CodeBlock(text=text.rstrip("\n"), lang=lang)], []

    if body is not None:
        # panel, expand 등 아직 모르는 매크로라도 본문(rich-text-body)이 있으면 펼친다.
        inner, notes = _children_blocks(body)
        return inner, notes + [f"매크로 '{name}'을(를) 본문만 펼쳐서 처리함"]

    return [], [f"지원하지 않는 매크로를 건너뜀: {name or '(이름 없음)'}"]


def _macro_child(el, local_name: str):
    return el.find(f"{{{AC_NS}}}{local_name}")


def _list(el, depth: int, ordered: bool) -> list[Block]:
    """<li>는 <p>로 감싼 항목과, 인라인 서식이 직접 들어간 항목이 둘 다 흔하다
    (<li>텍스트</li> vs <li><p>텍스트</p></li>). 후자도 굵게·링크 등을 살리려면
    <li> 자체를 인라인으로 훑어야 한다 — 텍스트만 뽑으면 서식이 사라진다.
    """
    out: list[Block] = []
    number = 1
    for li in el:
        if _local(li) != "li":
            continue
        block_children = [c for c in li if _local(c) in ("p", "ul", "ol", "table")]
        para = next((c for c in block_children if _local(c) == "p"), None)
        if para is not None:
            runs, images = _inline(para)
        else:
            # walk()가 ul/ol/table 자식은 건너뛰므로, 뒤이은 중첩 목록과 안 섞인다.
            runs, images = _inline(li)
        out.append(ListItem(depth=depth, runs=runs, ordered=ordered,
                            number=number if ordered else None))
        out.extend(images)
        for child in block_children:
            tag = _local(child)
            if tag in ("ul", "ol"):
                out.extend(_list(child, depth + 1, ordered=(tag == "ol")))
            elif tag == "table":
                out.append(_table(child))
        number += 1
    return out


def _table(el) -> Table:
    rows: list[Row] = []
    header_rows = 0
    trs: list = []
    for section in el:
        if _local(section) in ("thead", "tbody", "tfoot"):
            for tr in section:
                if _local(tr) == "tr":
                    trs.append((tr, _local(section) == "thead"))
        elif _local(section) == "tr":
            trs.append((section, False))

    counted_header = True
    for tr, in_thead in trs:
        cells: list[Cell] = []
        all_th = True
        for cell_el in tr:
            tag = _local(cell_el)
            if tag not in ("td", "th"):
                continue
            all_th = all_th and tag == "th"
            blocks = _cell_blocks(cell_el)
            if not blocks:
                blocks = [Paragraph(runs=[])]
            cells.append(Cell(
                blocks=blocks,
                colspan=_int_attr(cell_el, "colspan", 1),
                rowspan=_int_attr(cell_el, "rowspan", 1),
                is_header=in_thead or tag == "th",
            ))
        rows.append(Row(cells=cells))
        if counted_header and (in_thead or (cells and all_th)):
            header_rows += 1
        else:
            counted_header = False

    return Table(rows=rows, header_rows=header_rows)


_BLOCK_TAGS = {"p", "ul", "ol", "table", "blockquote", "hr", "h1", "h2", "h3", "h4", "h5", "h6"}


def _cell_blocks(el) -> list[Block]:
    """표 셀은 <td><p>구분</p></td>처럼 <p>로 감싸기도 하고, <td>구분</td>처럼 바로
    텍스트를 넣기도 한다. 후자를 _children_blocks에 그대로 넘기면 자식 요소가 없어
    아무것도 못 건지고 빈 문단이 된다 — 리스트 항목과 같은 문제라 같은 방식으로 푼다."""
    has_block = any(
        _local(c) in _BLOCK_TAGS or _is_ac(c, "structured-macro") or _is_ac(c, "image")
        for c in el
    )
    if has_block:
        blocks, _ = _children_blocks(el)
        return blocks
    lines, images = _inline_lines(el)
    return _paragraphs_from_lines(lines, images)


def _paragraphs_from_lines(lines: list[list[Run]], images: list[Image],
                           align: str | None = None) -> list[Block]:
    blocks: list[Block] = [Paragraph(runs=line, align=align)
                           for line in lines if any(r.text.strip() for r in line)]
    blocks.extend(images)
    return blocks


_ALIGN_RE = re.compile(r"text-align\s*:\s*(left|center|right)", re.I)


def _align_of(el) -> str | None:
    """Confluence 편집기의 정렬 버튼이 넣는 style="text-align: ..."(또는 옛
    align="..." 속성)을 읽는다 — 이게 있으면 표 제목으로 옮겨도 원래 정렬을
    유지할 수 있다(2026-09-29 사용자 요청)."""
    style = el.get("style")
    if style:
        m = _ALIGN_RE.search(style)
        if m:
            return m.group(1).lower()
    align = el.get("align")
    if align and align.lower() in ("left", "center", "right"):
        return align.lower()
    return None


def _int_attr(el, name: str, default: int) -> int:
    value = el.get(name)
    try:
        return int(value) if value else default
    except ValueError:
        return default


def _image(el) -> Image | None:
    attachment = el.find(f"{{{RI_NS}}}attachment")
    if attachment is not None:
        filename = attachment.get(f"{{{RI_NS}}}filename") or attachment.get("ri:filename")
        if filename:
            width = el.get(f"{{{AC_NS}}}width") or el.get("ac:width")
            return Image(src=filename, width_px=int(width) if width and width.isdigit() else None)
    url = el.find(f"{{{RI_NS}}}url")
    if url is not None:
        href = url.get(f"{{{RI_NS}}}value") or url.get("ri:value")
        if href:
            return Image(src=href)
    return None


# ── 인라인 ──────────────────────────────────────────────────────────────


def _inline(el) -> tuple[list[Run], list[Image]]:
    """storage XHTML은 흔히 태그 사이에 줄바꿈·들여쓰기가 그대로 남아 있다
    (source-view로 편집했거나 Confluence가 그대로 보존한 경우). HTML의
    white-space:normal 규칙대로 연속 공백을 하나로 접고 블록 앞뒤는 잘라 낸다 —
    안 그러면 "복합 인덱스 3건 추가\\n      " 처럼 원본 들여쓰기가 문서에 새어 나온다.
    """
    runs: list[Run] = []
    images: list[Image] = []

    def walk(node, bold: bool, italic: bool, code: bool, href: str | None) -> None:
        if node.text:
            runs.append(Run(_ws(node.text), bold=bold, italic=italic, code=code, href=href))
        for child in node:
            if _is_ac(child, "image"):
                image = _image(child)
                if image:
                    images.append(image)
                if child.tail:
                    runs.append(Run(_ws(child.tail), bold=bold, italic=italic, code=code, href=href))
                continue

            tag = _local(child)
            if tag == "br":
                runs.append(Run(" ", bold=bold, italic=italic, code=code, href=href))
                if child.tail:
                    runs.append(Run(_ws(child.tail), bold=bold, italic=italic, code=code, href=href))
                continue

            child_bold = bold or tag in ("strong", "b")
            child_italic = italic or tag in ("em", "i")
            child_code = code or tag == "code"
            child_href = href
            if tag == "a":
                child_href = child.get("href") or href

            if tag in _INLINE_TAGS or tag not in ("ul", "ol", "table", "p", "blockquote"):
                walk(child, child_bold, child_italic, child_code, child_href)
            if child.tail:
                runs.append(Run(_ws(child.tail), bold=bold, italic=italic, code=code, href=href))

    walk(el, False, False, False, None)
    return _trim(_merge_runs(runs)), images


def _inline_lines(el) -> tuple[list[list[Run]], list[Image]]:
    """_inline()과 같지만 <br>를 (공백이 아니라) 줄 경계로 취급한다.

    표 셀은 <p> 없이 텍스트 사이사이에 <br>만 넣어 여러 줄을 표현하는 경우가
    흔한데, 이를 _inline()으로 읽으면 <br>가 공백 하나로 접혀 여러 줄이 한
    문장으로 뭉개진다(실제로 겪음: "ㅇㅇㅇ<br>ㅁㅁㅁ<br>ㄷㄷㄷ" → 한 줄).
    <p> 블록 하나에서 이 함수가 돌려주는 줄마다 별도 Paragraph를 만들면
    셀 안에 여러 문단이 되어 원래 줄 구분이 살아난다."""
    lines: list[list[Run]] = [[]]
    images: list[Image] = []

    def walk(node, bold: bool, italic: bool, code: bool, href: str | None) -> None:
        if node.text:
            lines[-1].append(Run(_ws(node.text), bold=bold, italic=italic, code=code, href=href))
        for child in node:
            if _is_ac(child, "image"):
                image = _image(child)
                if image:
                    images.append(image)
                if child.tail:
                    lines[-1].append(Run(_ws(child.tail), bold=bold, italic=italic, code=code, href=href))
                continue

            tag = _local(child)
            if tag == "br":
                lines.append([])
                if child.tail:
                    lines[-1].append(Run(_ws(child.tail), bold=bold, italic=italic, code=code, href=href))
                continue

            child_bold = bold or tag in ("strong", "b")
            child_italic = italic or tag in ("em", "i")
            child_code = code or tag == "code"
            child_href = href
            if tag == "a":
                child_href = child.get("href") or href

            if tag in _INLINE_TAGS or tag not in ("ul", "ol", "table", "p", "blockquote"):
                walk(child, child_bold, child_italic, child_code, child_href)
            if child.tail:
                lines[-1].append(Run(_ws(child.tail), bold=bold, italic=italic, code=code, href=href))

    walk(el, False, False, False, None)
    return [_trim(_merge_runs(line)) for line in lines], images


def _ws(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _trim(runs: list[Run]) -> list[Run]:
    """블록 맨 앞/뒤의 공백만 잘라 낸다 (중간 공백은 단어 사이 구분이라 그대로 둔다)."""
    if not runs:
        return runs
    runs = list(runs)
    runs[0] = runs[0].copy_with(runs[0].text.lstrip())
    runs[-1] = runs[-1].copy_with(runs[-1].text.rstrip())
    return [r for r in runs if r.text]


def _merge_runs(runs: list[Run]) -> list[Run]:
    out: list[Run] = []
    for r in runs:
        if not r.text:
            continue
        if out and (out[-1].bold, out[-1].italic, out[-1].code, out[-1].href) == (
            r.bold, r.italic, r.code, r.href
        ):
            out[-1] = out[-1].copy_with(out[-1].text + r.text)
        else:
            out.append(r)
    return out
