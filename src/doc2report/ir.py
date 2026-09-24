"""중간표현(IR) — 파이프라인의 모든 단계가 주고받는 유일한 계약.

입력 형식이 늘어나면 parsers/ 만 추가하고, 출력이 늘어나면 render/ 만 추가한다.
IR 자체에는 서식(pt, mm, 글꼴명)이 절대 들어가지 않는다. 서식은 프로파일의 몫이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ── 인라인 ──────────────────────────────────────────────────────────────


@dataclass
class Run:
    """서식이 동일한 텍스트 조각."""

    text: str
    bold: bool = False
    italic: bool = False
    code: bool = False
    href: str | None = None

    def copy_with(self, text: str) -> Run:
        return Run(text=text, bold=self.bold, italic=self.italic, code=self.code, href=self.href)


def plain(runs: list[Run]) -> str:
    """런 목록의 순수 텍스트."""
    return "".join(r.text for r in runs)


# ── 블록 ────────────────────────────────────────────────────────────────


@dataclass
class Heading:
    level: int  # 1-6
    runs: list[Run] = field(default_factory=list)


@dataclass
class Paragraph:
    runs: list[Run] = field(default_factory=list)


@dataclass
class ListItem:
    """목록 항목 하나. depth는 0부터 시작하며 프로파일의 numbering 배열 인덱스가 된다."""

    depth: int
    runs: list[Run] = field(default_factory=list)
    ordered: bool = False
    number: int | None = None  # ordered일 때 원본 번호


@dataclass
class CodeBlock:
    text: str
    lang: str | None = None


@dataclass
class Image:
    src: str  # 로컬 경로 또는 URL
    caption: str | None = None
    width_px: int | None = None
    height_px: int | None = None


@dataclass
class Cell:
    blocks: list["Block"] = field(default_factory=list)
    colspan: int = 1
    rowspan: int = 1
    is_header: bool = False
    align: str | None = None  # left | center | right


@dataclass
class Row:
    cells: list[Cell] = field(default_factory=list)


@dataclass
class Table:
    rows: list[Row] = field(default_factory=list)
    header_rows: int = 1
    caption: str | None = None

    @property
    def col_count(self) -> int:
        return max((sum(c.colspan for c in r.cells) for r in self.rows), default=0)


@dataclass
class Callout:
    """Confluence의 info/note/warning 패널, Markdown의 인용문."""

    kind: str  # info | note | warning | quote
    blocks: list["Block"] = field(default_factory=list)


@dataclass
class HorizontalRule:
    pass


@dataclass
class PageBreak:
    pass


Block = (
    Heading | Paragraph | ListItem | CodeBlock | Image | Table | Callout | HorizontalRule | PageBreak
)


@dataclass
class Document:
    blocks: list[Block] = field(default_factory=list)
    title: str | None = None
    source: str | None = None  # 원본 경로/URL — 로그·머리말용


def iter_tables(doc: Document):
    """중첩(Callout, 표 셀) 안쪽까지 포함해 모든 Table을 순회."""

    def walk(blocks):
        for b in blocks:
            if isinstance(b, Table):
                yield b
                for row in b.rows:
                    for cell in row.cells:
                        yield from walk(cell.blocks)
            elif isinstance(b, Callout):
                yield from walk(b.blocks)

    yield from walk(doc.blocks)
