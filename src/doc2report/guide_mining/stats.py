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


def summarize(probes: list[DocProbe]) -> dict:
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
    for p in probes:
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
            "size_pt_median": _median(sizes),
            "bold_share": _ratio(sum(1 for x in items if x.fmt.bold), len(items)),
            "sep": dict(Counter(x.marker_sep or "-" for x in items).most_common(3)),
            "text_len": _dist([x.text_len for x in items]),
            # 층(말머리)마다 종결·길이가 다르다 — 같은 문장도 층에 따라 허용 여부가 갈린다
            "ending_class": _top(Counter(_ending_class(t) for t in sentences), n=4),
            "period_ended_share": _ratio(sum(1 for t in sentences if t.rstrip().endswith(".")), len(sentences)),
        })
    # 층 순서 = 왼쪽 들여쓰기가 얕은 것부터. 층 이름을 코드에 두지 않고 말뭉치의 말머리·들여쓰기에서 얻는다.
    rows.sort(key=lambda r: (r["left_mm_median"] if r["left_mm_median"] is not None else 0, -r["count"]))
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
    return {
        "per_doc": _dist([len(p.tables) for p in probes]),
        "rows": _dist([t.rows for t in tables]),
        "cols": _dist([t.cols for t in tables]),
        "jc": _top(Counter(t.jc or "(기본 왼쪽)" for t in tables)),
        "header_rows": _top(Counter(t.header_rows for t in tables)),
        "header_fill": _top(Counter(t.header_fill or "(없음)" for t in tables)),
        "merged_share": _ratio(sum(1 for t in tables if t.merged_cells), len(tables)),
        "nested": sum(1 for t in tables if t.nested),
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
