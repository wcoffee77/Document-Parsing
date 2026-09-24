"""표를 A4 폭에 밀어 넣는 엔진 — 이 프로젝트의 핵심.

브라우저의 CSS 자동 테이블 레이아웃과 같은 접근을 쓴다.
  1. 셀마다 min(가장 긴 끊을 수 없는 덩어리) / max(한 줄로 다 썼을 때) 폭을 잰다
  2. 열 단위로 모으고, 사용가능폭 안에 max가 들어가면 그대로
  3. 안 들어가면 min을 바닥으로 두고 남는 폭을 (max-min) 비례로 배분
  4. min의 합조차 넘치면 프로파일의 축소 사다리를 순서대로 내려간다
     글자 크기 ↓ → 셀 여백 ↓ → (허용 시) 가로 페이지
확정된 폭은 렌더러가 tblLayout=fixed + tcW로 못 박아 Word가 다시 흐트러뜨리지 못하게 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..ir import Cell, Document, Table, iter_tables, plain
from ..ir import Paragraph
from ..profile import Profile
from ..units import fmt_pt
from .measure import TextMeasurer


@dataclass
class TableLayout:
    """한 표에 대한 확정된 배치. 렌더러는 이 값을 그대로 쓴다."""

    col_widths: list[int]  # EMU
    font_size: int  # EMU
    cell_margin_x: int  # EMU
    landscape: bool = False
    overflow: bool = False  # 최소 폭조차 못 맞춰 강제로 줄인 경우
    notes: list[str] = field(default_factory=list)

    @property
    def total_width(self) -> int:
        return sum(self.col_widths)


def plan_tables(doc: Document, profile: Profile) -> dict[int, TableLayout]:
    """문서 안 모든 표의 배치를 계산해 id(table) → TableLayout 으로 돌려준다.

    IR에는 서식·치수를 넣지 않기 위해 별도 사이드 테이블로 관리한다.
    """
    available = int(profile.page.usable_width * profile.tables.width_ratio)
    return {id(t): fit_table(t, profile, available) for t in iter_tables(doc)}


def fit_table(table: Table, profile: Profile, available_width: int) -> TableLayout:
    rules = profile.tables
    ladder = profile.table_font_ladder()
    margins = [rules.cell_margin_x]
    if rules.cell_margin_x_min is not None and rules.cell_margin_x_min < rules.cell_margin_x:
        margins.append(rules.cell_margin_x_min)

    widths = [available_width]
    if rules.allow_landscape:
        widths.append(int(profile.page.landscape().usable_width * rules.width_ratio))

    base_size = ladder[0]

    # 1차: 폭도 맞고 셀 줄 수도 읽을 만한 조합을 위에서부터 찾는다.
    for page_idx, avail in enumerate(widths):
        for size in ladder:
            for margin in margins:
                attempt = _try_fit(table, profile, avail, size, margin, check_lines=True)
                if attempt is not None:
                    attempt.landscape = page_idx > 0
                    _annotate(attempt, base_size, size, rules.cell_margin_x, margin)
                    return attempt

    # 2차: 줄 수 제약은 못 지키더라도 폭은 맞춘다. 줄 수는 글자가 작을수록 적으므로 최소 크기로.
    for page_idx, avail in enumerate(widths):
        for margin in margins:
            attempt = _try_fit(table, profile, avail, ladder[-1], margins[-1], check_lines=False)
            if attempt is not None:
                attempt.landscape = page_idx > 0
                _annotate(attempt, base_size, ladder[-1], rules.cell_margin_x, margins[-1])
                if rules.max_cell_lines:
                    attempt.notes.append(
                        f"셀 줄 수가 {rules.max_cell_lines}줄을 넘어 최소 글자 크기를 적용함"
                    )
                return attempt

    # 3차: 최소 폭조차 넘치면 비례 축소 (텍스트는 세로로 길어질 뿐 잘리지 않음)
    result = _force_fit(table, profile, widths[-1], ladder[-1], margins[-1])
    result.landscape = len(widths) > 1
    _annotate(result, base_size, ladder[-1], rules.cell_margin_x, margins[-1])
    result.notes.append("최소 글자 크기로도 자연 폭을 맞출 수 없어 비례 축소함 (줄바꿈이 늘어남)")
    return result


def _annotate(layout: TableLayout, base_size: int, size: int, base_margin: int, margin: int) -> None:
    if size != base_size:
        layout.notes.append(f"표 글자 크기 {fmt_pt(base_size)} → {fmt_pt(size)} 하향")
    if margin != base_margin:
        layout.notes.append(f"셀 여백 {fmt_pt(base_margin)} → {fmt_pt(margin)} 축소")
    if layout.landscape:
        layout.notes.append("가로 방향 페이지로 전환")


def _try_fit(
    table: Table, profile: Profile, available: int, size: int, margin: int,
    *, check_lines: bool = True,
) -> TableLayout | None:
    """주어진 글자 크기·여백에서 배치 가능하면 TableLayout, 아니면 None."""
    cols = table.col_count
    if cols == 0:
        return None
    usable = _content_budget(profile, available, cols, margin)
    if usable <= 0:
        return None

    mins, maxs = column_demands(table, profile, size)
    total_min, total_max = sum(mins), sum(maxs)

    if total_max <= usable:
        widths = _scale_to(maxs, usable)
    elif total_min <= usable:
        slack = usable - total_min
        spread = [mx - mn for mn, mx in zip(mins, maxs)]
        denom = sum(spread)
        widths = [mn + (slack * s / denom if denom else slack / cols)
                  for mn, s in zip(mins, spread)]
        widths = _scale_to(widths, usable)
    else:
        return None

    limit = profile.tables.max_cell_lines
    if check_lines and limit and _max_cell_lines(table, profile, size, widths) > limit:
        return None

    return TableLayout(
        col_widths=_to_cell_widths(widths, margin),
        font_size=size,
        cell_margin_x=margin,
    )


def _max_cell_lines(
    table: Table, profile: Profile, size: int, content_widths: list[float]
) -> int:
    """확정 폭에서 가장 많이 줄바꿈되는 셀의 줄 수.

    열을 1글자 폭까지 좁혀 '폭은 맞지만 세로로 한없이 길어지는' 표를 막는 기준이다.
    """
    worst = 0
    for cell, col, span in iter_grid(table):
        if col >= len(content_widths):
            continue
        width = sum(content_widths[col : min(col + span, len(content_widths))])
        spec = profile.font("table_header" if cell.is_header else "table")
        measurer = TextMeasurer(spec.east_asia, spec.latin, size, bold=bool(spec.bold))
        for line in cell_lines(cell):
            worst = max(worst, measurer.wrap_count(line, width))
    return worst


def _force_fit(
    table: Table, profile: Profile, available: int, size: int, margin: int
) -> TableLayout:
    """어떤 조합으로도 min 합을 못 맞출 때: 최소 폭을 비례 축소해서라도 넣는다."""
    cols = max(1, table.col_count)
    usable = max(_content_budget(profile, available, cols, margin), cols * 1)
    mins, _ = column_demands(table, profile, size)
    widths = _scale_to(mins, usable)
    return TableLayout(
        col_widths=_to_cell_widths(widths, margin),
        font_size=size,
        cell_margin_x=margin,
        overflow=True,
    )


def _content_budget(profile: Profile, available: int, cols: int, margin: int) -> int:
    """텍스트가 실제로 쓸 수 있는 폭 = 표 폭 − 셀 여백 − 테두리 − 안전 여유."""
    rules = profile.tables
    border = (rules.border_width or 0) * (cols + 1)
    padding = margin * 2 * cols
    return int(available * (1 - rules.safety_margin)) - padding - border


def _to_cell_widths(content_widths: list[float], margin: int) -> list[int]:
    """내용 폭 → 셀 전체 폭(여백 포함). docx의 tcW는 여백을 포함한 값이다."""
    return [int(round(w)) + margin * 2 for w in content_widths]


def _scale_to(widths: list[float], target: float) -> list[float]:
    total = sum(widths)
    if total <= 0:
        return [target / max(1, len(widths))] * len(widths)
    factor = target / total
    return [w * factor for w in widths]


# ── 열별 요구 폭 ────────────────────────────────────────────────────────


def column_demands(table: Table, profile: Profile, size: int) -> tuple[list[float], list[float]]:
    """각 열의 (최소 폭, 자연 폭). colspan은 걸친 열들에 나눠 반영한다."""
    cols = table.col_count
    mins = [0.0] * cols
    maxs = [0.0] * cols
    spans: list[tuple[int, int, float, float]] = []  # (start, span, min, max)

    for cell, col, span in iter_grid(table):
        if col >= cols:
            continue
        mn, mx = _cell_demand(cell, profile, size)
        if span == 1:
            mins[col] = max(mins[col], mn)
            maxs[col] = max(maxs[col], mx)
        else:
            spans.append((col, span, mn, mx))

    for col, span, mn, mx in spans:
        end = min(col + span, cols)
        for target, value in ((mins, mn), (maxs, mx)):
            current = sum(target[col:end])
            if current < value:
                extra = (value - current) / (end - col)
                for k in range(col, end):
                    target[k] += extra

    for i in range(cols):
        maxs[i] = max(maxs[i], mins[i])
    return mins, maxs


def iter_grid(table: Table):
    """(셀, 시작 열, colspan) 순회 — rowspan으로 밀리는 자리를 고려."""
    occupied: dict[tuple[int, int], bool] = {}
    for r, row in enumerate(table.rows):
        col = 0
        for cell in row.cells:
            while occupied.get((r, col)):
                col += 1
            for rr in range(r, r + cell.rowspan):
                for cc in range(col, col + cell.colspan):
                    occupied[(rr, cc)] = True
            yield cell, col, cell.colspan
            col += cell.colspan


def _cell_demand(cell: Cell, profile: Profile, size: int) -> tuple[float, float]:
    spec = profile.font("table_header" if cell.is_header else "table")
    measurer = TextMeasurer(spec.east_asia, spec.latin, size, bold=bool(spec.bold))
    mn = mx = 0.0
    for line in cell_lines(cell):
        mn = max(mn, measurer.longest_word_width(line))
        mx = max(mx, measurer.width(line))
    return mn, mx


def cell_lines(cell: Cell) -> list[str]:
    """셀 안 텍스트를 줄 단위로. (셀 안의 표는 폭 계산에서 제외 — 드물고 재귀가 복잡)"""
    lines: list[str] = []
    for block in cell.blocks:
        if isinstance(block, Paragraph):
            text = plain(block.runs).strip()
            if text:
                lines.append(text)
        elif hasattr(block, "runs"):
            text = plain(block.runs).strip()
            if text:
                lines.append(text)
        elif hasattr(block, "text"):
            lines.extend(str(block.text).splitlines())
    return lines or [""]
