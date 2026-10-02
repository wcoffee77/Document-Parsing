"""줄 폭 보정용 docx — Word에서 열어 '한 줄에 몇 글자가 들어가는지' 세어 알려 주는 용도.

    uv run python tools/make_calibration.py [프로파일]    # 기본 formal → out/calibration.docx

각 시험은 라벨 한 줄 + 긴 문장 한 문단이다. 문장이 첫 줄에서 몇 글자까지 들어갔는지(공백 포함)
세어 라벨 옆 번호와 함께 알려 주면 된다. 서식(글꼴·크기·여백)은 프로파일 값을 쓰고,
글자 간격은 도구가 실제로 쓰는 방식(oxml.set_char_spacing)으로 넣는다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from docx import Document  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402
from docx.shared import Emu, Pt  # noqa: E402

from doc2report.profile import load_profile  # noqa: E402
from doc2report.render import oxml  # noqa: E402
from doc2report.render.base_template import open_base_template  # noqa: E402

HANGUL = "가나다라마바사아자차카타파하" * 6
TESTS = [
    # (라벨, 문장, 굵게, 간격 pt)
    *[(f"한글 보통 간격 {c}pt", HANGUL, False, c) for c in (0, 0.2, 0.4, 0.7, 1.0)],
    *[(f"한글 굵게 간격 {c}pt", HANGUL, True, c) for c in (0, 0.4, 1.0)],
    *[(f"한글+공백(5자마다) 간격 {c}pt", " ".join(HANGUL[i:i + 5] for i in range(0, 70, 5)), False, c)
      for c in (0, 1.0)],
    *[(f"한글+영문숫자(5자마다 'ab12') 간격 {c}pt", "".join(HANGUL[i:i + 5] + "ab12" for i in range(0, 70, 5)),
       False, c) for c in (0, 1.0)],
    # 아래는 한 종류 글자만 길게 이어 쓴 시험 — 공백 없는 긴 낱말은 Word가 줄 끝에서 글자 단위로 끊으므로
    # "첫 줄 글자 수"가 그 글자의 폭과 간격 효과를 그대로 보여 준다(위 혼합 시험은 줄바꿈 위치를 못 가렸다).
    *[(f"숫자만 100자 간격 {c}pt", "1234567890" * 10, False, c) for c in (0, 1.0)],
    *[(f"대문자만 100자 간격 {c}pt", "ABCDEFGHIJ" * 10, False, c) for c in (0, 1.0)],
    *[(f"소문자만 100자 간격 {c}pt", "abcdefghij" * 10, False, c) for c in (0, 1.0)],
    *[(f"기호 % 100자 간격 {c}pt", "%" * 100, False, c) for c in (0, 1.0)],
    # 한글 5자 + 기호 1자를 되풀이 — 한글↔기호 경계에도 한글↔영문처럼 1/4em이 붙는지 가린다
    # (붙으면 첫 줄이 34자, 안 붙으면 37자). 영문·숫자는 붙는 것이 확인됐다(위 [11]~[12]).
    *[(f"한글5자+'{mark}' 되풀이 간격 0pt (첫 줄 글자 수, 기호 포함)", ("가나다라마" + mark) * 14, False, 0)
      for mark in ("%", ",", ".", "(")],
    # 한글 한 글자 + 공백이 번갈아 — 공백마다 줄을 끊을 수 있어서 "첫 줄의 한글 수"로 공백 폭이 정해진다.
    *[(f"한글+공백 번갈아 간격 {c}pt (한글 글자 수를 세기)", "가 " * 60, False, c) for c in (0, 1.0)],
]


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "formal"
    profile = load_profile(name)
    doc = Document(profile.template or open_base_template())  # python-docx 기본 .docx 파일은 사내 보안이 막는다(CLAUDE.md)
    if profile.text.balance_sbcs_dbcs:  # 변환기와 같은 호환 옵션(없으면 한글 간격 −1pt에서 37자, 있으면 40자)
        oxml.set_compat_flag(doc.settings.element, "balanceSingleByteDoubleByteWidth")
    section = doc.sections[0]
    page = profile.page
    section.page_width, section.page_height = Emu(page.width), Emu(page.height)
    section.left_margin, section.right_margin = Emu(page.margin.left), Emu(page.margin.right)
    section.top_margin, section.bottom_margin = Emu(page.margin.top), Emu(page.margin.bottom)
    body = profile.font("body")
    for number, (label, text, bold, spacing) in enumerate(TESTS, 1):
        head = doc.add_paragraph()
        head_run = head.add_run(f"[{number}] {label}")
        head_run.font.size = Pt(10)
        paragraph = doc.add_paragraph()
        paragraph.paragraph_format.space_after = Pt(8)
        run = paragraph.add_run(text)
        rfonts = run._element.get_or_add_rPr().get_or_add_rFonts()
        for attr in ("ascii", "hAnsi", "eastAsia"):
            rfonts.set(qn(f"w:{attr}"), body.east_asia)
        run.font.size = Emu(body.size)
        run.bold = bold
        if spacing:
            oxml.set_char_spacing(run, -round(spacing * 20))
    out = Path(__file__).resolve().parents[1] / "out" / "calibration.docx"
    out.parent.mkdir(exist_ok=True)
    doc.save(out)
    print(f"저장: {out} (글꼴 {body.east_asia}, {body.size / 12700:g}pt)")


if __name__ == "__main__":
    main()
