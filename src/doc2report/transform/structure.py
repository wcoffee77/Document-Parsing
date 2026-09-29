"""문서 구조 정규화 — 제목을 단락 체계 안으로 접어 넣고, 표 주석을 표에 붙인다.

사내 보고서는 제목/본문이 따로 있는 것이 아니라 1. → □ → - 한 체계로 쓰인다.
반면 Confluence·Markdown 문서는 ##, ### 제목과 목록을 섞어 쓴다.
그 둘을 맞춰 주는 단계다. (profiles의 text.headings_as_levels 로 끈다.)

    ## 추진 배경        →  1. 추진 배경
    - 응답 지연 지속    →     □ 응답 지연 지속
      - 상세 내용       →        - 상세 내용

Confluence에서 내려받은 문서는 제목에 이미 "1. 추진 배경"처럼 번호가 박혀 있는 경우가
흔하다. 그대로 접으면 프로파일이 매기는 말머리와 겹쳐 "1.<TAB>1. 추진 배경"으로
두 번 나오므로, 접기 전에 그 번호를 떼어 낸다. 같은 이유로 원문이 "□ "/"- " 같은
말머리 문자를 이미 직접 쳐 넣은 경우도 있다(사내 Confluence 관행) — 이건 숫자가
아니라 `profiles`의 `text.strip_leading_markers`에 적힌 문자를 보고 뗀다.
"""

from __future__ import annotations

import re

from ..ir import Block, Callout, Document, Heading, ListItem, Paragraph, Run, Table, plain
from .stylize_ko import Change

HEADING_BASE = 2  # H1은 문서 제목이므로 H2가 첫 단계(1.)가 된다

# 제목 앞 수동 번호: "1. ", "1.추진", "1.1. ", "2) ", "(3) ".
# 끝의 (?!\d) 가 "1.5배 향상"처럼 숫자로 시작하는 제목을 번호로 오인하지 않게 한다.
_EXISTING_NUMBER = re.compile(r"^\s*(?:\(\d+\)|\d+(?:\.\d+)*[.)])(?!\d)\s*")


def fold_headings_into_levels(doc: Document,
                              strip_markers: list[str] | None = None
                              ) -> tuple[Document, list[Change]]:
    """제목을 ListItem으로 바꾸고, 그 아래 목록의 깊이를 한 단계씩 민다."""
    blocks: list[Block] = []
    changes: list[Change] = []
    heading_depth = -1
    marker_re = _marker_pattern(strip_markers or [])

    for block in doc.blocks:
        if isinstance(block, Heading):
            depth = max(0, block.level - HEADING_BASE)
            heading_depth = depth
            runs, change = _strip_existing_marker(block.runs, marker_re)
            if change:
                changes.append(change)
            blocks.append(ListItem(depth=depth, runs=runs))
        elif isinstance(block, ListItem):
            runs, change = _strip_existing_marker(block.runs, marker_re)
            if change:
                changes.append(change)
            blocks.append(ListItem(depth=heading_depth + 1 + block.depth, runs=runs,
                                   ordered=block.ordered, number=block.number))
        elif isinstance(block, Paragraph) and heading_depth >= 0:
            # 제목 아래 본문 문단도 그 단계의 항목으로 붙인다.
            runs, change = _strip_existing_marker(block.runs, marker_re)
            if change:
                changes.append(change)
            blocks.append(ListItem(depth=heading_depth + 1, runs=runs))
        else:
            blocks.append(block)

    return Document(blocks=blocks, title=doc.title, source=doc.source), changes


def _marker_pattern(markers: list[str]) -> re.Pattern | None:
    """원본에 이미 박혀 있는 말머리 문자(profiles의 text.strip_leading_markers)를
    잡는 패턴. 뒤에 공백이 와야만 매치한다 — "-5%"(음수), "1.5배"(소수)처럼
    말머리가 아닌 문자를 실수로 떼지 않기 위해서다."""
    if not markers:
        return None
    escaped = "|".join(re.escape(m) for m in sorted(markers, key=len, reverse=True))
    return re.compile(rf"^\s*(?:{escaped})\s+")


def _strip_existing_marker(runs: list[Run],
                           marker_re: re.Pattern | None) -> tuple[list[Run], Change | None]:
    if not runs:
        return runs, None
    first = runs[0]
    match = _EXISTING_NUMBER.match(first.text)
    label = "제목 중복 번호 제거"
    if not match and marker_re is not None:
        match = marker_re.match(first.text)
        label = "중복 말머리 제거"
    if not match or match.end() >= len(first.text.rstrip()) and len(runs) == 1:
        return runs, None  # 말머리만 있는 항목("1.", "-")은 그대로 둔다
    before = plain(runs)
    stripped = first.copy_with(first.text[match.end():])
    new_runs = [stripped, *runs[1:]] if stripped.text else list(runs[1:])
    return new_runs, Change(before, plain(new_runs), label)


# ── 표 주석 ─────────────────────────────────────────────────────────────


