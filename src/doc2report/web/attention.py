"""작업 메모 → 사용자가 꼭 알아야 할 것만 쉬운 말로 (2026-10-12 사용자).

변환·AI 작성 중에는 메모(`notes`)가 수십 줄 쌓이지만 대부분은 개발자용 진단이다(글꼴 폭 모델, 표 위치 수치, 구조 보정…).
사용자가 알아야 하는 것은 **내용이 바뀌었을 수 있거나 빠졌을 수 있는 경우**뿐이라, 그것만 골라 한두 줄로 보인다.
나머지는 작업 기록 파일에 그대로 남는다(지우지 않는다 — 조용히 바꾸지 않는다는 원칙 4).

분류 순서: ① 알려 줄 것(`_RULES`) → ② 알려진 참고(`_BENIGN`) → ③ 나머지 중 실패·누락을 뜻하는 말이 든 것은
"기타 확인"으로 **숨기지 않고** 보인다(새 메모 유형이 생겨도 중요한 것이 묻히지 않게).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_PREFIX = re.compile(r"^\[(?:요약|종합)\]\s*")


@dataclass(frozen=True)
class Rule:
    key: str
    pattern: re.Pattern
    level: str       # bad = 결과를 믿기 어려움, warn = 확인 권장
    one: str         # 1건일 때 문장 ({n} 없음)
    many: str        # 여러 건일 때 문장 ({n} = 건수)


def _r(key: str, pattern: str, level: str, one: str, many: str | None = None) -> Rule:
    return Rule(key, re.compile(pattern), level, one, many or one)


_RULES: tuple[Rule, ...] = (
    _r("ai_failed", r"실패해 원문 문장을 그대로 늘어놓|^규칙 기본 구조 사용", "bad",
       "AI 정리에 실패해 원문 문장을 그대로 늘어놓았습니다 — 요약·재구성이 아니므로 내용을 직접 확인해 주세요."),
    _r("ai_call", r"LLM 호출 실패", "warn",
       "AI(LLM) 호출에 실패한 곳이 있습니다 — 연결 상태를 확인하고 다시 만들어 보세요."),
    _r("reverted", r"사실 검증 실패 → 원문 문장으로 대체", "warn",
       "AI가 바꾼 문장 중 사실이 달라질 우려가 있어 원문 문장으로 되돌린 곳이 있습니다.",
       "AI가 바꾼 문장 중 사실이 달라질 우려가 있어 원문 문장으로 되돌린 곳이 {n}곳 있습니다."),
    _r("numbers", r"^수치 누락\(", "warn",
       "원문의 수치가 보고서에 빠졌을 수 있습니다 — 원문과 대조해 주세요.",
       "원문의 수치가 보고서에 빠졌을 수 있습니다({n}건) — 원문과 대조해 주세요."),
    _r("unused_numbers", r"^보고서에 안 나온 원문 수치", "warn",
       "보고서에 쓰이지 않은 원문 수치가 있습니다 — 필요한 수치인지 확인해 주세요."),
    _r("unclear", r"이해 불가 의심|내용 누락 의심|줄임말 남음", "warn",
       "읽어서 이해가 어렵거나 내용이 빠졌을 수 있는 곳이 있습니다 — 보고서를 한 번 읽어 확인해 주세요.",
       "읽어서 이해가 어렵거나 내용이 빠졌을 수 있는 곳이 {n}곳 있습니다 — 보고서를 한 번 읽어 확인해 주세요."),
    _r("unloaded", r"불러오지 못함|불러오지 않음|내려받기 실패|를 읽지 못함|읽지 못함:|대체 시도도 실패", "warn",
       "Confluence 연결 페이지·첨부 중 불러오지 못한 것이 있습니다 — 내용이 빠졌을 수 있습니다.",
       "Confluence 연결 페이지·첨부 중 불러오지 못한 것이 {n}건 있습니다 — 내용이 빠졌을 수 있습니다."),
    _r("image", r"이미지를 찾을 수 없어 건너뜀|이미지 삽입 실패", "warn",
       "이미지 1개를 넣지 못했습니다.", "이미지 {n}개를 넣지 못했습니다."),
    _r("pdf", r"PDF 만들기 실패", "warn", "PDF 변환에 실패해 Word 문서만 저장했습니다."),
    _r("empty", r"변환할 내용이 없습니다", "bad", "변환할 내용이 없습니다 — 입력이 비었거나 공백뿐입니다."),
    _r("table_split", r"한 쪽보다 커서 쪽 사이 잘림을 막지 못함", "warn",
       "한 쪽보다 큰 표가 있어 쪽 사이에서 나뉩니다 — Word에서 확인해 주세요."),
    _r("table_squeeze", r"최소 폭을 맞출 수 없어 비례 축소", "warn",
       "일부 표는 칸이 좁아 줄바꿈이 많아졌습니다 — Word에서 표를 확인해 주세요."),
    _r("no_font", r"을\(를\) 찾지 못해 줄 맞춤", "warn",
       "필요한 글꼴을 찾지 못해 줄 맞춤(글자 간격·줄 나눔)을 적용하지 못했습니다."),
)

# 알려진 참고용 메모(성공했거나 자동 보정한 것) — 작업 기록에만 남긴다.
_BENIGN = re.compile(
    r"^(?:자동 판단|구조 보정|규칙 교정|변화 표기 보정|날짜 표기 정리|날짜에 요일|글꼴\(|표 \d+ ?[:위]|표 글자 크기|표 장평|표 안 칸|"
    r"셀 여백|열 \d+|참고 열|가로 방향|연결 페이지 .*함께 불러옴|첨부 Word 파일 .*넣음|첨부 파일 .*이름만 남김|사내 CA|"
    r"여러 번 실행|LLM 다듬기|LLM 구조 응답|줄 맞춤|표현 줄임|쪽 제목|중복 말머리|빈 항목|요지 폐기|내용 누락 보강|"
    r"이해 불가 줄 풀어|수치 누락 (?:원문 어구로|줄 단위) 보강|생략한 원문 문장|\d+쪽이 약|지면에|넉넉한 간격|주석 \d+개|"
    r"두세 글자|제목:|제목 검증|절 제목이|형식 보정|검증:|httpx|.*은\(는\) 이미 넣었으므로|.*에서 책갈피 .*찾지 못해|"
    r"한 쪽에 넣으려고|표 \d+: |LLM \S+ ?응답|내용 검수 건너뜀)"
)
_FAILURE_WORDS = re.compile(r"실패|오류|못했|못함|불러오지|누락|의심|찾을 수 없")


def classify(notes: list[str]) -> tuple[list[dict], int]:
    """notes → (사용자에게 보일 항목 [{level, text}], 작업 기록에만 남는 메모 수)."""
    counts: dict[str, int] = {}
    order: list[Rule] = []
    others: list[str] = []
    hidden = 0
    for raw in notes:
        note = _PREFIX.sub("", raw).strip()
        if not note:
            continue
        rule = next((r for r in _RULES if r.pattern.search(note)), None)
        if rule:
            if rule.key not in counts:
                order.append(rule)
            counts[rule.key] = counts.get(rule.key, 0) + 1
        elif _BENIGN.search(note) or not _FAILURE_WORDS.search(note):
            hidden += 1
        else:
            others.append(note)
    items = [{"level": r.level,
              "text": (r.many if counts[r.key] > 1 else r.one).format(n=counts[r.key])} for r in order]
    for note in others[:3]:
        items.append({"level": "warn", "text": f"기타 확인: {note[:90]}"})
    if len(others) > 3:
        items.append({"level": "warn", "text": f"기타 확인할 것이 {len(others) - 3}건 더 있습니다 — 작업 기록을 보세요."})
    # 심각한 것이 앞에
    items.sort(key=lambda i: 0 if i["level"] == "bad" else 1)
    return items, hidden
