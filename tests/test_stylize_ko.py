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


@pytest.mark.parametrize(
    "before,after",
    [
        # 사용자가 준 예시 (2026-09-28)
        ("인덱스를 재설계하였습니다.", "인덱스 재설계"),
        ("모니터링 체계를 보강할 예정입니다.", "모니터링 체계 보강 예정"),
        ("응답 지연 문제가 지속적으로 발생하였습니다.", "응답 지연 문제 지속 발생"),
        # 같은 규칙의 다른 모양
        ("주요 지표가 개선되었습니다.", "주요 지표 개선"),
        ("사용하지 않는 인덱스 8개를 제거했습니다.", "사용하지 않는 인덱스 8개 제거"),
        ("측정 기준은 운영 로그입니다.", "측정 기준은 운영 로그"),
        ("미흡 사항은 4분기 과제로 이관합니다.", "미흡 사항은 4분기 과제로 이관"),
        ("추가 검토를 해야 합니다.", "추가 검토를 해야 함"),
        ("요구사항을 반영해야 합니다.", "요구사항 반영 필요"),
        ("현재 진행 중입니다.", "현재 진행 중"),
        # 명사로 못 끝내면 "~음"으로, 마침표 없이
        ("반복 조회를 줄였습니다.", "반복 조회를 줄였음"),
    ],
)
def test_noun_endings(before, after):
    assert Gaechosik(noun_ending=True).convert(before) == after


@pytest.mark.parametrize(
    "before,after",
    [
        ("주가 변동을 분석합니다.", "주가 변동 분석"),   # '주가'의 '가'는 조사가 아님
        ("업무 사이 공백을 조정합니다.", "업무 사이 공백 조정"),
        ("그렇게 말했습니다.", "그렇게 말하였음"),      # '말'(한 글자)은 명사로 끝내지 않음
    ],
)
def test_noun_endings_do_not_mangle_words(before, after):
    assert Gaechosik(noun_ending=True).convert(before) == after


def test_headings_and_nouns_are_left_alone(engine):
    assert engine.convert("추진 배경") == "추진 배경"
    assert engine.convert("관련 부서 등") == "관련 부서 등"


@pytest.mark.parametrize(
    "before,after",
    [
        # 사용자가 준 예시 (2026-09-28): 제목도 명사로 끝나야 함
        ("추진 배경임", "추진 배경"),
        ("개선 결과이다", "개선 결과"),
        ("향후 계획입니다", "향후 계획"),
    ],
)
def test_heading_noun_ending(before, after):
    assert Gaechosik(noun_ending=True).heading_noun_ending(before) == after


def test_heading_that_is_already_a_noun_phrase_is_unchanged():
    engine = Gaechosik(noun_ending=True)
    assert engine.heading_noun_ending("추진 배경") == "추진 배경"
    assert engine.changes == []  # 안 바뀐 건 --report에도 안 남아야 한다


def test_heading_noun_ending_is_a_noop_without_the_profile_flag():
    """text.noun_ending이 꺼져 있으면(기존 프로파일 등) 제목도 건드리지 않는다."""
    engine = Gaechosik(noun_ending=False)
    assert engine.heading_noun_ending("추진 배경임") == "추진 배경임"


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
