"""회귀 코퍼스 점수 — 서식을 고칠 때 개선인지 퇴보인지 숫자로 판단한다.

    uv run python tools/score_corpus.py [프로파일]

tests/fixtures/*.md 를 모두 변환하고 다음을 센다.
    표 폭 초과      : 사용가능폭을 넘긴 표 (0이어야 한다)
    글자 크기 하향  : 기본 크기로 못 들어가 줄인 표
    줄 수 초과      : 셀이 max_cell_lines를 넘긴 표
    페이지 수       : Word가 설치된 Windows에서만 (실제 렌더 기준)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from doc2report.pipeline import convert  # noqa: E402
from doc2report.profile import load_profile  # noqa: E402
from doc2report.units import emu_to_mm  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
OUT = Path(__file__).resolve().parents[1] / "out" / "corpus"


def page_count(path: Path) -> str:
    """Word가 있으면 실제 렌더 페이지 수를, 없으면 '-'."""
    try:
        import win32com.client  # type: ignore
    except ImportError:
        return "-"
    word = win32com.client.Dispatch("Word.Application")
    word.Visible = False
    try:
        doc = word.Documents.Open(str(path), False, True)
        count = doc.ComputeStatistics(2)  # wdStatisticPages
        doc.Close(0)
        return str(count)
    except Exception:
        return "?"
    finally:
        word.Quit()


def main(profile_name: str = "default") -> int:
    profile = load_profile(profile_name)
    usable = profile.page.usable_width
    OUT.mkdir(parents=True, exist_ok=True)

    header = f"{'문서':28} {'표':>3} {'초과':>4} {'축소':>4} {'최대폭':>7} {'문구':>5} {'쪽':>3}"
    print(f"[프로파일 {profile_name}] 사용가능폭 {emu_to_mm(usable):.1f}mm")
    print(header)
    print("-" * len(header))

    total_over = 0
    for source in sorted(FIXTURES.glob("*.md")):
        out = OUT / f"{source.stem}.docx"
        result = convert(str(source), out, profile)
        layouts = list(result.layouts.values())
        over = sum(1 for layout in layouts if layout.total_width > usable)
        shrunk = sum(1 for layout in layouts if layout.font_size < profile.table_font_ladder()[0])
        widest = max((emu_to_mm(layout.total_width) for layout in layouts), default=0.0)
        total_over += over
        print(f"{source.name:28} {len(layouts):>3} {over:>4} {shrunk:>4} "
              f"{widest:>6.1f}mm {len(result.changes):>5} {page_count(out):>3}")

    print()
    print("표 폭 초과 0건" if total_over == 0 else f"표 폭 초과 {total_over}건 — 확인 필요")
    return 1 if total_over else 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
