"""표 맞춤 엔진 — 경계 조건 위주."""

from __future__ import annotations

import pytest

from doc2report.ir import Cell, Paragraph, Row, Run, Table
from doc2report.layout.table_fit import column_demands, fit_table
from doc2report.profile import load_profile


def cell(text: str, *, header: bool = False, colspan: int = 1) -> Cell:
    return Cell(blocks=[Paragraph(runs=[Run(text)])], is_header=header, colspan=colspan)


def table_of(rows: list[list[str]], header: bool = True) -> Table:
    out = []
    for index, row in enumerate(rows):
        out.append(Row(cells=[cell(text, header=header and index == 0) for text in row]))
    return Table(rows=out, header_rows=1 if header else 0)


@pytest.fixture
def profile():
    return load_profile("default")


def test_narrow_table_is_stretched_to_available_width(profile):
    table = table_of([["구분", "값"], ["가", "1"]])
    layout = fit_table(table, profile, profile.page.usable_width)
    assert layout.total_width <= profile.page.usable_width
    # 여유가 있으면 표는 사용가능폭을 채운다 (보고서 관례)
    assert layout.total_width > profile.page.usable_width * 0.9
    assert layout.font_size == profile.table_font_ladder()[0]


def test_wide_table_shrinks_font_before_giving_up(profile):
    long = "매우 긴 설명이 들어가는 칸으로 한 줄에 다 들어가지 않는다"
    table = table_of([[f"항목{i}" for i in range(8)], [long] * 8])
    layout = fit_table(table, profile, profile.page.usable_width)
    assert layout.total_width <= profile.page.usable_width
    assert layout.font_size <= profile.table_font_ladder()[0]


def test_never_exceeds_available_width_even_when_impossible(profile):
    """한 칸에 끊을 수 없는 긴 영문이 있어 최소 폭조차 넘치는 경우."""
    table = table_of([["A"] * 12, ["Supercalifragilisticexpialidocious" * 2] * 12])
    layout = fit_table(table, profile, profile.page.usable_width)
    assert layout.total_width <= profile.page.usable_width
    assert layout.overflow is True
    assert layout.notes  # 무슨 조정을 했는지 사람에게 알린다


def test_column_demands_min_is_not_greater_than_max(profile):
    table = table_of([["구분", "내용"], ["가나다", "긴 문장이 들어간 칸 hello world"]])
    mins, maxs = column_demands(table, profile, profile.font("table").size)
    assert len(mins) == len(maxs) == 2
    assert all(mn <= mx for mn, mx in zip(mins, maxs))


def test_colspan_demand_is_spread_over_covered_columns(profile):
    wide = Row(cells=[cell("아주 긴 제목이 두 칸에 걸쳐 있음", colspan=2)])
    narrow = Row(cells=[cell("가"), cell("나")])
    table = Table(rows=[wide, narrow], header_rows=0)
    mins, maxs = column_demands(table, profile, profile.font("table").size)
    assert len(mins) == 2
    assert sum(maxs) > 0


def test_column_width_follows_content_not_header(profile):
    """값은 짧은데 머리만 긴 열이 넓어지지 않는다."""
    table = table_of([["구분", "개선 전 평균 응답시간과 비고 사항", "설명"],
                      ["조회", "3200ms", "인덱스 재설계 및 캐시 계층 도입으로 개선함"]])
    layout = fit_table(table, profile, profile.page.usable_width)
    short_values, long_values = layout.col_widths[1], layout.col_widths[2]
    assert short_values < long_values


def test_short_columns_are_levelled_to_similar_widths(profile):
    """남는 폭은 좁은 열부터 같은 폭이 되도록 채운다."""
    table = table_of([["가", "나", "다", "라"], ["1", "22", "333", "4"]])
    layout = fit_table(table, profile, profile.page.usable_width)
    assert max(layout.col_widths) - min(layout.col_widths) <= 2 * 635  # twips 반올림 오차


