"""문서 구조 정규화 — 제목을 단락 체계 안으로 접어 넣는다.

사내 보고서는 제목/본문이 따로 있는 것이 아니라 1. → □ → - 한 체계로 쓰인다.
반면 Confluence·Markdown 문서는 ##, ### 제목과 목록을 섞어 쓴다.
그 둘을 맞춰 주는 단계다. (profiles의 text.headings_as_levels 로 끈다.)

    ## 추진 배경        →  1. 추진 배경
    - 응답 지연 지속    →     □ 응답 지연 지속
      - 상세 내용       →        - 상세 내용
"""

from __future__ import annotations

from ..ir import Block, Document, Heading, ListItem, Paragraph

HEADING_BASE = 2  # H1은 문서 제목이므로 H2가 첫 단계(1.)가 된다


def fold_headings_into_levels(doc: Document) -> Document:
    """제목을 ListItem으로 바꾸고, 그 아래 목록의 깊이를 한 단계씩 민다."""
    blocks: list[Block] = []
    heading_depth = -1

    for block in doc.blocks:
        if isinstance(block, Heading):
            depth = max(0, block.level - HEADING_BASE)
            heading_depth = depth
            blocks.append(ListItem(depth=depth, runs=block.runs))
        elif isinstance(block, ListItem):
            blocks.append(ListItem(depth=heading_depth + 1 + block.depth, runs=block.runs,
                                   ordered=block.ordered, number=block.number))
        elif isinstance(block, Paragraph) and heading_depth >= 0:
            # 제목 아래 본문 문단도 그 단계의 항목으로 붙인다.
            blocks.append(ListItem(depth=heading_depth + 1, runs=block.runs))
        else:
            blocks.append(block)

    return Document(blocks=blocks, title=doc.title, source=doc.source)
