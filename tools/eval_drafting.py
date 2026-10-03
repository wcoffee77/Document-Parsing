"""줄글 → 보고서 다듬기를 샘플 5건 전부에 돌려 정답과 비교한다(온프렘 LLM 필요).

    uv run python tools/eval_drafting.py [--out out] [--holdout]

--holdout: 건마다 그 건의 정답에서 뽑은 변환 예시(rules/report_style.yaml)를 지시문에서 빼고 돌린다 — 예시를 베낀 것인지
가리는 공정한 채점. 안 주면 모든 예시를 쓴다(실제 사용과 같음). 결과 글은 out/eval_N_구조.txt, 리포트는 out/eval_N.md.
원문 글자는 화면에 안 나온다(수치·개수만) — 결과를 그대로 복사해 보내도 된다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import score_drafting  # noqa: E402

from doc2report.account import load_and_apply  # noqa: E402
from doc2report.drafting import draft  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="out")
    parser.add_argument("--holdout", action="store_true")
    parser.add_argument("--only", type=int, nargs="*", help="번호만 (예: --only 2 4)")
    args = parser.parse_args()
    load_and_apply()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for number in args.only or range(1, 6):
        source = next(score_drafting.SAMPLES.glob(f"줄글_{number}_*.txt"))
        result = draft(source.read_text(encoding="utf-8"), year=2026,
                       holdout={number} if args.holdout else None)
        target = out / f"eval_{number}_구조.txt"
        target.write_text(result.text, encoding="utf-8")
        (out / f"eval_{number}.md").write_text("\n".join(f"- {n}" for n in result.notes), encoding="utf-8")
        print(f"[{number}] 방식 {result.mode}, 판단 {len(result.notes)}건 → {target}")
        score_drafting.score(target, number)
        for note in result.notes:
            if any(k in note for k in ("대체", "교정", "검증 실패", "형식 오류", "호출 실패")):
                print(f"    · {note[:90]}")


if __name__ == "__main__":
    main()