def test_cell_with_many_lines_is_left_aligned(profile):
    """내용이 max_cell_lines(기본 3)줄 이상인 셀은 가운데 정렬 대신 왼쪽 맞춤이
    낫다 — 가운데 정렬은 줄마다 들쭉날쭉해 보인다 (2026-09-29 사용자 요청)."""
    many_lines = Cell(blocks=[Paragraph(runs=[Run(f"{i}번째 줄입니다")]) for i in range(5)])
    one_line = cell("한 줄짜리 짧은 내용")
    table = Table(rows=[Row(cells=[cell("항목", header=True), cell("설명", header=True)]),
                        Row(cells=[one_line, many_lines])],
                  header_rows=1)
    layout = fit_table(table, profile, profile.page.usable_width)
    assert layout.cell_align.get((1, 0)) is None
    assert layout.cell_align.get((1, 1)) == "left"


def test_cell_with_many_short_lines_is_shrunk_without_affecting_others(profile):
    """<br>/여러 문단으로 줄이 많은 셀은 '가장 긴 한 줄'만 보는 _max_cell_lines에는
    안 걸린다(각 줄이 짧아서) — 그래서 표 전체 크기가 안 줄었다(2026-09-29
    사용자 보고). 그 셀만 따로 줄인다(다른 셀은 안 건드림) — 단, 표 전체와
    그 셀의 차이가 max_font_spread(2pt)를 넘으면 표 전체를 그만큼만 낮춘다."""
    many_lines = Cell(blocks=[Paragraph(runs=[Run(f"{i}번째 줄")]) for i in range(6)])
    one_line = cell("짧은 값")
    table = Table(rows=[Row(cells=[cell("항목", header=True), cell("설명", header=True)]),
                        Row(cells=[one_line, many_lines])],
                  header_rows=1)
    layout = fit_table(table, profile, profile.page.usable_width)
    assert (1, 0) not in layout.cell_font  # 짧은 셀은 안 건드림
    size, scale = layout.cell_font[(1, 1)]
    assert size < layout.font_size or scale < layout.char_scale
    assert layout.font_size - size <= profile.tables.max_font_spread


def test_table_font_is_lowered_to_keep_spread_within_2pt(profile):
    """표 크기 12pt, 바쁜 셀만 9pt면 차이가 3pt라 불균형해 보인다는 사용자 지적 —
    표 전체를 11pt로 낮춰 9pt와의 차이를 2pt로 좁힌다."""
    many_lines = Cell(blocks=[Paragraph(runs=[Run(f"{i}번째 줄")]) for i in range(8)])
    table = Table(rows=[Row(cells=[cell("항목", header=True), cell("설명", header=True)]),
                        Row(cells=[cell("A"), many_lines])],
                  header_rows=1)
    layout = fit_table(table, profile, profile.page.usable_width)
    assert (1, 1) in layout.cell_font
    size, _ = layout.cell_font[(1, 1)]
    assert size == min(profile.table_font_ladder())  # 바닥까지 내려간 경우
    assert layout.font_size - size == profile.tables.max_font_spread
    assert any("표 전체 크기" in note for note in layout.notes)


def test_cell_align_does_not_override_explicit_alignment(profile):
    right_cell = Cell(blocks=[Paragraph(runs=[Run(f"{i}번째 줄입니다")]) for i in range(5)],
                      align="right")
    table = Table(rows=[Row(cells=[cell("항목", header=True)]), Row(cells=[right_cell])],
                  header_rows=1)
    layout = fit_table(table, profile, profile.page.usable_width)
    assert (1, 0) not in layout.cell_align


def test_crowded_table_shrinks_font_only_and_keeps_full_char_scale(profile):
    """글씨가 많아도 장평은 100%로 두고 글자 크기만 줄인다(2026-09-29 사용자: 90%도 95%도
    보기 안 좋다). 크기는 사다리 하한(9pt)까지."""
    long = "가나다라마바사아자차카타파하 " * 3
    table = table_of([[f"열{i}" for i in range(10)], [long] * 10])
    layout = fit_table(table, profile, profile.page.usable_width)
    assert layout.char_scale == 1.0
    assert min(profile.table_font_ladder()) <= layout.font_size < max(profile.table_font_ladder())
    assert not any("장평" in note for note in layout.notes)