def attach_table_notes(doc: Document, markers: list[str],
                       note_marker: str | None) -> tuple[Document, list[Change]]:
    """표 바로 뒤의 주석 문단을 표에 붙인다.

    - 인용문(`> 측정 기준은 …`)은 Markdown·Confluence에서 표 설명을 다는 흔한 방식이다.
    - `*`, `※` 등 markers 로 시작하는 문단도 주석으로 본다.
    본문 흐름에서 빼 두지 않으면 제목 접기에서 □ 항목이 되어 버리고, 표와 주석 사이에
    '표 뒤 간격'이 끼어 주석이 표에서 떨어져 보인다.
    """
    blocks: list[Block] = []
    changes: list[Change] = []
    current: Table | None = None

    for block in doc.blocks:
        if current is not None:
            notes = _as_notes(block, markers)
            if notes is not None:
                for runs in notes:
                    current.notes.append(runs)
                    after = f"{note_marker} {plain(runs)}" if note_marker else plain(runs)
                    changes.append(Change(_original_text(block), after, "표 주석"))
                continue
        current = block if isinstance(block, Table) else None
        blocks.append(block)

    return Document(blocks=blocks, title=doc.title, source=doc.source), changes


def _as_notes(block: Block, markers: list[str]) -> list[list[Run]] | None:
    if isinstance(block, Callout) and block.kind == "quote":
        if not block.blocks or not all(isinstance(b, Paragraph) for b in block.blocks):
            return None
        return [_strip_marker(b.runs, markers) for b in block.blocks]
    if isinstance(block, Paragraph) and _marker_of(plain(block.runs), markers):
        return [_strip_marker(block.runs, markers)]
    return None


def _marker_of(text: str, markers: list[str]) -> str | None:
    stripped = text.lstrip()
    for marker in sorted(markers, key=len, reverse=True):
        if stripped.startswith(marker):
            return marker
    return None


def _strip_marker(runs: list[Run], markers: list[str]) -> list[Run]:
    if not runs:
        return runs
    marker = _marker_of(runs[0].text, markers)
    if not marker:
        return runs
    text = runs[0].text.lstrip()[len(marker):].lstrip()
    head = runs[0].copy_with(text)
    return [head, *runs[1:]] if text else list(runs[1:])


def _original_text(block: Block) -> str:
    if isinstance(block, Callout):
        return " / ".join(plain(b.runs) for b in block.blocks if isinstance(b, Paragraph))
    return plain(getattr(block, "runs", []))


# ── 짧은 항목 병합 ──────────────────────────────────────────────────────


def merge_short_list_items(doc: Document, max_chars: int) -> tuple[Document, list[Change]]:
    """같은 단계의 짧은 항목이 연달아 나오면 "및"으로 **둘씩** 짝지어 합친다
    (사용자 요청, 2026-09-28). "10월 중 2차 성능 시험 실시" / "미흡 사항 4분기
    과제로 이관"처럼 둘 다 짧으면 굳이 줄을 나눌 필요가 없다. 셋 이상을 한 항목에
    이어 붙이지는 않는다 — "A 및 B 및 C"는 "및"이 반복돼 어색하고, 개조식의
    핵심인 항목별 스캔 가독성도 해친다. 합친 뒤에도 다음 항목이 짧으면 그 항목은
    또 다른 항목과 새로 짝짓는다(방금 합친 결과와 다시 합치지 않는다).

    fold_headings_into_levels보다 **먼저** 돌아야 한다 — 그 전에는 제목이
    아직 Heading 블록이라 ListItem과 섞이지 않는다. 접은 뒤에는 제목도
    ListItem이 되어 버려서, 짧은 소제목이 그 아래 짧은 항목과 잘못 합쳐질 수 있다.
    """
    if max_chars <= 0:
        return doc, []

    blocks: list[Block] = []
    changes: list[Change] = []
    src = doc.blocks
    i = 0
    while i < len(src):
        block = src[i]
        next_item = src[i + 1] if i + 1 < len(src) else None
        can_pair = (isinstance(block, ListItem) and isinstance(next_item, ListItem)
                   and next_item.depth == block.depth
                   and _merged_length([block], next_item) <= max_chars)
        group = [block, next_item] if can_pair else [block]
        j = i + len(group)

        if len(group) > 1:
            merged = _merge_items(group)
            changes.append(Change(" / ".join(plain(g.runs) for g in group),
                                  plain(merged.runs), "항목 병합"))
            blocks.append(merged)
        else:
            blocks.append(block)
        i = j

    return Document(blocks=blocks, title=doc.title, source=doc.source), changes


def _merged_length(group: list[ListItem], candidate: ListItem) -> int:
    texts = [plain(g.runs) for g in group] + [plain(candidate.runs)]
    return len(" 및 ".join(texts))


def _merge_items(group: list[ListItem]) -> ListItem:
    first = group[0]
    template = first.runs[0] if first.runs else Run("")
    merged_text = " 및 ".join(plain(g.runs) for g in group)
    return ListItem(depth=first.depth, runs=[template.copy_with(merged_text)],
                    ordered=first.ordered, number=first.number)
