"""표 머리 축약 규칙 (rules/abbreviations.yaml)."""

from __future__ import annotations

from doc2report.transform.abbreviate import Abbreviator


def test_candidates_get_shorter_step_by_step():
    abbr = Abbreviator.load()
    candidates = abbr.candidates("소요 예산(단위: 천원)")
    assert candidates[0] == "소요 예산"
    assert "예산" in candidates


def test_keep_before_and_drop_words():
    abbr = Abbreviator.load()
    assert "비고" in abbr.candidates("비고 및 향후 조치 계획")


def test_shared_suffix_with_neighbours_is_dropped():
    abbr = Abbreviator.load()
    row = ["구분", "개선 전 평균 응답시간", "개선 후 평균 응답시간"]
    assert "개선 전" in abbr.candidates("개선 전 평균 응답시간", row)


def test_nothing_to_abbreviate():
    assert Abbreviator.load().candidates("구분") == []
