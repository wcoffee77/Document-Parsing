"""문서가 세로로 얼마나 차는지 어림하고, 여유가 있으면 넉넉하게 쓰도록 판단한다.

"단락 뒤 간격은 6pt, 지면에 여유가 있으면 12pt까지", "여유가 있으면 셀 높이를 키워
표가 답답하지 않게" 같은 요구를 판단하려면 문서가 몇 쪽이고 마지막 쪽이 얼마나
비는지를 알아야 한다. 정확한 조판은 Word의 몫이므로 여기서는 어림만 한다.

어림 기준: 글자 크기 × 줄간격 × 1.2(한 줄이 차지하는 실제 높이) × 줄 수.
넉넉하게 잡아 "여유 있음"을 과하게 판단하지 않도록 한다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..ir import (
    Block,
    Callout,
    CodeBlock,
    Document,
    Heading,
    HorizontalRule,
    Image,
    ListItem,
    PageBreak,
    Paragraph,
    Table,
    plain,
)
from ..profile import FontSpec, Profile
from .measure import TextMeasurer
from .table_fit import TableLayout, cell_lines, iter_grid

# 글꼴 크기 대비 한 줄이 실제로 차지하는 높이(윗줄 여백 포함). Word 기본 동작의 근사치.
SINGLE_LINE_FACTOR = 1.2
# 여유 판단 뒤에도 이만큼(쪽 높이 대비)은 남겨 둔다. 어림 오차로 쪽이 넘어가지 않도록.
SAFETY_SHARE = 0.10


@dataclass
class FlowPlan:
    relaxed: bool = False  # 지면에 여유가 있어 간격·행 높이를 넉넉히 써도 되는가
    estimated_height: int = 0
    pages: int = 1
    spare: int = 0  # 마지막 쪽에 남는 높이(EMU)
    notes: list[str] = field(default_factory=list)
    # 표를 한 쪽에 넣으려고 줄간격을 줄일 문단·항목: id(block) → 배율(0.9 = 10% 줄임)
    line_scale: dict[int, float] = field(default_factory=dict)


def plan_flow(doc: Document, profile: Profile,
              layouts: dict[int, TableLayout]) -> FlowPlan:
    usable_h = profile.page.usable_height
    height = _blocks_height(doc, profile, layouts)

    pages = max(1, math.ceil(height / usable_h)) if usable_h else 1
    spare = pages * usable_h - height

    extra = _extra_if_relaxed(doc, profile, layouts)
    relaxed = extra > 0 and spare - extra > usable_h * SAFETY_SHARE

    plan = FlowPlan(relaxed=relaxed, estimated_height=height, pages=pages, spare=spare)
    if profile.tables.keep_on_page and usable_h:
        if relaxed and _fit_tables_on_pages(doc, profile, layouts, relaxed=True)[2]:
            relaxed = plan.relaxed = False   # 넉넉한 간격이 표를 쪽 사이로 밀어낸다 — 표가 잘리지 않는 것이 먼저
            plan.notes.append("넉넉한 간격을 쓰면 표가 쪽을 넘어가 간격을 기본값으로 둠")
        scales, notes, _ = _fit_tables_on_pages(doc, profile, layouts, relaxed=relaxed)
        plan.line_scale = scales
        plan.notes += notes
    if relaxed:
        plan.notes.append(
            f"지면에 여유가 있어(약 {spare / usable_h:.0%} 쪽) 단락 간격과 행 높이를 넉넉히 적용함")
    return plan


def _fit_tables_on_pages(doc: Document, profile: Profile, layouts: dict[int, TableLayout], *, relaxed: bool
                         ) -> tuple[dict[int, float], list[str], bool]:
    """쪽을 넘어 잘릴 표를 찾아, 그 쪽 앞쪽 문단·항목의 줄간격을 미세하게 줄여 한 쪽에 들어가게 한다(2026-10-08 사용자).

    (줄간격을 줄일 블록 → 배율, 리포트 노트, 줄여도 못 넣은 표가 있는가). 높이는 어림이라 확실한 보장은 렌더러의 keep-with-next가 한다 —
    여기서 줄이는 것은 표가 다음 쪽으로 통째로 밀려 윗쪽이 크게 비는 것을 막으려는 시도다. 쪽 높이보다 큰 표는 손대지 않는다."""
    usable = profile.page.usable_height
    rules = profile.tables
    margin = rules.page_fit_margin or 0
    min_scale = rules.page_fit_min_scale or 1.0
    blocks = doc.blocks
    title_h = (_text_height(doc.title, profile.font("title"), profile.page.usable_width, profile) if doc.title else 0)

    def height(index: int, scale: float = 1.0) -> int:
        previous = blocks[index - 1] if index else None
        following = blocks[index + 1] if index + 1 < len(blocks) else None
        h = _block_height(blocks[index], profile, layouts, previous, following, scale=scale)
        return h + (_extra_for_block(blocks[index], following, profile, layouts) if relaxed else 0)

    heights = [height(i) for i in range(len(blocks))]
    scales: dict[int, float] = {}
    notes: list[str] = []
    failed = False
    y = title_h
    table_no = 0
    for i, block in enumerate(blocks):
        if isinstance(block, PageBreak):
            y = (int(y // usable) + 1) * usable if y % usable else y
            continue
        if isinstance(block, Table):
            table_no += 1
            h = heights[i]
            page_end = (int(y // usable) + 1) * usable
            if 0 < h <= usable and y + h > page_end:
                overflow = y + h - page_end + margin
                window = [j for j in range(i) if isinstance(blocks[j], (Paragraph, ListItem)) and _block_start(heights, j, title_h) >= page_end - usable
                          and id(blocks[j]) not in scales]
                gain, chosen = _compress(window, overflow, min_scale, height, heights)
                if chosen is not None:
                    scales.update({id(blocks[j]): chosen for j in window})
                    for j in window:
                        heights[j] = height(j, chosen)
                    y -= gain
                    notes.append(f"표 {table_no}: 한 쪽에 넣으려고 앞 {len(window)}개 문장의 줄간격을 {round((1 - chosen) * 100)}% 줄임(어림)")
                else:
                    failed = True
                    blank = page_end - y
                    y = page_end    # Word가 표를 통째로 다음 쪽으로 옮긴다
                    notes.append(f"표 {table_no}: 줄간격을 {round((1 - min_scale) * 100)}%까지 줄여도 한 쪽에 안 들어가 표를 다음 쪽으로 넘김"
                                 f"(앞 쪽 아래 약 {blank / 36000:.0f}mm 비게 됨)")
        y += heights[i]
    return scales, notes, failed


def _block_start(heights: list[int], index: int, title_h: int) -> int:
    return title_h + sum(heights[:index])


def _compress(window: list[int], overflow: int, min_scale: float, height, heights: list[int]) -> tuple[int, float | None]:
    """overflow 이상 높이를 줄이는 가장 약한 배율(1% 단위)을 찾는다. (줄어드는 높이, 배율) — 못 찾으면 (0, None)."""
    if not window or min_scale >= 1.0:
        return 0, None
    scale = 0.99
    while scale >= min_scale - 1e-9:
        gain = sum(heights[j] - height(j, scale) for j in window)
        if gain >= overflow:
            return gain, round(scale, 2)
        scale = round(scale - 0.01, 2)
    return 0, None


# ── 높이 어림 ───────────────────────────────────────────────────────────


def _blocks_height(doc: Document, profile: Profile,
                   layouts: dict[int, TableLayout]) -> int:
    total = 0
    if doc.title:
        total += _text_height(doc.title, profile.font("title"), profile.page.usable_width,
                              profile)
    blocks = doc.blocks
    for index, block in enumerate(blocks):
        previous = blocks[index - 1] if index else None
        following = blocks[index + 1] if index + 1 < len(blocks) else None
        total += _block_height(block, profile, layouts, previous, following)
    return total


def _block_height(block: Block, profile: Profile, layouts: dict[int, TableLayout],
                  previous: Block | None = None, following: Block | None = None, *, scale: float = 1.0) -> int:
    width = profile.page.usable_width

    if isinstance(block, Heading):
        key = f"heading{block.level}"
        spec = profile.font(key if profile.has_font(key) else "body")
        return _text_height(plain(block.runs), spec, width, profile)

    if isinstance(block, Paragraph):
        return _text_height(plain(block.runs), profile.font("body"), width, profile, scale=scale)

    if isinstance(block, ListItem):
        # 렌더러(_item_spacing / _space_before)와 같은 규칙으로 간격을 더해야
        # '여유 있음' 판단이 실제와 어긋나지 않는다.
        level = profile.numbering_level(block.depth)
        spec = profile.font("body")
        indent = level.indent + (level.hanging or 0)

        same_level = isinstance(following, ListItem) and following.depth == block.depth
        up = isinstance(following, ListItem) and following.depth < block.depth
        after = (level.space_after if same_level
                 else level.level_up_space(False) if up
                 else level.level_down_space(False, profile.text.heading_like(plain(block.runs))) if isinstance(following, ListItem)
                 else level.level_change_space(False))
        before = 0
        if isinstance(previous, ListItem) and previous.depth > block.depth:
            before = level.space_before or 0
        if isinstance(previous, Table):
            before = max(before, profile.tables.space_after or 0)

        return _text_height(plain(block.runs), spec, width - indent, profile,
                            extra=(after or 0) + before, scale=scale)

    if isinstance(block, Table):
        return table_height(block, profile, layouts.get(id(block)), relaxed=False)

    if isinstance(block, CodeBlock):
        spec = profile.font("code")
        lines = len(block.text.splitlines()) or 1
        return int(lines * _line_height(spec) + (spec.space_before or 0)
                   + (spec.space_after or 0))

    if isinstance(block, Callout):
        return sum(_block_height(inner, profile, layouts) for inner in block.blocks)

    if isinstance(block, Image):
        return int(profile.page.usable_height * 0.25)  # 크기를 모를 때의 보수적 가정

    if isinstance(block, HorizontalRule):
        return _line_height(profile.font("body"))

    return 0


def table_height(table: Table, profile: Profile, layout: TableLayout | None,
                 *, relaxed: bool) -> int:
    """표 높이 어림 — 행마다 가장 많이 줄바꿈되는 셀이 행 높이를 정한다."""
    if layout is None or not layout.col_widths:
        return 0
    spec = profile.font("table")
    line_height = _line_height(spec.resized(layout.font_size))
    padding = profile.tables.cell_margin_y * 2
    floor = profile.tables.min_row_height(relaxed) or 0

    lines_per_row = [1] * len(table.rows)
    for row_index, row in enumerate(table.rows):
        lines_per_row[row_index] = max(
            (_cell_line_count(cell, profile, layout, col, span)
             for cell, col, span, r in _grid_with_row(table) if r == row_index),
            default=1,
        )
    total = 0
    for lines in lines_per_row:
        total += max(int(lines * line_height + padding), floor)
    caption = _text_height(table.caption, profile.font("caption"),
                           profile.page.usable_width, profile) if table.caption else 0
    notes = sum(_text_height(plain(runs), profile.font("table_note"),
                             profile.page.usable_width, profile) for runs in table.notes)
    return total + caption + notes


def _grid_with_row(table: Table):
    """(iter_grid와 같되 행 번호를 함께 돌려준다)."""
    row_of: list[tuple] = []
    occupied: set[tuple[int, int]] = set()
    for r, row in enumerate(table.rows):
        col = 0
        for cell in row.cells:
            while (r, col) in occupied:
                col += 1
            for rr in range(r, r + cell.rowspan):
                for cc in range(col, col + cell.colspan):
                    occupied.add((rr, cc))
            row_of.append((cell, col, cell.colspan, r))
            col += cell.colspan
    return row_of


def _cell_line_count(cell, profile: Profile, layout: TableLayout,
                     col: int, span: int) -> int:
    widths = layout.col_widths
    if col >= len(widths):
        return 1
    width = sum(widths[col : min(col + span, len(widths))]) - layout.cell_margin_x * 2
    spec = profile.font("table_header" if cell.is_header else "table")
    measurer = TextMeasurer(spec.east_asia, spec.latin, layout.font_size,
                            bold=bool(spec.bold), scale=layout.char_scale)
    return max((measurer.wrap_count(line, width) for line in cell_lines(cell)), default=1)


def _text_height(text: str, spec: FontSpec, width: int, profile: Profile,
                 *, extra: int = 0, scale: float = 1.0) -> int:
    if width <= 0:
        return 0
    measurer = TextMeasurer(spec.east_asia, spec.latin, spec.size, bold=bool(spec.bold))
    lines = measurer.wrap_count(text or "", width)
    return int(lines * _line_height(spec) * scale + (spec.space_before or 0)
               + (spec.space_after or 0) + extra)


def _line_height(spec: FontSpec) -> float:
    return spec.size * (spec.line_spacing or 1.0) * SINGLE_LINE_FACTOR


# ── 넉넉하게 쓸 경우 늘어나는 높이 ──────────────────────────────────────


def _extra_if_relaxed(doc: Document, profile: Profile,
                      layouts: dict[int, TableLayout]) -> int:
    """간격과 행 높이를 넉넉한 값으로 바꿨을 때 늘어나는 총 높이."""
    blocks = doc.blocks
    return sum(_extra_for_block(block, blocks[index + 1] if index + 1 < len(blocks) else None, profile, layouts)
               for index, block in enumerate(blocks))


def _extra_for_block(block: Block, following: Block | None, profile: Profile, layouts: dict[int, TableLayout]) -> int:
    """블록 하나가 넉넉한 값에서 늘어나는 높이."""
    extra = 0
    if isinstance(block, ListItem):
        # 단계가 바뀌는 자리에서만 간격이 늘어난다 (같은 단계가 이어지면 그대로).
        if isinstance(following, ListItem) and following.depth == block.depth:
            return 0
        level = profile.numbering_level(block.depth)
        if isinstance(following, ListItem) and following.depth < block.depth:
            until = profile.text.level_up_relaxed_until
            gap = ((level.level_up_space(True, following.depth, until) or 0)
                   - (level.level_up_space(False, following.depth, until) or 0))
        elif isinstance(following, ListItem):
            heading = profile.text.heading_like(plain(block.runs))
            gap = (level.level_down_space(True, heading) or 0) - (level.level_down_space(False, heading) or 0)
        else:
            gap = (level.level_change_space(True) or 0) - (level.level_change_space(False) or 0)
        extra += max(0, gap)
    elif isinstance(block, Table):
        layout = layouts.get(id(block))
        if layout is not None:
            extra += max(0, table_height(block, profile, layout, relaxed=True)
                         - table_height(block, profile, layout, relaxed=False))
    return extra