def test_char_scale_ladder_still_works_when_a_profile_asks_for_it(profile):
    """장평 기능 자체는 남겨 뒀다 — 프로파일이 사다리에 95%를 넣으면 쓴다."""
    tables = profile.tables.model_copy(update={"char_scale_ladder": [1.0, 0.95]})
    wide = profile.model_copy(update={"tables": tables})
    long = "가나다라마바사아자차카타파하 " * 3
    table = table_of([[f"열{i}" for i in range(10)], [long] * 10])
    layout = fit_table(table, wide, wide.page.usable_width)
    assert layout.char_scale == pytest.approx(0.95)
    assert any("장평" in note for note in layout.notes)


def test_steps_go_from_least_to_most_narrowing(profile):
    widths = [size * scale for size, scale in profile.table_steps()]
    assert widths == sorted(widths, reverse=True)


def test_long_header_over_short_values_is_abbreviated(profile):
    table = table_of([["구분", "개선 전 평균 응답시간", "개선 후 평균 응답시간", "비고"],
                      ["조회", "3200ms", "480ms", "인덱스 튜닝 예정"]])
    narrow = int(profile.page.usable_width * 0.5)
    layout = fit_table(table, profile, narrow)
    after = {before: short for before, short in layout.header_text.values()}
    assert "개선 전 평균 응답시간" in after
    assert len(after["개선 전 평균 응답시간"]) < len("개선 전 평균 응답시간")


def test_landscape_is_used_only_when_allowed(profile):
    long = "가나다라마바사아자차카타파하" * 3
    table = table_of([[f"열{i}" for i in range(10)], [long] * 10])

    portrait = fit_table(table, profile, profile.page.usable_width)
    assert portrait.landscape is False

    allowed = profile.model_copy(
        update={"tables": profile.tables.model_copy(update={"allow_landscape": True})}
    )
    wide = fit_table(table, allowed, allowed.page.usable_width)
    assert wide.total_width <= allowed.page.landscape().usable_width


def test_left_align_applies_to_whole_column_when_any_cell_is_long(profile):
    """같은 열 안에서 정렬이 섞여 보이면 안 된다 — 여러 줄인 셀이 하나라도 있으면 그
    열의 본문 셀 전부 왼쪽 맞춤(2026-09-29 사용자). 머리행은 그대로 가운데."""
    many = Cell(blocks=[Paragraph(runs=[Run(f"{i}번째 줄입니다")]) for i in range(5)])
    table = Table(rows=[Row(cells=[cell("구분", header=True), cell("내용", header=True)]),
                        Row(cells=[cell("가"), cell("짧음")]),
                        Row(cells=[cell("나"), many]),
                        Row(cells=[cell("다"), cell("짧음2")])],
                  header_rows=1)
    layout = fit_table(table, profile, profile.page.usable_width)
    assert [layout.cell_align.get((r, 1)) for r in (1, 2, 3)] == ["left"] * 3
    assert (0, 1) not in layout.cell_align  # 머리행
    assert all((r, 0) not in layout.cell_align for r in (1, 2, 3))  # 다른 열은 그대로


def test_shrunk_font_applies_to_whole_column_not_just_one_cell(profile):
    """정렬처럼 글자 크기도 열 단위 — 한 셀만 줄면 그 열의 본문 셀 전부 같은 크기,
    머리행과 다른 열은 그대로(2026-09-29 사용자)."""
    many = Cell(blocks=[Paragraph(runs=[Run(f"{i}번째 줄")]) for i in range(6)])
    table = Table(rows=[Row(cells=[cell("구분", header=True), cell("내용", header=True)]),
                        Row(cells=[cell("가"), cell("짧음")]),
                        Row(cells=[cell("나"), many]),
                        Row(cells=[cell("다"), cell("짧음2")])],
                  header_rows=1)
    layout = fit_table(table, profile, profile.page.usable_width)
    fonts = [layout.cell_font.get((r, 1)) for r in (1, 2, 3)]
    assert fonts[0] is not None and fonts[0] == fonts[1] == fonts[2]
    assert fonts[0][0] < layout.font_size
    assert all((r, 0) not in layout.cell_font for r in (1, 2, 3))  # 다른 열
    assert (0, 1) not in layout.cell_font  # 머리행
    assert any("열 2" in note for note in layout.notes)
