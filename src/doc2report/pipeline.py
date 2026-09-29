"""전체 변환 오케스트레이션.

CLI·GUI·MCP 무엇을 붙이든 이 convert() 하나만 호출하면 되도록 유지한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .ir import Document, Image
from .layout.flow import FlowPlan, plan_flow
from .layout.table_fit import TableLayout, plan_tables
from .parsers.markdown import parse_markdown
from .profile import Profile, load_profile
from .render.docx_writer import DATE_LINE, DocxRenderer
from .sources import load_source
from .transform import Change, apply_text_rules
from .transform.structure import (
    attach_table_captions,
    attach_table_notes,
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


def auto_profile(source: str) -> str:
    """프로파일을 안 골랐을 때의 기본값. Confluence는 글이 많고 이미 다듬어진 문장이라
    규칙이 다르다(2026-09-29 사용자): 원문 말머리 유지·문장 다듬기 없음·12pt 본문."""
    return "confluence" if source.startswith(("http://", "https://")) else "default"


def convert(
    source: str,
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
    if profile is None:
        profile = auto_profile(source)
    prof = profile if isinstance(profile, Profile) else load_profile(profile)
    polish = polish or prof.text.polish or "rules"

    loaded = load_source(source)
    if loaded.format == "confluence_storage":
        from .parsers.confluence_storage import parse_confluence_storage

        parsed = parse_confluence_storage(loaded.text, source=loaded.name, title=loaded.title)
        doc = parsed.document
        loaded.notes.extend(parsed.notes)
    else:
        doc = parse_markdown(loaded.text, source=loaded.name)
    if loaded.base_dir:
        _resolve_image_paths(doc, loaded.base_dir)
    if date:
        _insert_dateline(doc, date, prof)

    changes: list[Change] = []
    if polish != "none":
        transformed = apply_text_rules(doc, prof)
        doc, changes = transformed.document, transformed.changes
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
            marker_depths=prof.marker_depths())
        changes.extend(fold_changes)
    if polish == "llm":
        from .transform.llm_polish import polish_document

        doc, llm_changes = polish_document(doc, prof)
        changes.extend(llm_changes)

    layouts = plan_tables(doc, prof)
    for layout in layouts.values():
        changes.extend(Change(before, after, "표 머리 축약")
                       for before, after in layout.header_text.values())
    flow = plan_flow(doc, prof, layouts)
    renderer = DocxRenderer(prof, layouts, flow)

    notes = list(loaded.notes)
    if output is None:
        result = renderer.render(doc)
        notes.extend(result.notes)
        return ConvertResult(document=doc, layouts=layouts, notes=notes, changes=changes,
                             flow=flow)

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
