"""한 문장을 몇 줄로, 어디서 나눌지 정한다 — 정식보고서의 손으로 맞춘 줄 모양.

정식보고서는 줄이 길면 글쓴이가 **엔터로 줄을 나누고 왼쪽 끝을 윗줄 글자에 맞춘다.** 줄이 아슬아슬하게
넘칠 때는 글자 간격을 0.1~0.5pt 좁혀 줄 바뀜을 막는다(2026-10-01 사용자 — "아주 많음"). 이 모듈은
그 판단만 한다: 글자별 폭 목록을 받아 줄 범위와 좁힐 양을 돌려준다(글꼴·문서 구조는 모른다).

규칙:
- 줄은 어절(공백) 경계에서만 나눈다. 한 어절이 한 줄보다 길면 글자 단위로 끊는다.
- 한 줄이 넘치는 양을 글자 수로 나눈 값이 `max_condense` 이하면 나누지 않고 좁힌다
  (좁히는 양은 `step`의 배수로 올림). 그보다 넘치면 앞 어절까지만 한 줄로 쓴다.
- `margin`만큼 폭을 덜 쓴다 — 글꼴 폭 측정이 Word와 조금 달라도 Word가 다시 줄을 바꾸지 않게.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Line:
    start: int          # 글자 목록 안 시작 위치
    end: int            # 끝 위치(미포함, 뒤쪽 공백 제외)
    steps: int = 0      # 글자 간격을 step의 몇 배만큼 좁혔는지(0 = 안 좁힘)
    need: float = 0.0   # 다음 어절까지 한 줄에 넣으려면 글자마다 좁혀야 했던 양(0 = 어절이 남지 않았거나 끊은 이유가 다름)


def fit_text(text: str, widths: list[float], *, first_room: float, cont_room: float,
             max_condense: float = 0.0, step: float = 0.0, margin: float = 0.0) -> list[Line]:
    """text를 줄로 나눈다. widths[i]는 text[i]의 폭, room은 글자가 쓸 수 있는 줄 폭(같은 단위)."""
    lines: list[Line] = []
    n = len(text)
    pos = 0
    while pos < n:
        while pos < n and text[pos] == " ":
            pos += 1  # 줄 앞의 공백은 버린다 (줄 나눔 자리의 공백)
        if pos >= n:
            break
        room = max((cont_room if lines else first_room) * (1.0 - margin), min(widths[pos:pos + 1] or [1.0]))
        best: Line | None = None
        need = 0.0
        total = 0.0
        j = pos
        while j < n:
            total += widths[j]
            j += 1
            if j < n and text[j] != " ":
                continue  # 어절 중간 — 줄을 끝낼 수 없다
            count = j - pos
            overflow = total - room
            if overflow <= 1e-6:
                best = Line(pos, j)
            elif max_condense > 0 and step > 0 and overflow <= max_condense * count:
                best = Line(pos, j, max(1, math.ceil(overflow / count / step - 1e-9)))
            else:
                need = overflow / count
                break
        if best is not None and need:
            best = Line(best.start, best.end, best.steps, need)
        if best is None:  # 첫 어절부터 한 줄에 안 들어간다 — 글자 단위로 끊는다
            end, total = pos, 0.0
            while end < n and (end == pos or total + widths[end] <= room):
                total += widths[end]
                end += 1
            best = Line(pos, end)
        lines.append(best)
        pos = best.end
    return lines
