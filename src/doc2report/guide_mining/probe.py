"""정식보고서 .docx에서 '실제로 보이는 서식'과 형식 요소를 그대로 기록한다.

`parsers/docx_reader.py`는 변환용 입력 파서라 빈 문단·서식 값·머리말/꼬리말·텍스트 상자를
버린다(IR 계약). 문서의 **특징을 파악**하려면 그것들이 바로 재료라서, 분석용으로 따로 읽는다.
변환 코드는 건드리지 않는다.

- 값은 판단 없이 '실효값'으로 푼다: 직접 서식 > 번호 수준 > 스타일 체인 > docDefaults.
- OOXML을 아는 코드라 설계 원칙 3에 따라 이 모듈에 가둔다 (분석 쪽 stats.py는 XML을 모른다).
- 여기서 나온 값은 코드에 굳히지 않는다 — 분포로 요약해 `profiles/*.yaml` **후보**로만 낸다.
- 원문 글자는 메모리에만 두고 `to_dict()`는 기본으로 뺀다(기밀 문서가 리포트로 새지 않게).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from docx import Document as open_docx
from docx.oxml.ns import qn

from ..ir import invisible_codes, is_blank
from ..units import EMU_PER_MM, PAGE_SIZES, parse_length

_TWIP_PER_MM = 1440 / 25.4
_PUA = re.compile("[\ue000-\uf8ff]")
# 글쓴이가 문자로 쳐 둔 말머리. 기호는 붙여 써도("ㆍ입사예정") 말머리지만, 글자로도 흔한 것
# (ㅇ - * 번호 가나다)은 뒤에 공백·탭이 있을 때만 말머리로 본다("-5%p", "1.5배", "ㅇㅇ팀" 제외).
_TYPED_MARKER = re.compile(
    r"^(?P<lead>[ \u3000\t]*)"
    r"(?:(?P<sym>[□■○●◦▪▫◆◇▶▷▲△※•‧·ㆍ\u119e➢➤►✓]|\([0-9]{1,2}\)|\([가-힣a-zA-Z]\)|[①-⑳❶-❿⓵-⓾])"
    r"|(?P<wordy>ㅇ|[-–—*]|[0-9]{1,2}[.)]|[가-힣a-zA-Z][.)]|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ][.)]?))"
    r"(?P<sep>[ \t\u3000]?)"
)
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"


# ── 결과 자료형 ─────────────────────────────────────────────────────────


@dataclass
class Fmt:
    """글자 서식(문단 대표값). None = 어디에도 안 적힘(= Word 기본)."""
    east_asia: str | None = None
    ascii: str | None = None
    size_pt: float | None = None
    bold: bool | None = None
    italic: bool | None = None
    char_scale_pct: int | None = None


@dataclass
class ParaProbe:
    where: str                       # body | table | header | footer | textbox
    style: str | None
    text: str
    text_len: int
    blank: bool
    invisible_codes: list[str]
    align: str | None
    left_mm: float
    first_line_mm: float             # 음수 = 내어쓰기
    space_before_pt: float
    space_after_pt: float
    line_rule: str                   # auto | exact | atLeast
    line_value: float                # auto면 배수, 아니면 pt
    fmt: Fmt
    heading_level: int | None
    marker_kind: str | None          # typed | auto | None
    marker: str | None               # typed면 글쓴이가 친 말머리, auto면 번호 정의 원문(lvlText)
    marker_sep: str | None           # tab | space | none (typed 말머리 뒤)
    marker_level: int | None         # auto면 ilvl
    leading_spaces: int              # 들여쓰기를 공백으로 친 개수
    pua_bullet: bool                 # Symbol/Wingdings 글머리(문자로는 못 읽음)
    has_object: bool                 # 그림·도형·텍스트 상자가 붙은 문단(글이 없어도 '빈 줄'이 아니다)
    page_break_before: bool
    has_page_break: bool
    text_runs: int


@dataclass
class PageProbe:
    width_mm: float
    height_mm: float
    top_mm: float
    bottom_mm: float
    left_mm: float
    right_mm: float
    header_mm: float
    footer_mm: float
    orientation: str
    paper: str | None
    title_page: bool                 # 첫 쪽 머리말·꼬리말이 다름


@dataclass
class HeaderFooterProbe:
    kind: str                        # header | footer
    section: int
    text_len: int
    text: str
    has_page_field: bool
    align: str | None
    linked: bool


@dataclass
class TableProbe:
    rows: int
    cols: int
    col_widths_mm: list[float]
    jc: str | None
    header_rows: int
    header_fill: str | None
    merged_cells: int
    cell_margin_mm: dict[str, float]
    nested: bool


@dataclass
class DocProbe:
    doc_id: str
    name: str
    sections: list[PageProbe] = field(default_factory=list)
    paragraphs: list[ParaProbe] = field(default_factory=list)
    tables: list[TableProbe] = field(default_factory=list)
    headers_footers: list[HeaderFooterProbe] = field(default_factory=list)
    textbox_count: int = 0
    toc: bool = False
    page_breaks: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self, *, keep_text: bool = False, keep_name: bool = False) -> dict:
        data = asdict(self)
        if not keep_name:
            data["name"] = ""
        if not keep_text:
            for para in data["paragraphs"]:
                para["text"] = ""
            for hf in data["headers_footers"]:
                hf["text"] = ""
        return data


# ── 진입점 ──────────────────────────────────────────────────────────────


def probe_docx(path: str | Path, *, doc_id: str | None = None) -> DocProbe:
    path = Path(path)
    docx = open_docx(str(path))
    probe = DocProbe(doc_id=doc_id or path.stem, name=path.name)
    _Prober(docx, probe).run()
    return probe


class _Prober:
    def __init__(self, docx, probe: DocProbe):
        self.docx = docx
        self.probe = probe
        self.styles = {
            s.get(qn("w:styleId")): s
            for s in docx.styles.element.findall(qn("w:style"))
        }
        self.defaults = docx.styles.element.find(qn("w:docDefaults"))
        self.default_para_style = next(
            (s for s in self.styles.values()
             if s.get(qn("w:type")) == "paragraph" and s.get(qn("w:default")) in ("1", "true")),
            None,
        )
        try:
            self.numbering = docx.part.numbering_part.element
        except (KeyError, NotImplementedError, AttributeError):
            self.numbering = None

    # ── 전체 ────────────────────────────────────────────────────────────

    def run(self) -> None:
        body = self.docx.element.body
        self._body(body, where="body", nested=False)
        self._sections()
        self._textboxes(body)
        self.probe.toc = self._has_toc(body)

    def _body(self, container, *, where: str, nested: bool) -> None:
        for child in container.iterchildren():
            if child.tag == qn("w:p"):
                self._paragraph(child, where)
            elif child.tag == qn("w:tbl"):
                self._table(child, nested=nested)
            elif child.tag == qn("w:sdt"):
                content = child.find(qn("w:sdtContent"))
                if content is not None:
                    self._body(content, where=where, nested=nested)

    # ── 문단 ────────────────────────────────────────────────────────────

    def _paragraph(self, p, where: str) -> ParaProbe:
        text = _text(p)
        style = self._para_style(p)
        ppr = self._effective_ppr(p, style)
        numbering = self._numbering_of(p, style)
        marker_kind = marker = sep = None
        level = None
        pua = False
        leading = 0
        if numbering is not None:
            level, marker, pua = numbering
            marker_kind = "auto"
        else:
            found = _typed_marker(text)
            if found is not None:
                marker_kind = "typed"
                marker, sep = found
                leading = len(text) - len(text.lstrip(" \u3000"))
        spacing = ppr.get("spacing", {})
        line_rule = spacing.get("lineRule", "auto")
        line = _num(spacing.get("line"), 240.0)
        line_value = line / 240 if line_rule == "auto" else line / 20
        ind = ppr.get("ind", {})
        left = _num(ind.get("left", ind.get("start")), 0.0)
        first = _num(ind.get("firstLine"), 0.0) - _num(ind.get("hanging"), 0.0)
        heading = self._heading_level(p, style)
        has_object = any(True for _ in p.iter(qn("w:drawing"), qn("w:pict"), qn("w:object")))
        para = ParaProbe(
            where=where,
            style=_style_name(style),
            text=text,
            text_len=len(text),
            blank=is_blank(text) and not has_object,
            invisible_codes=invisible_codes(text),
            align=ppr.get("jc_value"),
            left_mm=round(left / _TWIP_PER_MM, 2),
            first_line_mm=round(first / _TWIP_PER_MM, 2),
            space_before_pt=round(_num(spacing.get("before"), 0.0) / 20, 2),
            space_after_pt=round(_num(spacing.get("after"), 0.0) / 20, 2),
            line_rule=line_rule,
            line_value=round(line_value, 3),
            fmt=self._dominant_fmt(p, style),
            heading_level=heading,
            marker_kind=marker_kind,
            marker=marker,
            marker_sep=sep,
            marker_level=level,
            leading_spaces=leading,
            pua_bullet=pua,
            has_object=has_object,
            page_break_before="pageBreakBefore" in ppr,
            has_page_break=_has_page_break(p),
            text_runs=len(p.findall(qn("w:r"))),
        )
        if para.page_break_before or para.has_page_break:
            self.probe.page_breaks += 1
        self.probe.paragraphs.append(para)
        return para

    # ── 서식 풀기 ───────────────────────────────────────────────────────

    def _para_style(self, p):
        ppr = p.find(qn("w:pPr"))
        pstyle = ppr.find(qn("w:pStyle")) if ppr is not None else None
        if pstyle is not None and pstyle.get(qn("w:val")) in self.styles:
            return self.styles[pstyle.get(qn("w:val"))]
        return self.default_para_style

    def _chain(self, style):
        """기본 스타일 → … → 자기 순서(뒤로 갈수록 우선)."""
        out, seen = [], set()
        while style is not None and id(style) not in seen and len(out) < 12:
            seen.add(id(style))
            out.append(style)
            based = style.find(qn("w:basedOn"))
            style = self.styles.get(based.get(qn("w:val"))) if based is not None else None
        return list(reversed(out))

    def _effective_ppr(self, p, style) -> dict:
        """문단 속성의 실효값: docDefaults < 스타일 체인 < 번호 수준 < 직접 서식."""
        merged: dict = {}
        sources = []
        if self.defaults is not None:
            sources.append(self.defaults.find(f"{qn('w:pPrDefault')}/{qn('w:pPr')}"))
        sources += [s.find(qn("w:pPr")) for s in self._chain(style)]
        direct = p.find(qn("w:pPr"))
        lvl = self._level_def(*self._num_ref(p, style)) if self._num_ref(p, style) else None
        sources.append(lvl.find(qn("w:pPr")) if lvl is not None else None)
        sources.append(direct)
        for ppr in sources:
            if ppr is None:
                continue
            for tag in ("spacing", "ind"):
                el = ppr.find(qn(f"w:{tag}"))
                if el is not None:
                    merged.setdefault(tag, {}).update(_attrs(el))
            jc = ppr.find(qn("w:jc"))
            if jc is not None:
                merged["jc_value"] = jc.get(qn("w:val"))
            if ppr.find(qn("w:pageBreakBefore")) is not None:
                merged["pageBreakBefore"] = True
        # 들여쓰기에 hanging과 firstLine이 함께 오면 나중 것이 이긴다(스키마상 배타)
        ind = merged.get("ind", {})
        if "hanging" in ind and "firstLine" in ind and direct is not None:
            d_ind = direct.find(qn("w:ind"))
            if d_ind is not None:
                if d_ind.get(qn("w:hanging")) is not None:
                    ind.pop("firstLine", None)
                elif d_ind.get(qn("w:firstLine")) is not None:
                    ind.pop("hanging", None)
        return merged

    def _dominant_fmt(self, p, style) -> Fmt:
        """글자 수가 가장 많은 run의 실효 서식(제목 줄의 굵은 말머리 한 글자에 흔들리지 않게)."""
        best, best_len = None, -1
        for run in p.findall(qn("w:r")):
            length = len("".join(t.text or "" for t in run.findall(qn("w:t"))).strip())
            if length > best_len:
                best, best_len = run, length
        return self._run_fmt(best, style)

    def _run_fmt(self, run, pstyle) -> Fmt:
        rprs = []
        if self.defaults is not None:
            rprs.append(self.defaults.find(f"{qn('w:rPrDefault')}/{qn('w:rPr')}"))
        rprs += [s.find(qn("w:rPr")) for s in self._chain(pstyle)]
        if run is not None:
            direct = run.find(qn("w:rPr"))
            rstyle = direct.find(qn("w:rStyle")) if direct is not None else None
            if rstyle is not None and rstyle.get(qn("w:val")) in self.styles:
                rprs += [s.find(qn("w:rPr")) for s in self._chain(self.styles[rstyle.get(qn("w:val"))])]
            rprs.append(direct)
        fmt = Fmt()
        for rpr in rprs:
            if rpr is None:
                continue
            fonts = rpr.find(qn("w:rFonts"))
            if fonts is not None:
                fmt.east_asia = fonts.get(qn("w:eastAsia")) or fmt.east_asia
                fmt.ascii = fonts.get(qn("w:ascii")) or fmt.ascii
            sz = rpr.find(qn("w:sz"))
            if sz is not None and sz.get(qn("w:val")):
                fmt.size_pt = int(sz.get(qn("w:val"))) / 2
            for tag, attr in (("b", "bold"), ("i", "italic")):
                el = rpr.find(qn(f"w:{tag}"))
                if el is not None:
                    setattr(fmt, attr, el.get(qn("w:val")) not in ("0", "false", "off"))
            scale = rpr.find(qn("w:w"))
            if scale is not None and scale.get(qn("w:val")):
                fmt.char_scale_pct = int(scale.get(qn("w:val")))
        return fmt

    def _heading_level(self, p, style) -> int | None:
        for s in reversed(self._chain(style)):
            ppr = s.find(qn("w:pPr"))
            outline = ppr.find(qn("w:outlineLvl")) if ppr is not None else None
            if outline is not None:
                value = int(outline.get(qn("w:val"), "9"))
                return value + 1 if value < 9 else None
        return None

    # ── 자동 번호 ───────────────────────────────────────────────────────

    def _num_ref(self, p, style) -> tuple[str, int] | None:
        ppr_list = [p.find(qn("w:pPr"))] + [s.find(qn("w:pPr")) for s in reversed(self._chain(style))]
        for ppr in ppr_list:
            numpr = ppr.find(qn("w:numPr")) if ppr is not None else None
            if numpr is None:
                continue
            num_id = numpr.find(qn("w:numId"))
            ilvl = numpr.find(qn("w:ilvl"))
            value = num_id.get(qn("w:val")) if num_id is not None else "0"
            if value == "0":
                return None
            return value, int(ilvl.get(qn("w:val"))) if ilvl is not None else 0
        return None

    def _numbering_of(self, p, style) -> tuple[int, str | None, bool] | None:
        ref = self._num_ref(p, style)
        if ref is None:
            return None
        lvl = self._level_def(*ref)
        text = None
        pua = False
        if lvl is not None:
            el = lvl.find(qn("w:lvlText"))
            text = el.get(qn("w:val")) if el is not None else None
            pua = bool(text and _PUA.search(text))
        return ref[1], text, pua

    def _level_def(self, num_id: str, ilvl: int):
        if self.numbering is None:
            return None
        num = next((n for n in self.numbering.findall(qn("w:num"))
                    if n.get(qn("w:numId")) == num_id), None)
        if num is None:
            return None
        for override in num.findall(qn("w:lvlOverride")):
            if override.get(qn("w:ilvl")) == str(ilvl) and override.find(qn("w:lvl")) is not None:
                return override.find(qn("w:lvl"))
        abstract_id = num.find(qn("w:abstractNumId"))
        abstract = next(
            (a for a in self.numbering.findall(qn("w:abstractNum"))
             if abstract_id is not None and a.get(qn("w:abstractNumId")) == abstract_id.get(qn("w:val"))),
            None,
        )
        if abstract is None:
            return None
        return next((lvl for lvl in abstract.findall(qn("w:lvl"))
                     if lvl.get(qn("w:ilvl")) == str(ilvl)), None)

    # ── 표 ──────────────────────────────────────────────────────────────

    def _table(self, tbl, *, nested: bool) -> None:
        tblpr = tbl.find(qn("w:tblPr"))
        grid = tbl.find(qn("w:tblGrid"))
        widths = [
            round(_num(c.get(qn("w:w")), 0.0) / _TWIP_PER_MM, 1)
            for c in (grid.findall(qn("w:gridCol")) if grid is not None else [])
        ]
        rows = tbl.findall(qn("w:tr"))
        header_rows = 0
        for tr in rows:
            trpr = tr.find(qn("w:trPr"))
            if trpr is not None and trpr.find(qn("w:tblHeader")) is not None:
                header_rows += 1
            else:
                break
        merged = sum(
            1 for tc in tbl.iter(qn("w:tc"))
            if tc.find(f"{qn('w:tcPr')}/{qn('w:gridSpan')}") is not None
            or tc.find(f"{qn('w:tcPr')}/{qn('w:vMerge')}") is not None
        )
        fill = None
        if rows:
            first_tc = rows[0].find(qn("w:tc"))
            shd = first_tc.find(f"{qn('w:tcPr')}/{qn('w:shd')}") if first_tc is not None else None
            fill = shd.get(qn("w:fill")) if shd is not None else None
        jc = tblpr.find(qn("w:jc")) if tblpr is not None else None
        margins: dict[str, float] = {}
        mar = tblpr.find(qn("w:tblCellMar")) if tblpr is not None else None
        if mar is not None:
            for side in ("top", "left", "bottom", "right"):
                el = mar.find(qn(f"w:{side}"))
                if el is None:
                    el = mar.find(qn("w:start" if side == "left" else "w:end"))
                if el is not None and el.get(qn("w:w")):
                    margins[side] = round(_num(el.get(qn("w:w")), 0.0) / _TWIP_PER_MM, 2)
        self.probe.tables.append(TableProbe(
            rows=len(rows), cols=len(widths), col_widths_mm=widths,
            jc=jc.get(qn("w:val")) if jc is not None else None,
            header_rows=header_rows, header_fill=fill, merged_cells=merged,
            cell_margin_mm=margins, nested=nested,
        ))
        for tr in rows:
            for tc in tr.findall(qn("w:tc")):
                self._body(tc, where="table", nested=True)

    # ── 쪽·머리말·텍스트 상자 ───────────────────────────────────────────

    def _sections(self) -> None:
        for index, section in enumerate(self.docx.sections):
            width, height = section.page_width, section.page_height
            self.probe.sections.append(PageProbe(
                width_mm=_mm(width), height_mm=_mm(height),
                top_mm=_mm(section.top_margin), bottom_mm=_mm(section.bottom_margin),
                left_mm=_mm(section.left_margin), right_mm=_mm(section.right_margin),
                header_mm=_mm(section.header_distance), footer_mm=_mm(section.footer_distance),
                orientation="landscape" if (width or 0) > (height or 0) else "portrait",
                paper=_paper_name(width, height),
                title_page=bool(section.different_first_page_header_footer),
            ))
            for kind, part in (("header", section.header), ("footer", section.footer)):
                element = part._element  # noqa: SLF001 — 머리말 XML을 직접 본다
                text = "\n".join(_text(p) for p in element.iter(qn("w:p")) if _text(p).strip())
                first = next(element.iter(qn("w:p")), None)
                jc = first.find(f"{qn('w:pPr')}/{qn('w:jc')}") if first is not None else None
                self.probe.headers_footers.append(HeaderFooterProbe(
                    kind=kind, section=index, text_len=len(text.strip()), text=text,
                    has_page_field=_has_page_field(element),
                    align=jc.get(qn("w:val")) if jc is not None else None,
                    linked=bool(part.is_linked_to_previous),
                ))

    def _textboxes(self, body) -> None:
        for box in body.iter(qn("w:txbxContent")):
            if _inside_fallback(box):
                continue  # mc:AlternateContent의 Fallback은 같은 상자의 사본
            self.probe.textbox_count += 1
            for p in box.findall(qn("w:p")):
                self._paragraph(p, "textbox")

    def _has_toc(self, body) -> bool:
        for sdt in body.iter(qn("w:sdt")):
            gallery = sdt.find(f"{qn('w:sdtPr')}/{qn('w:docPartObj')}/{qn('w:docPartGallery')}")
            if gallery is not None and "table of contents" in (gallery.get(qn("w:val")) or "").lower():
                return True
        return any("TOC" in (t.text or "").split()[:1] or (t.text or "").strip().startswith("TOC")
                   for t in body.iter(qn("w:instrText")))


# ── 도우미 ──────────────────────────────────────────────────────────────


def _text(el) -> str:
    """문단의 보이는 글자. 지워진 변경 내용·필드 코드·텍스트 상자 속 글자는 뺀다."""
    out: list[str] = []

    def walk(node) -> None:
        for child in node:
            tag = child.tag
            if tag in (qn("w:del"), qn("w:instrText"), qn("w:txbxContent"), _MC_FALLBACK):
                continue
            if tag == qn("w:t"):
                out.append(child.text or "")
            elif tag == qn("w:tab"):
                out.append("\t")
            elif tag in (qn("w:br"), qn("w:cr")) and child.get(qn("w:type")) != "page":
                out.append("\n")
            else:
                walk(child)

    walk(el)
    return "".join(out)


def _typed_marker(text: str) -> tuple[str, str] | None:
    """(말머리, 뒤 구분: tab|space|none). 말머리가 아니면 None."""
    match = _TYPED_MARKER.match(text)
    if match is None or is_blank(text):
        return None
    mark = match.group("sym") or match.group("wordy")
    raw = match.group("sep")
    sep = "tab" if raw == "\t" else "space" if raw else "none"
    if match.group("wordy") and sep == "none":
        return None
    rest = text[match.end("sym") if match.group("sym") else match.end("wordy"):]
    if rest[:1] == mark[-1:]:
        return None  # "○○팀"처럼 같은 기호가 연달아 오면 자리표시자
    return mark, sep


def _has_page_break(p) -> bool:
    return any(br.get(qn("w:type")) == "page" for br in p.iter(qn("w:br")))


def _has_page_field(element) -> bool:
    for instr in element.iter(qn("w:instrText")):
        if (instr.text or "").strip().upper().startswith(("PAGE", "NUMPAGES")):
            return True
    return any((f.get(qn("w:instr")) or "").strip().upper().startswith(("PAGE", "NUMPAGES"))
               for f in element.iter(qn("w:fldSimple")))


def _inside_fallback(el) -> bool:
    parent = el.getparent()
    while parent is not None:
        if parent.tag == _MC_FALLBACK:
            return True
        parent = parent.getparent()
    return False


def _attrs(el) -> dict[str, str]:
    return {k.replace(_W, ""): v for k, v in el.attrib.items()}


def _num(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _mm(length) -> float:
    return round((length or 0) / EMU_PER_MM, 1)


def _paper_name(width, height) -> str | None:
    for name, (w, h) in PAGE_SIZES.items():
        for a, b in ((w, h), (h, w)):
            if abs((width or 0) - parse_length(a)) < 1.5 * EMU_PER_MM and \
                    abs((height or 0) - parse_length(b)) < 1.5 * EMU_PER_MM:
                return name
    return None


def _style_name(style) -> str | None:
    if style is None:
        return None
    name = style.find(qn("w:name"))
    return name.get(qn("w:val")) if name is not None else style.get(qn("w:styleId"))
