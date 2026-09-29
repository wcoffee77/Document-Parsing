"""전체 변환 오케스트레이션.

CLI·GUI·MCP 무엇을 붙이든 이 convert() 하나만 호출하면 되도록 유지한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .ir import Document, Heading, Image, PageBreak, Run
from .layout.flow import FlowPlan, plan_flow
from .layout.table_fit import TableLayout, plan_tables
from .parsers.markdown import parse_markdown
from .profile import Profile, load_profile
from .render.docx_writer import DATE_LINE, DocxRenderer
from .sources import LoadedSource, load_source
from .transform import Change, apply_text_rules
from .transform.structure import (
    attach_table_captions,
    attach_table_notes,
    drop_blank_blocks,
    fold_headings_into_levels,
    merge_short_list_items,
)


@dataclass
class ConvertResult:
    document: Document
    layouts: dict[int, TableLayout]
    output: Path | None = None
    notes: list[str] = field(default_factory=list)
    changes: list[Change] = field(default_factory=list)
    flow: FlowPlan = field(default_factory=FlowPlan)

    def report(self) -> str:
        """--report 로 저장하거나 화면에 보여 줄 변경 요약."""
        lines = ["# 변환 리포트", ""]
        if self.output:
            lines += [f"- 출력: `{self.output}`"]
        lines += [f"- 표 {len(self.layouts)}개, 문구 수정 {len(self.changes)}건", ""]

        if self.notes:
            lines += ["## 레이아웃 조정", ""]
            lines += [f"- {note}" for note in self.notes]
            lines.append("")
        if self.changes:
            lines += ["## 문구 수정", "", "| 원문 | 수정 | 규칙 |", "|---|---|---|"]
            for change in self.changes:
                lines.append(
                    f"| {_escape(change.before)} | {_escape(change.after)} | {change.rule} |"
                )
        return "\n".join(lines) + "\n"


def _escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def auto_profile(source: str | LoadedSource) -> str:
    """프로파일을 안 골랐을 때의 기본값. Confluence는 글이 많고 이미 다듬어진 문장이라
    규칙이 다르다(2026-09-29 사용자): 원문 말머리 유지·문장 다듬기 없음·12pt 본문."""
    if isinstance(source, LoadedSource):
        return "confluence" if source.format == "confluence_storage" else "default"
    return "confluence" if source.startswith(("http://", "https://")) else "default"


def load_document(source: str | LoadedSource) -> tuple[Document, list[str]]:
    """입력 하나를 읽어 IR로. (문서, 리포트에 남길 노트)"""
    loaded = source if isinstance(source, LoadedSource) else load_source(source)
    notes = list(loaded.notes)
    if loaded.format == "confluence_storage":
        from .parsers.confluence_storage import parse_confluence_storage

        parsed = parse_confluence_storage(loaded.text, source=loaded.name, title=loaded.title)
        doc = parsed.document
        notes.extend(parsed.notes)
    elif loaded.format == "docx":
        import tempfile

        from .parsers.docx_reader import parse_docx

        image_dir = Path(tempfile.mkdtemp(prefix="doc2report-docx-"))
        parsed = parse_docx(loaded.path, source=loaded.name, image_dir=image_dir)
        doc = parsed.document
        if loaded.title and not doc.title:
            doc.title = loaded.title
        notes.extend(parsed.notes)
    else:
        doc = parse_markdown(loaded.text, source=loaded.name)
        if loaded.title and not doc.title:
            doc.title = loaded.title
    if loaded.base_dir:
        _resolve_image_paths(doc, loaded.base_dir)
    return doc, notes


def merge_documents(docs: list[Document], *, title: str | None = None,
                    section_titles: bool = True, page_breaks: bool = False) -> Document:
    """여러 입력(Confluence 페이지·Word·붙여넣은 글)을 한 문서로.

    section_titles: 각 입력의 제목을 절 제목(맨 바깥 단계)으로 넣고 그 입력의 내용은 한 단계 안으로
    들인다(`Heading.section_title` — 제목 접기가 그 아래 단계를 한 칸씩 민다). 안 그러면 페이지마다
    같은 "1."부터 시작해 어느 페이지 내용인지 구분이 안 된다.
    문서 제목은 title, 없으면 첫 입력의 제목.
    """
    if len(docs) == 1:
        doc = docs[0]
        return Document(blocks=list(doc.blocks), title=title or doc.title, source=doc.source)
    blocks: list = []
    for index, doc in enumerate(docs):
        if index and page_breaks:
            blocks.append(PageBreak())
        if section_titles and doc.title:
            blocks.append(Heading(level=1, runs=[Run(doc.title)], section_title=True))
            blocks.extend(doc.blocks)
        else:
            blocks.extend(doc.blocks)
    first = next((d.title for d in docs if d.title), None)
    return Document(blocks=blocks, title=title or first,
                    source=", ".join(d.source or "" for d in docs))


def convert(
    source: str | LoadedSource,
    output: str | Path | None = None,
    profile: str | Profile | None = None,
    *,
    polish: str | None = None,
    date: str | None = None,
) -> ConvertResult:
    """source(파일 경로 / Confluence URL / '-') → output(.docx).

    profile: 안 주면 소스 종류로 고른다(auto_profile).
    polish: 안 주면 프로파일의 text.polish(없으면 "rules").
    date: 제목 아래에 넣을 날짜. "today"(또는 "오늘")면 오늘 날짜를 프로파일 형식으로 넣는다.
    """
    return convert_many([source], output, profile, polish=polish, date=date)


def convert_many(
    sources: list[str | LoadedSource],
    output: str | Path | None = None,
    profile: str | Profile | None = None,
    *,
    polish: str | None = None,
    date: str | None = None,
    title: str | None = None,
    section_titles: bool = True,
    page_breaks: bool = False,
    progress=None,
) -> ConvertResult:
    """여러 입력을 읽어 한 문서로 합친 뒤 변환한다. progress(메시지)는 진행 상황 알림(웹 화면용)."""
    if not sources:
        raise ValueError("입력이 없습니다")
    say = progress or (lambda message: None)
    if profile is None:
        profile = auto_profile(sources[0])
    prof = profile if isinstance(profile, Profile) else load_profile(profile)

    docs: list[Document] = []
    notes: list[str] = []
    for index, source in enumerate(sources, 1):
        name = source.name if isinstance(source, LoadedSource) else source
        say(f"입력 읽는 중 ({index}/{len(sources)}): {name}")
        doc, source_notes = load_document(source)
        docs.append(doc)
        notes.extend(source_notes)
    doc = merge_documents(docs, title=title, section_titles=section_titles, page_breaks=page_breaks)
    say("문구·구조 규칙 적용 중")
    return convert_document(doc, output, prof, polish=polish, date=date, notes=notes, progress=say)


def convert_document(
    doc: Document,
    output: str | Path | None,
    prof: Profile,
    *,
    polish: str | None = None,
    date: str | None = None,
    notes: list[str] | None = None,
    progress=None,
) -> ConvertResult:
    say = progress or (lambda message: None)
    polish = polish or prof.text.polish or "rules"
    if date:
        _insert_dateline(doc, date, prof)

    doc, changes = drop_blank_blocks(doc)  # 안 그러면 접을 때 "□"만 덜렁 찍힌 줄이 된다
    if polish != "none":
        transformed = apply_text_rules(doc, prof)
        doc = transformed.document
        changes.extend(transformed.changes)
    if prof.tables.note_markers or prof.tables.note_marker:
        # 제목 접기보다 먼저 — 안 그러면 주석 문단이 □ 항목으로 접혀 버린다.
        doc, note_changes = attach_table_notes(doc, prof.tables.note_markers,
                                               prof.tables.note_marker)
        changes.extend(note_changes)
    if prof.text.table_captions:
        # 마찬가지로 제목 접기보다 먼저 — 안 그러면 표 제목도 "-" 항목이 되어 버린다.
        doc, caption_changes = attach_table_captions(doc)
        changes.extend(caption_changes)
    if prof.text.merge_short_items:
        # 제목 접기보다 먼저 — 접은 뒤에는 제목도 ListItem이라 소제목과 섞여 합쳐질 수 있다.
        doc, merge_changes = merge_short_list_items(doc, prof.text.max_sentence_chars)
        changes.extend(merge_changes)
    if prof.text.headings_as_levels:
        # 문구를 다듬은 뒤에 접는다 (제목과 본문은 다듬는 규칙이 다르므로 순서가 중요).
        doc, fold_changes = fold_headings_into_levels(
            doc, prof.text.leading_markers, keep=prof.text.keep_leading_markers,
            marker_depths=prof.marker_depths(), normalize=prof.text.normalize_levels,
            no_marker_openers=prof.text.no_marker_openers,
            auto_markers=prof.text.auto_markers, plain_level=prof.text.plain_paragraph_level,
            note_marks=prof.text.note_marks)
        changes.extend(fold_changes)
    if polish == "llm":
        from .transform.llm_polish import polish_document

        say("LLM으로 문장 다듬는 중")
        doc, llm_changes = polish_document(doc, prof)
        changes.extend(llm_changes)

    say("표 배치 계산 중")
    layouts = plan_tables(doc, prof)
    for layout in layouts.values():
        changes.extend(Change(before, after, "표 머리 축약")
                       for before, after in layout.header_text.values())
    flow = plan_flow(doc, prof, layouts)
    renderer = DocxRenderer(prof, layouts, flow)

    notes = list(notes or [])
    if output is None:
        result = renderer.render(doc)
        notes.extend(result.notes)
        return ConvertResult(document=doc, layouts=layouts, notes=notes, changes=changes,
                             flow=flow)

    say("Word 문서 쓰는 중")
    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result = renderer.save(doc, out_path)
    notes.extend(result.notes)
    return ConvertResult(document=doc, layouts=layouts, output=out_path,
                         notes=notes, changes=changes, flow=flow)


def _insert_dateline(doc: Document, date: str, profile: Profile) -> None:
    """제목 아래 날짜 줄을 넣는다 (이미 있으면 바꾼다)."""
    from datetime import date as _date

    from .ir import Paragraph, Run, plain

    text = date.strip()
    if text.lower() in ("today", "오늘"):
        fmt = profile.text.date_format or "{y}. {m}. {d}"
        today = _date.today()
        text = fmt.format(y=today.year, m=today.month, d=today.day)

    first = doc.blocks[0] if doc.blocks else None
    if isinstance(first, Paragraph) and DATE_LINE.match(plain(first.runs).strip()):
        doc.blocks[0] = Paragraph(runs=[Run(text)])
    else:
        doc.blocks.insert(0, Paragraph(runs=[Run(text)]))


def _resolve_image_paths(doc: Document, base: Path) -> None:
    def walk(blocks):
        for block in blocks:
            if isinstance(block, Image) and not block.src.startswith(("http://", "https://")):
                path = Path(block.src)
                if not path.is_absolute():
                    block.src = str((base / path).resolve())
            for attr in ("blocks",):
                inner = getattr(block, attr, None)
                if inner:
                    walk(inner)
            rows = getattr(block, "rows", None)
            if rows:
                for row in rows:
                    for cell in row.cells:
                        walk(cell.blocks)

    walk(doc.blocks)
