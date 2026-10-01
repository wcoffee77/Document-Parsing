"""붙여넣은 글 → Markdown 텍스트 (그다음은 Markdown 파서가 IR로 옮긴다).

메신저·메일·Word에서 복사한 글은 **한 줄이 한 문단**이다. 그대로 Markdown에 넣으면 빈 줄이
없는 줄들이 한 문단으로 합쳐져("□ 항목1 - 항목2") 말머리 구분이 사라진다. 그래서 줄마다
문단을 나눈다. Markdown으로 쓴 글(# 제목, |---| 표, ``` 코드가 있는 글)은 손대지 않고 Markdown으로 읽는다.

일반 글에서 줄 앞의 "- ", "1. "은 Markdown 목록 문법이 아니라 **글쓴이가 친 말머리**다 —
목록으로 읽으면 말머리가 프로파일 것(□ 등)으로 바뀌어 "원문 말머리 유지" 원칙이 깨진다. 그래서
글자 그대로 남도록 이스케이프하고, 단계(들여쓰기)는 제목 접기가 그 말머리를 보고 정한다.

엑셀에서 복사한 표는 칸이 탭으로 나뉘어 들어온다 — 탭으로 나뉜 줄이 두 줄 이상 이어지면
Markdown 표로 바꿔 준다(첫 줄 = 머리행).
"""

from __future__ import annotations

import functools
import re

from ..ir import DATE_LINE, Run

_TITLE_STOP = ("□", "■", "○", "●", "※", "(", "[", "【", "〈", "ㅁ")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_MD_LIST = re.compile(r"^(\s*)([-*+>]|\d{1,9}[.)])(\s+)")
_MARKDOWN_SIGNS = re.compile(r"^(?:#{1,6}\s|```|~~~|\s*\|?\s*:?-{3,}:?\s*\|)", re.MULTILINE)


def looks_like_markdown(text: str) -> bool:
    return bool(_MARKDOWN_SIGNS.search(text))


def _mark_title(lines: list[str]) -> None:
    """맨 위 짧은 한 줄 + 바로 다음 줄이 날짜면 문서 제목으로 본다("# 제목") — 서식이 없는 글에서도 제목·날짜
    줄이 정식보고서 모양(가운데 큰 글씨 + 오른쪽 날짜)으로 나오게."""
    filled = [i for i, line in enumerate(lines) if line.strip()]
    if len(filled) < 2:
        return
    first, second = filled[0], filled[1]
    title = lines[first].strip()
    if (len(title) <= 60 and DATE_LINE.match(lines[second].strip())
            and not _MD_LIST.match(title) and not title.startswith(_TITLE_STOP)):
        lines[first] = "# " + title


_NUMBERED_HEADING = re.compile(r"^(?:\d{1,2}[.)]|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ][.)]?)\s")
_SENTENCE_END = re.compile(r"(?<!\d)[.!?]$")


@functools.lru_cache(maxsize=1)
def _marker_rules():
    """말머리·꺾쇠·주석 표시 문자는 프로파일 값을 쓴다 — 코드에 문자를 굳히지 않는다."""
    from ..profile import load_profile
    from ..transform.structure import _find_marker, _marker_pattern

    rules = load_profile("default").text
    notes: tuple[str, ...] = ()
    try:
        notes = tuple(load_profile("formal").text.annotation_markers)  # "*" "＊" "(주석)" — 글쓴이가 친 주석 표시
    except FileNotFoundError:
        pass
    return (_marker_pattern(rules.leading_markers), _find_marker,
            tuple(rules.no_marker_openers) + ("(", "（"), notes)


