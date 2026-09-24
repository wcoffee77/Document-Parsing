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
