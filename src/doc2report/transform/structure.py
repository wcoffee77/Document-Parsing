"""문서 구조 정규화 — 제목을 단락 체계 안으로 접어 넣는다.

사내 보고서는 제목/본문이 따로 있는 것이 아니라 1. → □ → - 한 체계로 쓰인다.
반면 Confluence·Markdown 문서는 ##, ### 제목과 목록을 섞어 쓴다.
그 둘을 맞춰 주는 단계다. (profiles의 text.headings_as_levels 로 끈다.)

    ## 추진 배경        →  1. 추진 배경
    - 응답 지연 지속    →     □ 응답 지연 지속
      - 상세 내용       →        - 상세 내용

Confluence에서 내려받은 문서는 제목에 이미 "1. 추진 배경"처럼 번호가 박혀 있는 경우가
흔하다. 그대로 접으면 프로파일이 매기는 말머리와 겹쳐 "1.<TAB>1. 추진 배경"으로
두 번 나오므로, 접기 전에 그 번호를 떼어 낸다.
"""

from __future__ import annotations

import re

from ..ir import Block, Document, Heading, ListItem, Paragraph, Run, plain
from .stylize_ko import Change

HEADING_BASE = 2  # H1은 문서 제목이므로 H2가 첫 단계(1.)가 된다

# "1. ", "2) ", "(3) " 같이 흔히 쓰는 수동 번호. 소수점 다단계("2.1")는 프로파일
# 체계가 표현하지 못해 건드리지 않는다.
_EXISTING_NUMBER = re.compile(r"^\(?\d+[.)]\s+")


def fold_headings_into_levels(doc: Document) -> tuple[Document, list[Change]]:
    """제목을 ListItem으로 바꾸고, 그 아래 목록의 깊이를 한 단계씩 민다."""
    blocks: list[Block] = []
    changes: list[Change] = []
    heading_depth = -1

    for block in doc.blocks:
        if isinstance(block, Heading):
            depth = max(0, block.level - HEADING_BASE)
            heading_depth = depth
            runs, change = _strip_existing_number(block.runs)
            if change:
                changes.append(change)
            blocks.append(ListItem(depth=depth, runs=runs))
        elif isinstance(block, ListItem):
            blocks.append(ListItem(depth=heading_depth + 1 + block.depth, runs=block.runs,
                                   ordered=block.ordered, number=block.number))
        elif isinstance(block, Paragraph) and heading_depth >= 0:
            # 제목 아래 본문 문단도 그 단계의 항목으로 붙인다.
            blocks.append(ListItem(depth=heading_depth + 1, runs=block.runs))
        else:
            blocks.append(block)

    return Document(blocks=blocks, title=doc.title, source=doc.source), changes


def _strip_existing_number(runs: list[Run]) -> tuple[list[Run], Change | None]:
    if not runs:
        return runs, None
    first = runs[0]
    match = _EXISTING_NUMBER.match(first.text)
    if not match:
        return runs, None
    before = plain(runs)
    stripped = first.copy_with(first.text[match.end():])
    new_runs = [stripped, *runs[1:]] if stripped.text else list(runs[1:])
    return new_runs, Change(before, plain(new_runs), "제목 중복 번호 제거")