def _join_wrapped(lines: list[str]) -> list[str]:
    """말머리 줄 바로 아래의 **말머리 없는 줄**을 윗줄에 딸린 줄로 묶는다 — 엔터 위치는 그대로 둔다.

    정식보고서에서 한 문장이 길어 글쓴이가 엔터로 내려쓴 줄은 txt에서 독립된 줄이 된다. 그대로 두면 새 항목
    (말머리가 붙고 굵기·정렬이 어긋남)이 된다. 그렇다고 한 줄로 합쳐 다시 나누면 글쓴이의 줄바꿈과 어긋난다
    (2026-10-01 사용자: 뒤죽박죽). 그래서 Markdown **강제 줄바꿈**(줄 끝 공백 두 칸)으로 같은 문단에 묶어
    렌더러가 그 줄바꿈 자리에서 윗줄 글자에 맞춰 이어 쓰게 한다.

    묶는 조건: 윗줄이 말머리 줄(번호 제목 "1." 제외)이고 마침표·물음표로 끝나지 않으며, 이 줄은 말머리·날짜·꺾쇠·
    괄호·주석 표시로 시작하지 않을 때. 이어지는 줄이 여러 개여도 계속 묶는다(쉼표로 끝나는 줄 다음 줄 포함)."""
    pattern, find, openers, notes = _marker_rules()
    out: list[str] = []
    in_fence = False
    joinable = False  # 바로 윗줄이 이어 받을 수 있는 말머리 줄(또는 그 이어짐)인가
    for line in lines:
        if _FENCE.match(line):
            in_fence = not in_fence
            out.append(line)
            joinable = False
            continue
        stripped = line.strip()
        if in_fence or not stripped or "\t" in line or _TABLE_ROW.match(line):
            out.append(line)
            joinable = False
            continue
        listed = _MD_LIST.match(stripped)
        is_marker = (listed is not None and not listed.group(2)[0].isdigit()) or stripped.startswith(notes) \
            or find([Run(stripped)], pattern) is not None   # 말머리 줄 (날짜 "2026. 9. 1"은 아니다)
        starts_new = bool(listed) or is_marker or stripped.startswith(openers) or bool(DATE_LINE.match(stripped))
        if joinable and not starts_new and not _SENTENCE_END.search(out[-1].rstrip()):
            out[-1] = out[-1].rstrip() + "  \n" + stripped
            continue
        out.append(line)
        joinable = is_marker and not _NUMBERED_HEADING.match(stripped)
    return out


def text_to_markdown(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if looks_like_markdown(text):
        return text
    lines = text.split("\n")
    _mark_title(lines)
    lines = _join_wrapped(lines)
    out: list[str] = []
    in_fence = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if _FENCE.match(line):
            in_fence = not in_fence
            out.append(line)
            i += 1
            continue
        if in_fence:
            out.append(line)
            i += 1
            continue

        tabbed = _tab_block(lines, i)
        if tabbed:
            _blank(out)
            out.extend(_tab_table(lines[i:i + tabbed]))
            out.append("")
            i += tabbed
            continue

        if _TABLE_ROW.match(line):
            if out and out[-1] and not _TABLE_ROW.match(out[-1]):
                out.append("")
            out.append(line)  # 표 행은 붙여 둬야 한 표가 된다
        elif not line.strip():
            _blank(out)
        else:
            _blank(out)
            out.append(_literal(line))
        i += 1
    return "\n".join(out).strip() + "\n"


def _blank(out: list[str]) -> None:
    if out and out[-1] != "":
        out.append("")


def _literal(line: str) -> str:
    """줄을 글자 그대로 한 문단으로. 앞 공백은 걷고(4칸이면 코드 블록이 된다) 줄 앞 말머리는
    Markdown 목록·인용으로 안 읽히게 이스케이프한다("- 항목" → "\\- 항목")."""
    line = line.strip()
    match = _MD_LIST.match(line)
    if match:
        mark = match.group(2)
        escaped = "\\" + mark if not mark[0].isdigit() else mark[:-1] + "\\" + mark[-1]
        line = escaped + line[len(mark):]
    return line


def _tab_block(lines: list[str], start: int) -> int:
    """start부터 탭으로 나뉜 줄이 몇 줄 이어지는지. 2줄 미만이면 0.

    머리 줄의 칸 수가 기준이다. 뒤 줄이 그보다 칸이 **적으면**(엑셀에서 복사할 때 끝의 빈 칸 탭이 잘려 나온
    줄 — "A\t30%\t120%") 표의 줄로 보고 빈 칸을 채운다. 칸이 더 많거나 탭이 없는 줄은 표의 끝이다."""
    width = lines[start].count("\t")
    if width == 0:
        return 0
    count = 0
    for line in lines[start:]:
        if not line.strip() or not 1 <= line.count("\t") <= width:
            break
        count += 1
    return count if count >= 2 else 0


def _tab_table(rows: list[str]) -> list[str]:
    cells = [[c.strip().replace("|", "\\|") for c in row.split("\t")] for row in rows]
    width = len(cells[0])
    cells = [row + [""] * (width - len(row)) for row in cells]  # 끝 칸이 빈 줄은 탭이 잘려 칸이 모자라다
    header, body = cells[0], cells[1:]
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(row) + " |" for row in body]
    return out
