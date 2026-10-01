"""probe 결과 → 집계 요약. OOXML을 모른다(probe.py가 푼 값만 본다).

요약에는 **집계 수치만** 넣는다: 분포·비율·최빈값. 원문 문장은 넣지 않는다.
예외는 문장 끝 두 글자("합니다"·"함" 같은 종결 형태)뿐이며 어투 분석에 꼭 필요하고 유출 위험이 낮다.
LLM이 필요한 정성 분석(문서 유형·섹션 흐름·어투 요약)은 이 요약을 입력으로 다음 단계에서 붙인다.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from typing import Callable, Iterable

from ..transform.stylize_ko import _SENTENCE_SPLIT
from .probe import DocProbe, ParaProbe

TOP = 8  # 분포마다 보여 줄 최빈값 수

_CLOSERS = " \t\n.!?)]}>」』】〕〉》\"'”’…"
_NOUNISH_ENDS = "음함임됨"
_DATE_FORMS = {
    "YYYY.M.D.": re.compile(r"\b(?:19|20)\d{2}\s*\.\s*\d{1,2}\s*\.\s*\d{1,2}\s*\."),
    "YYYY-MM-DD": re.compile(r"\b(?:19|20)\d{2}-\d{1,2}-\d{1,2}\b"),
    "YY.M.D.": re.compile(r"(?<!\d)\d{2}\s*\.\s*\d{1,2}\s*\.\s*\d{1,2}\s*\.(?!\d)"),
    "YYYY년 M월 D일": re.compile(r"(?:19|20)\d{2}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일"),
    "M/D": re.compile(r"(?<![\d/])\d{1,2}/\d{1,2}(?![\d/])"),
}
_NUMBER_FORMS = {
    "%p": re.compile(r"\d\s*%p"),
    "%": re.compile(r"\d\s*%(?!p)"),
    "억원": re.compile(r"\d\s*억\s*원?"),
    "백만원": re.compile(r"\d\s*백만\s*원"),
    "천단위 콤마": re.compile(r"\d{1,3}(?:,\d{3})+"),
    "▲/△ 증감": re.compile(r"[▲△▼▽]\s*\d"),
}


def summarize(probes: list[DocProbe], *, phrases: bool = True) -> dict:
    return {
        "docs": _docs(probes),
        "page": _page(probes),
        "fonts": _fonts(probes),
        "spacing": _spacing(probes),
        "blank_lines": _blank_lines(probes),
        "markers": _markers(probes),
        "text": _text(probes),
        "notation": _notation(probes),
        "tables": _tables(probes),
        "headers_footers": _headers_footers(probes),
        "structure": _structure(probes),
        "annotations": _annotations(probes),
        "unmarked": _unmarked(probes),
        "skeleton": _skeleton(probes),
        "dates": _dates(probes),
        "table_cells": _table_cells(probes),
        "phrases": _phrases(probes) if phrases else None,
        "charset": _charset(probes),
        "fitting": _fitting(probes),
    }


# ── 항목별 집계 ─────────────────────────────────────────────────────────


def _docs(probes) -> dict:
    return {
        "count": len(probes),
        "notes": [f"{p.doc_id}: {n}" for p in probes for n in p.notes],
        "per_doc": [
            {
                "id": p.doc_id,
                "paragraphs": sum(1 for x in p.paragraphs if x.where == "body"),
                "tables": len(p.tables),
                "sections": len(p.sections),
                "blank_ratio": _ratio(
                    sum(1 for x in _body(p) if x.blank), len(_body(p))),
                "textboxes": len(p.textboxes),
                "body_size_pt": _dominant(p, lambda x: x.fmt.size_pt),
                "body_line": _dominant(p, lambda x: x.line_value),
                "margins_mm": (f"{_r(p.sections[0].top_mm)}/{_r(p.sections[0].bottom_mm)}/"
                               f"{_r(p.sections[0].left_mm)}/{_r(p.sections[0].right_mm)}"
                               if p.sections else None),
            }
            for p in probes
        ],
    }


def _page(probes) -> dict:
    firsts = [p.sections[0] for p in probes if p.sections]
    return {
        "layout": _top(Counter(
            (s.paper or f"{s.width_mm}x{s.height_mm}", s.orientation,
             _r(s.top_mm), _r(s.bottom_mm), _r(s.left_mm), _r(s.right_mm)) for s in firsts),
            label=lambda k: f"{k[0]} {k[1]} 위{k[2]} 아래{k[3]} 좌{k[4]} 우{k[5]} (mm)"),
        "header_footer_distance": _top(Counter((_r(s.header_mm), _r(s.footer_mm)) for s in firsts),
                                       label=lambda k: f"머리말 {k[0]} 꼬리말 {k[1]} (mm)"),
        "multi_section_docs": sum(1 for p in probes if len(p.sections) > 1),
    }


def _fonts(probes) -> dict:
    """글자 수 가중. 본문·표는 따로 본다."""
    def collect(where: str, pick: Callable):
        counter: Counter = Counter()
        for p in probes:
            for x in p.paragraphs:
                if x.where == where and not x.blank:
                    counter[pick(x)] += x.text_len
        return counter

    out = {}
    for where in ("body", "table"):
        out[where] = {
            "east_asia": _top(collect(where, lambda x: x.fmt.east_asia or "(기본)")),
            "size_pt": _top(collect(where, lambda x: x.fmt.size_pt if x.fmt.size_pt is not None else "(기본)")),
            "char_scale_pct": _top(collect(where, lambda x: x.fmt.char_scale_pct or 100)),
            "color": _top(collect(where, lambda x: x.fmt.color or "(자동)")),
        }
    bold = [x for p in probes for x in _body(p) if not x.blank]
    out["body_bold_share"] = _ratio(sum(x.text_len for x in bold if x.fmt.bold), sum(x.text_len for x in bold))
    return out


def _spacing(probes) -> dict:
    body = [x for p in probes for x in _body(p) if not x.blank]
    return {
        "line": _top(Counter((x.line_rule, x.line_value) for x in body),
                     label=lambda k: f"{k[1]}배" if k[0] == "auto" else f"{k[1]}pt({k[0]})"),
        "space_before_pt": _top(Counter(x.space_before_pt for x in body)),
        "space_after_pt": _top(Counter(x.space_after_pt for x in body)),
        "align": _top(Counter(x.align or "(기본 왼쪽)" for x in body)),
    }


def _blank_lines(probes) -> dict:
    """줄 띄우기를 빈 문단으로 하는가, 단락 간격으로 하는가."""
    runs: Counter = Counter()
    before_marker: dict[str, list[int]] = {}
    ratios = []
    for p in probes:
        body = _body(p)
        ratios.append(_ratio(sum(1 for x in body if x.blank), len(body)) or 0.0)
        streak = 0
        for i, x in enumerate(body):
            if x.blank:
                streak += 1
                continue
            if streak:
                runs[streak] += 1
            if x.marker_kind:
                key = _marker_key(x)
                before_marker.setdefault(key, []).append(1 if streak else 0)
            streak = 0
    return {
        "blank_ratio_per_doc": _dist(ratios),
        "consecutive_blank_runs": _top(runs, label=lambda k: f"{k}줄 연속"),
        "blank_before_marker": {
            k: {"n": len(v), "share": round(sum(v) / len(v), 2)}
            for k, v in sorted(before_marker.items(), key=lambda kv: -len(kv[1]))[:TOP * 2]
        },
        "invisible_chars": dict(Counter(c for p in probes for x in p.paragraphs
                                        for c in x.invisible_codes).most_common(TOP)),
    }


def _markers(probes) -> dict:
    """말머리별 실제 서식 — 정식보고서의 계층 규칙(기호·들여쓰기·굵기)이 여기서 보인다."""
    groups: dict[str, list[ParaProbe]] = {}
    with_child: set[int] = set()   # 바로 다음 줄이 더 깊은 말머리인 항목
    for p in probes:
        items = _body_items(p)
        for x, nxt in zip(items, items[1:]):
            if x.marker_kind and nxt.marker_kind and \
                    (nxt.left_mm, nxt.leading_spaces) > (x.left_mm, x.leading_spaces):
                with_child.add(id(x))
        for x in _body(p):
            if x.marker_kind and not x.blank:
                groups.setdefault(_marker_key(x), []).append(x)
    rows = []
    for key, items in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:TOP * 3]:
        sizes = [x.fmt.size_pt for x in items if x.fmt.size_pt]
        sentences = [s for x in items for s in _SENTENCE_SPLIT.split(x.text.strip()) if s.strip()]
        rows.append({
            "marker": key,
            "count": len(items),
            "left_mm_median": _median([x.left_mm for x in items]),
            "first_line_mm_median": _median([x.first_line_mm for x in items]),
            "leading_spaces_median": _median([x.leading_spaces for x in items]),
            "leading_spaces": _top(Counter(x.leading_spaces for x in items), n=5),
            "leading_wide_share": _ratio(sum(1 for x in items if x.leading_wide), len(items)),
            "size_pt_median": _median(sizes),
            "bold_share": _ratio(sum(1 for x in items if x.fmt.bold), len(items)),
            "sep": dict(Counter(x.marker_sep or "-" for x in items).most_common(3)),
            "text_len": _dist([x.text_len for x in items]),
            # 층(말머리)마다 종결·길이가 다르다 — 같은 문장도 층에 따라 허용 여부가 갈린다
            "ending_class": _top(Counter(_ending_class(t) for t in sentences), n=4),
            "period_ended_share": _ratio(sum(1 for t in sentences if t.rstrip().endswith(".")), len(sentences)),
            "bold_pattern": _top(Counter(x.bold_pattern for x in items), n=4),
            "bold_by_children": {
                label: _top(Counter(x.bold_pattern for x in group), n=3)
                for label, group in (("하위 항목 있음", [x for x in items if id(x) in with_child]),
                                     ("하위 항목 없음", [x for x in items if id(x) not in with_child]))},
            "underline_share": _ratio(sum(1 for x in items if x.underline), len(items)),
            "space_before_pt": _top(Counter(x.space_before_pt for x in items), n=3),
            "space_after_pt": _top(Counter(x.space_after_pt for x in items), n=3),
            "line": _top(Counter((x.line_rule, x.line_value) for x in items), n=3,
                         label=lambda k: f"{k[1]}배" if k[0] == "auto" else f"{k[1]}pt({k[0]})"),
            "color": _top(Counter(x.fmt.color or "(자동)" for x in items), n=3),
            "ending_tail": [r for r in _top(Counter(_tail(t) for t in sentences if _tail(t)), n=8)
                            if r["count"] >= 2],
        })
    # 층 순서 = 왼쪽 들여쓰기가 얕은 것부터. 층 이름을 코드에 두지 않고 말뭉치의 말머리·들여쓰기에서 얻는다.
    # 들여쓰기를 앞 공백으로 친 문서는 left_mm이 모두 0이라, 같으면 앞 공백 수로 깊이를 가른다.
    rows.sort(key=lambda r: (r["left_mm_median"] if r["left_mm_median"] is not None else 0,
                             r["leading_spaces_median"] if r["leading_spaces_median"] is not None else 0,
                             -r["count"]))
    return {
        "by_marker": rows,
        "auto_numbering_share": _ratio(
            sum(1 for p in probes for x in _body(p) if x.marker_kind == "auto"),
            sum(1 for p in probes for x in _body(p) if x.marker_kind)),
        "docs_with_pua_bullet": sum(1 for p in probes if any(x.pua_bullet for x in p.paragraphs)),
        "no_marker_paragraph_share": _ratio(
            sum(1 for p in probes for x in _body(p) if not x.marker_kind and not x.blank),
            sum(1 for p in probes for x in _body(p) if not x.blank)),
    }


def _text(probes) -> dict:
    """문장 형태: 항목 길이, 문장 수, 종결 형태. (표 셀 글은 따로)"""
    out = {}
    for where in ("body", "table"):
        items = [x for p in probes for x in p.paragraphs if x.where == where and x.text.strip() and not x.blank]
        sentences: list[str] = []
        per_item = []
        for x in items:
            parts = [s for s in _SENTENCE_SPLIT.split(x.text.strip()) if s.strip()]
            per_item.append(len(parts))
            sentences += parts
        classes = Counter(_ending_class(s) for s in sentences)
        tails = Counter(_tail(s) for s in sentences if _tail(s))
        out[where] = {
            "items": len(items),
            "item_chars": _dist([x.text_len for x in items]),
            "sentences_per_item": _dist(per_item),
            "ending_class": _top(classes),
            "ending_tail": _top(tails, n=15),
            "period_ended_share": _ratio(sum(1 for s in sentences if s.rstrip().endswith(".")), len(sentences)),
        }
    return out


def _notation(probes) -> dict:
    texts = [x.text for p in probes for x in p.paragraphs if not x.blank]
    return {
        "date_forms": {k: sum(len(rx.findall(t)) for t in texts) for k, rx in _DATE_FORMS.items()},
        "number_forms": {k: sum(len(rx.findall(t)) for t in texts) for k, rx in _NUMBER_FORMS.items()},
    }


def _tables(probes) -> dict:
    tables = [t for p in probes for t in p.tables]
    outer = [t for t in tables if not t.nested]
    widths = []
    for p in probes:
        if not p.sections:
            continue
        s = p.sections[0]
        text_width = s.width_mm - s.left_mm - s.right_mm
        widths += [round(t.total_width_mm / text_width, 2) for t in p.tables
                   if not t.nested and t.total_width_mm and text_width > 0]

    def mean(values):
        values = [v for v in values if v is not None]
        return round(sum(values) / len(values), 2) if values else None

    return {
        "per_doc": _dist([len(p.tables) for p in probes]),
        "rows": _dist([t.rows for t in tables]),
        "cols": _dist([t.cols for t in tables]),
        "jc": _top(Counter(t.jc or "(기본 왼쪽)" for t in tables)),
        "header_rows": _top(Counter(t.header_rows for t in tables)),
        "header_fill": _top(Counter(t.header_fill or "(없음)" for t in tables)),
        "merged_share": _ratio(sum(1 for t in tables if t.merged_cells), len(tables)),
        "nested": sum(1 for t in tables if t.nested),
        "style": _top(Counter(t.style_id or "(없음)" for t in tables)),
        "style_first_row_fill": _top(Counter(t.style_first_row_fill or "(없음)" for t in tables)),
        "style_first_row_bold": _top(Counter(t.style_first_row_bold for t in tables)),
        "look_first_row": _top(Counter(t.look_first_row for t in tables)),
        "fill_first_row_mean": mean(t.fill_first_row_share for t in tables),
        "fill_first_col_mean": mean(t.fill_first_col_share for t in tables),
        "fill_other_mean": mean(t.fill_other_share for t in tables),
        "fill_colors": _top(Counter(c for t in tables for c in t.fill_colors)),
        "cell_border_mean": mean(t.cell_border_share for t in tables),
        "cell_border_kinds": _top(Counter(k for t in tables for k in t.cell_border_kinds)),
        "width_vs_text": _dist(widths),
        "indent_mm": _top(Counter(_r(t.indent_mm) for t in outer)),
        "borders": _top(Counter(", ".join(f"{k} {v}" for k, v in sorted(t.borders.items())) or "(표 수준 지정 없음)"
                                for t in tables), n=5),
        "before_kind": _top(Counter(t.before_kind for t in outer)),
        "after_kind": _top(Counter(t.after_kind or "(문서 끝)" for t in outer)),
    }


def _table_cells(probes) -> dict:
    """표 칸 서식: 머리행(0행)·첫 열·나머지를 따로 본다."""
    groups: dict[str, list[ParaProbe]] = {"머리행(0행)": [], "첫 열(1행 이후)": [], "나머지 칸": []}
    for p in probes:
        for x in p.paragraphs:
            if x.where != "table" or x.blank or x.cell_row is None:
                continue
            key = "머리행(0행)" if x.cell_row == 0 else "첫 열(1행 이후)" if x.cell_col == 0 else "나머지 칸"
            groups[key].append(x)
    return {
        key: {
            "count": len(items),
            "align": _top(Counter(x.align or "(기본 왼쪽)" for x in items), n=4),
            "bold_pattern": _top(Counter(x.bold_pattern for x in items), n=3),
            "size_pt": _top(Counter(x.fmt.size_pt if x.fmt.size_pt is not None else "(기본)" for x in items), n=4),
            "color": _top(Counter(x.fmt.color or "(자동)" for x in items), n=3),
            "text_len": _dist([x.text_len for x in items]),
        }
        for key, items in groups.items()
    }


def _headers_footers(probes) -> dict:
    out = {}
    for kind in ("header", "footer"):
        items = [h for p in probes for h in p.headers_footers if h.kind == kind and not h.linked]
        out[kind] = {
            "with_text_share": _ratio(sum(1 for h in items if h.text_len), len(items)),
            "page_field_share": _ratio(sum(1 for h in items if h.has_page_field), len(items)),
            "align": _top(Counter(h.align or "(기본)" for h in items if h.text_len or h.has_page_field)),
            "text_len": _dist([h.text_len for h in items if h.text_len]),
        }
    out["title_page_docs"] = sum(1 for p in probes if any(s.title_page for s in p.sections))
    return out


def _annotations(probes) -> dict:
    """텍스트 상자 = 본문 문장 옆·아래에 붙이는 주석. 상자 서식·배치·글 형태를 본문과 따로 본다."""
    boxes = [b for p in probes for b in p.textboxes]
    paras = [x for p in probes for x in p.paragraphs if x.where == "textbox" and not x.blank]
    sentences = [s for x in paras for s in _SENTENCE_SPLIT.split(x.text.strip()) if s.strip()]

    def weighted(pick: Callable) -> Counter:
        counter: Counter = Counter()
        for x in paras:
            counter[pick(x)] += x.text_len
        return counter

    return {
        "boxes": len(boxes),
        "docs_with_boxes": sum(1 for p in probes if p.textboxes),
        "per_doc": _dist([len(p.textboxes) for p in probes]),
        "floating_share": _ratio(sum(1 for b in boxes if b.floating), len(boxes)),
        "placement": _top(Counter(b.placement for b in boxes)),
        "wrap": _top(Counter(b.wrap or "(없음)" for b in boxes)),
        "x_mm": _dist([b.x_mm for b in boxes if b.x_mm is not None]),
        "v_offset_mm": _dist([b.v_offset_mm for b in boxes if b.v_offset_mm is not None]),
        "behind": _top(Counter(b.behind for b in boxes)),
        "width_mm": _dist([b.width_mm for b in boxes if b.width_mm is not None]),
        "height_mm": _dist([b.height_mm for b in boxes if b.height_mm is not None]),
        "border": _top(Counter((b.border, b.border_color or "-") for b in boxes),
                       label=lambda k: f"{k[0]} {k[1]}"),
        "fill": _top(Counter(b.fill for b in boxes)),
        "paragraphs_per_box": _dist([b.paragraphs for b in boxes]),
        "box_chars": _dist([b.text_len for b in boxes]),
        "east_asia": _top(weighted(lambda x: x.fmt.east_asia or "(기본)")),
        "size_pt": _top(weighted(lambda x: x.fmt.size_pt if x.fmt.size_pt is not None else "(기본)")),
        "color": _top(weighted(lambda x: x.fmt.color or "(자동)")),
        "bold_share": _ratio(sum(x.text_len for x in paras if x.fmt.bold), sum(x.text_len for x in paras)),
        "line": _top(Counter((x.line_rule, x.line_value) for x in paras),
                     label=lambda k: f"{k[1]}배" if k[0] == "auto" else f"{k[1]}pt({k[0]})"),
        "align": _top(Counter(x.align or "(기본 왼쪽)" for x in paras)),
        "marker_inside": _top(Counter(x.marker or "(없음)" for x in paras), n=6),
        "ending_class": _top(Counter(_ending_class(s) for s in sentences)),
        "ending_tail": _top(Counter(_tail(s) for s in sentences if _tail(s)), n=15),
        "period_ended_share": _ratio(sum(1 for s in sentences if s.rstrip().endswith(".")), len(sentences)),
        "anchor_where": _top(Counter(b.anchor_where or "(알 수 없음)" for b in boxes)),
        "anchor_marker": _top(Counter(b.anchor_marker or "(말머리 없음)" for b in boxes)),
        "anchor_text_len": _dist([b.anchor_text_len for b in boxes if b.anchor_text_len]),
    }


def _body_items(probe: DocProbe) -> list[ParaProbe]:
    return [x for x in _body(probe) if not x.blank]


_OPENERS = "[［【〔〈《「『"
_DATE_ANY = re.compile(r"[’']?\d{2,4}\s*[.\-/년]\s*\d{1,2}\s*[.\-/월]\s*(?:\d{1,2}\s*[.일]?)?")


def _opener_class(text: str) -> str:
    t = text.strip()
    if not t:
        return "기타"
    if t[0] in _OPENERS:
        return "꺾쇠로 시작"
    if t[0] in "(（":
        return "괄호로 시작"
    if _DATE_ANY.match(t):
        return "날짜로 시작"
    if t[0].isdigit():
        return "숫자로 시작"
    return "글자로 시작"


def _unmarked(probes) -> dict:
    """말머리 없는 본문 줄이 무엇인가 (제목·날짜·표 제목·부연 구분)."""
    items = [x for p in probes for x in _body_items(p) if not x.marker_kind]
    return {
        "count": len(items),
        "opener": _top(Counter(_opener_class(x.text) for x in items)),
        "profile": _top(Counter((x.align or "(기본 왼쪽)", x.fmt.size_pt, x.bold_pattern, x.left_mm > 0)
                                for x in items), n=8,
                        label=lambda k: f"{k[0]} {k[1]}pt 굵기:{k[2]} {'들여씀' if k[3] else '들여쓰기 없음'}"),
        "text_len": _dist([x.text_len for x in items]),
        "ending_class": _top(Counter(_ending_class(x.text.strip().rstrip(_CLOSERS)) for x in items), n=5),
    }


def _shape(x: ParaProbe) -> str:
    size = f"{x.fmt.size_pt:g}pt" if x.fmt.size_pt is not None else "기본크기"
    length = "짧음(≤10)" if x.text_len <= 10 else "중간(≤30)" if x.text_len <= 30 else "긺"
    return (f"{x.align or '왼쪽'}·{size}·굵기:{x.bold_pattern}{'·밑줄' if x.underline else ''}"
            f"·{x.marker or '말머리없음'}·{length}{'·날짜형' if _DATE_ANY.search(x.text) else ''}")


def _skeleton(probes) -> dict:
    """문서 첫머리·말미 줄이 어떤 모양인가 (제목·날짜·부서·결문 위치 관례)."""
    def at(position: int, from_end: bool = False):
        counter: Counter = Counter()
        for p in probes:
            body = _body_items(p)
            if len(body) > position:
                counter[_shape(body[-1 - position] if from_end else body[position])] += 1
        return _top(counter, n=4)

    return {
        "first": [{"position": i + 1, "shapes": at(i)} for i in range(6)],
        "last": [{"position": i + 1, "shapes": at(i, from_end=True)} for i in range(3)],
    }


def _dates(probes) -> dict:
    """날짜 표기 모양 — 숫자를 9로 가려 형식(점·공백·연도 자리수)만 센다."""
    counter: Counter = Counter()
    for p in probes:
        for x in p.paragraphs:
            if not x.blank:
                for m in _DATE_ANY.finditer(x.text):
                    counter[re.sub(r"\d", "9", m.group(0).strip())] += 1
    return {"shapes": _top(counter, n=10)}


def _phrases(probes) -> dict:
    """여러 문서에 반복되는 짧은 말만 — 제목·표 머리 용어. 한 문서에만 있는 말은 싣지 않는다."""
    def clean(x: ParaProbe) -> str:
        t = x.text.strip()
        if x.marker and t.startswith(x.marker):
            t = t[len(x.marker):]
        return re.sub(r"\s+", " ", t).strip()

    titles: dict[str, set] = {}
    terms: dict[str, set] = {}
    for p in probes:
        for x in p.paragraphs:
            if x.blank:
                continue
            text = clean(x)
            if not text:
                continue
            if (x.where == "body" and re.fullmatch(r"\d{1,2}\.|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]\.?", x.marker or "")
                    and len(text) <= 20):
                titles.setdefault(text, set()).add(p.doc_id)
            if x.where == "table" and (x.cell_row == 0 or x.cell_col == 0) and len(text) <= 10:
                terms.setdefault(text, set()).add(p.doc_id)

    def repeated(groups: dict, n: int):
        rows = sorted(((k, len(v)) for k, v in groups.items() if len(v) >= 2), key=lambda kv: (-kv[1], kv[0]))
        return [{"value": k, "docs": c} for k, c in rows[:n]]

    latin: dict[str, set] = {}
    for p in probes:
        for x in p.paragraphs:
            for word in re.findall(r"[A-Za-z][A-Za-z0-9&/.-]{1,11}", x.text):
                latin.setdefault(word, set()).add(p.doc_id)
    return {"section_titles": repeated(titles, 25), "table_terms": repeated(terms, 30),
            "latin_terms": repeated(latin, 20)}


def _fitting(probes) -> dict:
    """줄 맞춤 실측 — 원본이 줄을 얼마나 꽉 채우고, 글자 간격을 얼마나·얼마나 자주 좁히는가, 내려쓴 줄은 어떤 모양인가."""
    body = [x for p in probes for x in _body_items(p)]
    spaced = [x for x in body if x.fmt.spacing_twips]
    groups = {"보통 글자·간격 그대로": [], "보통 글자·좁힘": [], "굵은 글자·간격 그대로": [], "굵은 글자·좁힘": []}
    for x in body:
        if x.width_ratio is None or not 0.5 <= x.width_ratio <= 1.12:  # 한 줄에 쓴 문단만(여러 줄은 1을 훨씬 넘는다)
            continue
        bold = x.bold_pattern == "all"
        narrowed = bool(x.fmt.spacing_twips and x.fmt.spacing_twips < 0)
        groups[f"{'굵은' if bold else '보통'} 글자·{'좁힘' if narrowed else '간격 그대로'}"].append(x.width_ratio)
    # 내려쓴 줄: 말머리 없이 앞 공백으로 시작하고 바로 윗줄이 말머리 줄
    follow, follow_spaces, follow_by = 0, Counter(), Counter()
    unmarked_after_marker = 0
    for p in probes:
        items = _body_items(p)
        for prev, cur in zip(items, items[1:]):
            if prev.marker_kind and not cur.marker_kind:
                unmarked_after_marker += 1
                if cur.leading_spaces:
                    follow += 1
                    follow_spaces[cur.leading_spaces] += 1
                    follow_by[_marker_key(prev)] += 1
    return {
        "paragraphs": len(body),
        "spaced_share": _ratio(len(spaced), len(body)),
        "spacing_pt": _top(Counter(round(x.fmt.spacing_twips / 20, 2) for x in spaced), n=8),
        "width_ratio": {k: _dist(v) for k, v in groups.items()},
        "unmarked_after_marker": unmarked_after_marker,
        "continuation_like": follow,
        "continuation_spaces": _top(follow_spaces, n=6),
        "continuation_after": _top(follow_by, n=6),
    }


def _dominant(probe: DocProbe, pick: Callable):
    counter: Counter = Counter()
    for x in _body_items(probe):
        value = pick(x)
        if value is not None:
            counter[value] += x.text_len
    return counter.most_common(1)[0][0] if counter else None


_HANGUL = re.compile("[가-힣ㄱ-ㅎㅏ-ㅣ]")
_HANJA = re.compile("[\u4e00-\u9fff]")


def _charset(probes) -> dict:
    """글자 종류 구성과 기호 목록 — 한자 약어(無·要)·화살표(↑)·▲ 같은 표기 관례를 본다."""
    total = hangul = hanja = latin = digits = 0
    symbols: Counter = Counter()
    hanja_chars: Counter = Counter()
    for p in probes:
        for x in p.paragraphs:
            if x.blank:
                continue
            for ch in x.text:
                if ch.isspace():
                    continue
                total += 1
                if _HANGUL.match(ch):
                    hangul += 1
                elif _HANJA.match(ch):
                    hanja += 1
                    hanja_chars[ch] += 1
                elif ch.isascii() and ch.isalpha():
                    latin += 1
                elif ch.isdigit():
                    digits += 1
                elif ch not in ".,:;()[]'\"/%-~":
                    symbols[ch] += 1
    return {
        "share": {"한글": _ratio(hangul, total), "한자": _ratio(hanja, total), "영문": _ratio(latin, total),
                  "숫자": _ratio(digits, total)},
        "symbols": [{"value": k, "count": c} for k, c in symbols.most_common(25)],
        "hanja": [{"value": k, "count": c} for k, c in hanja_chars.most_common(10)],
    }


def _structure(probes) -> dict:
    return {
        "toc_docs": sum(1 for p in probes if p.toc),
        "textbox_docs": sum(1 for p in probes if p.textbox_count),
        "textboxes_per_doc": _dist([p.textbox_count for p in probes]),
        "page_breaks_per_doc": _dist([p.page_breaks for p in probes]),
        "heading_style_docs": sum(1 for p in probes if any(x.heading_level for x in p.paragraphs)),
    }


# ── 도우미 ──────────────────────────────────────────────────────────────


def _body(probe: DocProbe) -> list[ParaProbe]:
    return [x for x in probe.paragraphs if x.where == "body"]


def _marker_key(x: ParaProbe) -> str:
    return f"{'글자' if x.marker_kind == 'typed' else '자동'} {x.marker or '(알 수 없음)'}"


def _ending_class(sentence: str) -> str:
    core = sentence.rstrip(_CLOSERS)
    if not core:
        return "기타"
    last = core[-1]
    if core.endswith("니다"):
        return "~습니다 (합쇼체)"
    if last == "다":
        return "~다 (서술)"
    if last == "요":
        return "~요"
    if last in _NOUNISH_ENDS:
        return "~음/함/임 (개조식)"
    if "가" <= last <= "힣":
        return "명사 종결"
    if last.isdigit() or last in "%)":
        return "수치·기호 종결"
    return "기타"


def _tail(sentence: str) -> str:
    core = sentence.rstrip(_CLOSERS)
    return core[-2:] if len(core) >= 2 else ""


def _r(mm: float) -> float:
    return round(mm * 2) / 2  # 0.5mm 단위로 묶어 미세한 차이가 다른 값으로 안 갈리게


def _ratio(part: int | float, whole: int | float) -> float | None:
    return round(part / whole, 3) if whole else None


def _median(values: Iterable[float]) -> float | None:
    values = list(values)
    return round(statistics.median(values), 2) if values else None


def _dist(values: list[float]) -> dict | None:
    if not values:
        return None
    ordered = sorted(values)

    def pct(q: float) -> float:
        return round(ordered[min(len(ordered) - 1, int(q * len(ordered)))], 2)

    return {"n": len(ordered), "min": round(ordered[0], 2), "p25": pct(0.25), "p50": pct(0.5),
            "p75": pct(0.75), "p90": pct(0.9), "max": round(ordered[-1], 2)}


def _top(counter: Counter, *, n: int = TOP, label: Callable | None = None) -> list[dict]:
    total = sum(counter.values())
    return [
        {"value": label(k) if label else k, "count": c, "share": round(c / total, 3)}
        for k, c in counter.most_common(n)
    ]
