"""줄글 다듬기 결과(_구조.txt)를 정답(samples/drafting/정답_N_*.txt)과 비교한다.

    uv run python tools/score_drafting.py out/d1_구조.txt out/d2_구조.txt ...

파일 이름에 든 번호(d1, 줄글_1 …의 첫 숫자)로 정답을 고른다. 원문 글자는 출력하지 않는다(수치·개수만).
- 분량: 원문 대비 글자 수 비율(정답은 62~75%)
- 줄 수: 말머리별(□ - ∙ ① → ※ * 표)
- 수치: 정답에 나온 원문 수치 중 결과에도 나온 비율, 결과에만 있는 숫자(원문에 없으면 사실 검증이 막았어야 함)
- 절: 정답의 □·1. 제목과 같은 말을 쓴 비율(낱말 겹침)
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples" / "drafting"
sys.path.insert(0, str(ROOT / "src"))

from doc2report.transform.factcheck import _NUM, _clean, _norm  # noqa: E402
from doc2report.transform.report_style import lint  # noqa: E402

_MARK = re.compile(r"^\s*(\d+\.|□|-|∙|·|→|※|\*|[①-⑳])")


def _chars(text: str) -> int:
    return len(re.sub(r"\s", "", text))


def _marks(lines: list[str]) -> Counter:
    counter: Counter = Counter()
    for line in lines:
        if "\t" in line:
            counter["표 행"] += 1
            continue
        m = _MARK.match(line)
        if m:
            mark = m.group(1)
            counter["①" if re.match(r"[①-⑳]", mark) else "1." if mark[0].isdigit() else mark] += 1
    return counter


def _numbers(text: str) -> set[str]:
    return {_norm(n) for n in re.findall(_NUM, _clean(text))}


def _heads(lines: list[str]) -> list[str]:
    out = []
    for line in lines:
        m = re.match(r"^\s*(?:\d+\.|□)\s*(.+)$", line)
        if m:
            out.append(re.sub(r"\s*:.*$", "", m.group(1)).replace(" ", ""))
    return out


def _items(lines: list[str]) -> list[str]:
    """항목(논리 줄) 목록 — 엔터로 나눈 둘째 줄은 윗줄에 합친다. 표 행은 뺀다."""
    items: list[str] = []
    for line in lines:
        if "\t" in line:
            continue
        if _MARK.match(line) or not items:
            items.append(_MARK.sub("", line, 1).strip())
        else:
            items[-1] += " " + line.strip()
    return items


def _style(items: list[str]) -> str:
    import statistics

    if not items:
        return "항목 없음"
    hard = sum(1 for t in items if any(i.hard for i in lint(t)))
    soft = sum(1 for t in items if lint(t) and not any(i.hard for i in lint(t)))
    widths = [_chars(t) for t in items]
    return (f"항목 {len(items)}개: 서술체·구어체(필수) {hard}, 길이·연결어미(약함) {soft}, "
            f"글자 수 중앙값 {statistics.median(widths):.0f} / 최대 {max(widths)}")


def score(result: Path, number: int) -> None:
    source = next(SAMPLES.glob(f"줄글_{number}_*.txt")).read_text(encoding="utf-8")
    answer = [l for l in next(SAMPLES.glob(f"정답_{number}_*.txt")).read_text(encoding="utf-8").splitlines()[2:]
              if l.strip() and l.replace(" ", "") != "-이상-"]
    mine = [l for l in result.read_text(encoding="utf-8").splitlines() if l.strip()]
    body_src = source.split("\n", 1)[1]
    a_text, m_text = "\n".join(answer), "\n".join(mine)
    print(f"== {result.name} (정답 {number})")
    print(f"  분량: 결과 {_chars(m_text) / _chars(body_src):.0%} / 정답 {_chars(a_text) / _chars(body_src):.0%}")
    am, mm = _marks(answer), _marks(mine)
    keys = sorted(set(am) | set(mm))
    print("  줄 수(결과/정답): " + ", ".join(f"{k} {mm.get(k, 0)}/{am.get(k, 0)}" for k in keys))
    src_n, a_n, m_n = _numbers(body_src), _numbers(a_text), _numbers(m_text)
    kept = (a_n & src_n)
    print(f"  수치: 정답이 쓴 원문 수치 {len(kept)}개 중 결과에도 {len(kept & m_n)}개"
          f" / 결과에만 있고 원문에 없는 숫자 {sorted(m_n - src_n - a_n) or '없음'}")
    print(f"  문체(결과): {_style(_items(mine))}")
    print(f"  문체(정답): {_style(_items(answer))}")
    ah, mh = _heads(answer), _heads(mine)
    hit = sum(1 for h in ah if any(h in x or x in h for x in mh))
    print(f"  절·□ 제목: 정답 {len(ah)}개 중 같은 말 {hit}개")


def main() -> None:
    files = [Path(p) for p in sys.argv[1:]]
    if not files:
        print(__doc__)
        return
    for path in files:
        found = re.search(r"(\d)", path.stem)
        if not found:
            print(f"번호를 못 찾음: {path}")
            continue
        score(path, int(found.group(1)))


if __name__ == "__main__":
    main()
