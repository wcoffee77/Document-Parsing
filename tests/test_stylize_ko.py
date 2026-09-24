"""개조식 변환과 표기 통일."""

from __future__ import annotations

import pytest

from doc2report.transform.notation import Notation
from doc2report.transform.stylize_ko import Gaechosik, nominalize


@pytest.fixture
def engine():
    return Gaechosik()


@pytest.mark.parametrize(
    "before,after",
    [
        ("검토하였습니다.", "검토하였음."),
        ("검토했습니다.", "검토하였음."),
        ("추진합니다.", "추진함."),
        ("담당자는 홍길동입니다.", "담당자는 홍길동임."),
        ("문제가 없습니다.", "문제가 없음."),
        ("개선이 필요하다.", "개선이 필요함."),
        ("일정을 조정한다.", "일정을 조정함."),
        ("확인 부탁드립니다.", "확인 요망"),
    ],
)
def test_endings(engine, before, after):
    assert engine.convert(before) == after


def test_headings_and_nouns_are_left_alone(engine):
    assert engine.convert("추진 배경") == "추진 배경"
    assert engine.convert("관련 부서 등") == "관련 부서 등"


def test_nominalize_uses_jamo_rules():
    assert nominalize("진행하") == "진행함"       # 받침 없음 → ㅁ
    assert nominalize("확인되") == "확인됨"
    assert nominalize("먹") == "먹음"             # 받침 있음 → 음
    assert nominalize("만들") == "만듦"           # ㄹ → ㄻ


def test_date_is_not_a_sentence_boundary(engine):
    text = "측정 기준은 2026. 9. 1.부터의 로그입니다."
    assert engine.split_long(text, 60) == [text]


def test_long_sentence_splits_at_connective(engine):
    text = ("인덱스를 재설계하고, 캐시 계층을 도입하여 응답 시간을 크게 줄였으며 "
            "추가 과제를 다음 분기로 이관하였습니다.")
    parts = engine.split_long(text, 40)
    assert len(parts) > 1


def test_notation_normalizes_dates_and_numbers():
    notation = Notation()
    assert "2026. 7. 15." in notation.apply("기준일은 2026-07-15 입니다")
    assert "12,000건" in notation.apply("총 12000건 처리")
    # 연도에는 쉼표가 붙지 않아야 한다
    assert notation.apply("2026년 목표") == "2026년 목표"


def test_notation_strips_confluence_residue():
    notation = Notation()
    assert "Unknown macro" not in notation.apply("표 참고 Unknown macro: {toc}")
