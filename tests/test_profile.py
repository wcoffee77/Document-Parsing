"""프로파일 해석과 역추출."""

from __future__ import annotations

from pathlib import Path

import pytest

from doc2report.pipeline import convert
from doc2report.profile import load_profile
from doc2report.profile_init import profile_from_docx
from doc2report.units import emu_to_mm, emu_to_pt, parse_length

FIXTURE = Path(__file__).parent / "fixtures" / "sample_report.md"


def test_units_are_parsed_once_not_twice():
    """상속·병합 과정에서 단위가 두 번 변환되면 문서가 깨진다 (실제로 겪은 버그).

    YAML에 적힌 문자열을 직접 파싱한 값과 프로파일이 들고 있는 값이 같아야 한다.
    """
    import yaml

    from doc2report.profile import PROFILE_DIR

    raw = yaml.safe_load((PROFILE_DIR / "default.yaml").read_text(encoding="utf-8"))
    profile = load_profile("default")

    assert profile.font("body").size == parse_length(raw["fonts"]["body"]["size"])
    assert profile.page.margin.top == parse_length(raw["page"]["margin"]["top"])
    # 상속받은 서식도 한 번만 변환되어야 한다 (callout은 size를 직접 적지 않음)
    assert profile.font("callout").size == parse_length(
        raw["fonts"].get("callout", {}).get("size", raw["fonts"]["body"]["size"]))
    assert 5 <= emu_to_pt(profile.font("body").size) <= 30
    assert 5 <= emu_to_mm(profile.page.margin.left) <= 60


def test_dump_profile_round_trips(tmp_path):
    """profile show / --save-profile 결과를 다시 읽을 수 있어야 한다."""
    from doc2report.profile import dump_profile

    original = load_profile("default")
    path = tmp_path / "dumped.yaml"
    path.write_text(dump_profile(original), encoding="utf-8")
    again = load_profile(path)

    assert again.font("body").size == original.font("body").size
    assert again.page.margin.top == original.page.margin.top
    assert [level.indent for level in again.numbering] == \
           [level.indent for level in original.numbering]
    assert again.tables.font_ladder == original.tables.font_ladder


def test_inherited_values_come_from_body():
    profile = load_profile("default")
    body, heading = profile.font("body"), profile.font("heading1")
    assert heading.east_asia == body.east_asia  # heading1에 글꼴을 안 적었으므로 상속
    assert heading.size != body.size


def test_usable_width_excludes_margins():
    profile = load_profile("default")
    expected = profile.page.width - profile.page.margin.left - profile.page.margin.right
    assert profile.page.usable_width == expected
    assert emu_to_mm(profile.page.usable_width) == pytest.approx(170, abs=0.1)


def test_landscape_swaps_dimensions():
    page = load_profile("default").page
    wide = page.landscape()
    assert wide.width == page.height and wide.height == page.width
    assert wide.usable_width > page.usable_width


def test_numbering_level_falls_back_to_deepest():
    profile = load_profile("default")
    deepest = profile.numbering[-1]
    assert profile.numbering_level(99) is deepest


def test_profile_init_round_trips(tmp_path):
    """생성한 문서에서 프로파일을 뽑아내면 다시 읽혀야 한다."""
    docx = tmp_path / "report.docx"
    convert(str(FIXTURE), docx, "default")

    yaml_path = tmp_path / "extracted.yaml"
    yaml_path.write_text(profile_from_docx(docx), encoding="utf-8")

    extracted = load_profile(yaml_path)
    original = load_profile("default")
    assert extracted.font("body").east_asia == original.font("body").east_asia
    assert extracted.font("body").size == pytest.approx(original.font("body").size, rel=0.01)
    assert extracted.page.margin.left == pytest.approx(
        original.page.margin.left, abs=parse_length("0.5mm")
    )


def test_confluence_profile_extends_default_with_dense_sizes():
    """Confluence 변환 서식(2026-09-29 사용자 두 번째 확정): 제목 18pt, 본문 12pt·장평 95%·
    줄간격 1.0·단락 앞뒤 0pt, 표 10pt·장평 80% 고정, 문장 다듬기 없음."""
    conf, default = load_profile("confluence"), load_profile("default")
    assert emu_to_pt(conf.font("title").size) == 18
    assert conf.font("title").char_scale == 1.0  # 본문 장평을 물려받지 않음
    body = conf.font("body")
    assert (emu_to_pt(body.size), body.char_scale, body.line_spacing) == (12, 0.95, 1.0)
    assert body.space_before == body.space_after == 0
    assert conf.table_steps() == [(10 * 12700, 0.8)]  # 10pt·80% 하나 — 더 줄이지 않는다
    assert conf.text.polish == "none"
    assert conf.text.keep_leading_markers
    # 덮어쓰지 않은 값(머리글 여백·표 음영·말머리 기호·들여쓰기)은 부모 그대로 — 단위가 두 번 변환되지도 않는다.
    assert conf.page.margin.header == default.page.margin.header
    assert conf.tables.header_shading == default.tables.header_shading
    assert [(l.marker, l.aliases) for l in conf.numbering[:4]] == [(l.marker, l.aliases) for l in default.numbering]
    # numbering_all: 모든 단계의 단락 앞뒤·단계 전환 간격 0
    assert all(l.space_before == l.space_after == l.space_after_level_change == 0
               for l in conf.numbering)
    assert any(l.space_before for l in default.numbering)  # default는 그대로


def test_extends_cycle_is_reported(tmp_path):
    a, b = tmp_path / "a.yaml", tmp_path / "b.yaml"
    a.write_text("extends: b.yaml\n", encoding="utf-8")
    b.write_text("extends: a.yaml\n", encoding="utf-8")
    with pytest.raises(ValueError, match="순환"):
        load_profile(a)
