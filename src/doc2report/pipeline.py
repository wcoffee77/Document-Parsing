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
from .transform.structure import fold_headings_into_levels


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


def convert(
    source: str,
    output: str | Path | None = None,
    profile: str | Profile = "default",
    *,
    polish: str = "rules",
    date: str | None = None,
) -> ConvertResult:
    """source(파일 경로 / Confluence URL / '-') → output(.docx).

    date: 제목 아래에 넣을 날짜. "today"(또는 "오늘")면 오늘 날짜를 프로파일 형식으로 넣는다.
    """
    prof = profile if isinstance(profile, Profile) else load_profile(profile)

    loaded = load_source(source)
    doc = parse_markdown(loaded.text, source=loaded.name)
    if loaded.base_dir:
        _resolve_image_paths(doc, loaded.base_dir)
    if date:
        _insert_dateline(doc, date, prof)

    changes: list[Change] = []
    if polish != "none":
        transformed = apply_text_rules(doc, prof)
        doc, changes = transformed.document, transformed.changes
    if prof.text.headings_as_levels:
        # 문구를 다듬은 뒤에 접는다 (제목과 본문은 다듬는 규칙이 다르므로 순서가 중요).
        doc = fold_headings_into_levels(doc)
    if polish == "llm":
        from .transform.llm_polish import polish_document

        doc, llm_changes = polish_document(doc, prof)
        changes.extend(llm_changes)

    layouts = plan_tables(doc, prof)
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
