"""서식 값이 코드로 새어 들어가지 않는지 감시한다.

여백·글자 크기·글꼴명은 profiles/*.yaml 에만 있어야 사내 규격이 바뀔 때
코드를 건드리지 않고 대응할 수 있다. 이 테스트가 그 약속을 지켜 준다.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "doc2report"

# 단위 변환기와 프로파일 초안 생성기는 단위 리터럴을 다루는 것이 본업이다.
ALLOWED = {"units.py", "profile_init.py"}

_LENGTH_LITERAL = re.compile(r"^\s*-?\d+(\.\d+)?\s*(pt|mm|cm|in)\s*$", re.I)
_FONT_NAMES = ("맑은 고딕", "굴림", "바탕", "돋움", "함초롬", "Calibri", "Arial",
               "Times New Roman", "Consolas")


def _source_files():
    return [p for p in SRC.rglob("*.py") if p.name not in ALLOWED]


def _string_literals(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value, node.lineno


def test_no_length_literals_in_code():
    offenders = [
        f"{path.relative_to(SRC)}:{line} → {value!r}"
        for path in _source_files()
        for value, line in _string_literals(path)
        if _LENGTH_LITERAL.match(value)
    ]
    assert not offenders, "서식 값은 프로파일에만 두세요:\n" + "\n".join(offenders)


def test_no_font_names_in_code():
    """글꼴 이름은 프로파일에만. (layout/measure.py의 글꼴 파일 색인은 예외)"""
    offenders = [
        f"{path.relative_to(SRC)}:{line} → {value!r}"
        for path in _source_files()
        if path.name != "measure.py"
        for value, line in _string_literals(path)
        if any(name in value for name in _FONT_NAMES)
    ]
    assert not offenders, "글꼴 이름은 프로파일에만 두세요:\n" + "\n".join(offenders)
