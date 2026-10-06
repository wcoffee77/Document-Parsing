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


def _kind(reason: str) -> str:
    for key, label in (("숫자", "수치"), ("금액", "수치"), ("비율", "수치"), ("날짜", "수치"), ("요일", "수치"),
                       ("방향", "방향"), ("가능성", "가능성"), ("범위", "범위"), ("한자", "표기"), ("영문", "표기"),
                       ("확정", "확정"), ("다른 뜻", "다른 뜻")):
        if key in reason:
            return label
    return "기타"


def _brief(number: int, result, scored: dict) -> str:
    """한 건 요약(원문 글자 없이 개수·유형만)."""
    import re

    notes = result.notes
    fmt = sum(1 for n in notes if "형식 오류" in n)
    fixed = sum(1 for n in notes if "줄 단위 다시 쓰기로 해결" in n)
    replaced = [n for n in notes if "원문 문장으로 대체" in n]
    kinds = sorted({_kind(m.group(1)) for n in replaced for m in [re.search(r"개조식, (.*?)\): ", n)] if m})
    ruled = sum(1 for n in notes if n.startswith("규칙 교정"))
    dropped = [m.group(1) for n in notes for m in [re.match(r"생략한 원문 문장 \[(\d+)\]", n)] if m]
    gaps = [n.split("—")[0].replace("수치 누락(인용한 문장 ", "").replace(" 기준):", "").strip()
            for n in notes if n.startswith("수치 누락(")]
    audit_ok = sum(1 for n in notes if n.startswith("내용 누락 보강"))
    audit_bad = sum(1 for n in notes if n.startswith("내용 누락 의심"))
    diag = next((re.sub(r"^.*?\(", "(", n)[:70] for n in notes if "형식 오류" in n), "")
    return (f"[{number}] 분량 {scored['ratio']} | 서술체 {scored['hard']} | 수치왜곡 {scored['invented']} | 핵심수치보존 {scored['numbers']}" + ("" if scored["missing"] == "-" else f" 빠진 {scored['missing']}") + " | "
            f"형식오류 {fmt}회 | 줄단위해결 {fixed} | 원문대체 {len(replaced)}({'·'.join(kinds) or '-'}) | 규칙교정 {ruled}"
            f"\n     생략문장 {','.join(dropped) or '없음'} | 수치누락 {'; '.join(gaps) or '없음'} | 내용보강 {audit_ok}(실패 {audit_bad})"
            + (f"\n     형식오류 진단 {diag}" if diag else ""))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="out")
    parser.add_argument("--holdout", action="store_true")
    parser.add_argument("--quiet", action="store_true", help="건별 상세 출력을 끄고 맨 끝 요약만(기본은 상세도 출력)")
    parser.add_argument("--only", type=int, nargs="*", help="번호만 (예: --only 2 4)")
    args = parser.parse_args()
    load_and_apply()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    summary: list[str] = []
    for number in args.only or range(1, 6):
        source = next(score_drafting.SAMPLES.glob(f"줄글_{number}_*.txt"))
        result = draft(source.read_text(encoding="utf-8"), year=2026,
                       holdout={number} if args.holdout else None)
        target = out / f"eval_{number}_구조.txt"
        target.write_text(result.text, encoding="utf-8")
        (out / f"eval_{number}.md").write_text("\n".join(f"- {n}" for n in result.notes), encoding="utf-8")
        scored = score_drafting.summary(target, number)
        summary.append(_brief(number, result, scored))
        if not args.quiet:
            print(f"[{number}] 방식 {result.mode}, 판단 {len(result.notes)}건 → {target}")
            score_drafting.score(target, number)
        else:
            print(f"[{number}] 완료")
    text = "\n".join(["==== 핵심 요약 (이 부분만 보내 주세요) ====", *summary,
                      "기준: 분량 정답 62~77% / 서술체 0 / 수치왜곡 0 / 핵심수치보존 전부(예 14/14) / 원문대체 줄 전체의 20% 이하 / 형식오류 0~1회"])
    (out / "eval_summary.txt").write_text(text, encoding="utf-8")
    print()
    print(text)


if __name__ == "__main__":
    main()
