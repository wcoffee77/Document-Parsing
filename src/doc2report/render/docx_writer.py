"""IR → .docx.

서식 값은 전부 프로파일에서 온다. 이 파일에는 pt·mm·글꼴명 상수가 없다.
표의 열 폭과 글자 크기는 layout 단계가 정해 준 TableLayout을 그대로 쓴다.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from docx import Document as DocxDocument
from docx.enum.section import WD_SECTION
from docx.shared import Emu

from ..ir import (
    Block,
    Callout,
    Cell,
    CodeBlock,
    Document,
    Heading,
    HorizontalRule,
    Image,
    ListItem,
    PageBreak,
    Paragraph,
    Run,
    Table,
    plain,
)
from ..layout.flow import FlowPlan
from ..layout.lines import Line, fit_text
from ..layout.measure import TextMeasurer, is_wide
from ..layout.table_fit import TableLayout, plan_tables
from ..profile import FontSpec, Profile
from ..units import emu_to_dxa
from . import oxml
from .base_template import open_base_template
from .markers import format_marker

from ..ir import DATE_LINE  # noqa: F401  (pipeline이 여기서 가져다 쓴다)

def _base_template(profile: Profile):
    """profile.template(사내 template.docx 경로)이 있으면 그 경로, 없으면 메모리에 든
    기본 템플릿. 파일(.docx)로 두지 않는 이유는 base_template.py 참고."""
    return profile.template or open_base_template()


@dataclass
class RenderResult:
    document: object  # docx.Document
    notes: list[str] = field(default_factory=list)


class DocxRenderer:
    def __init__(self, profile: Profile, layouts: dict[int, TableLayout] | None = None,
                 flow: FlowPlan | None = None, shortener=None):
        self.profile = profile
        self.shortener = shortener  # (문장, 첫 줄에 들어가는 글자 수) → 줄인 문장. 없으면 줄이지 않는다
        self.layouts = layouts or {}
        self.flow = flow or FlowPlan()
        self.notes: list[str] = list(self.flow.notes)
        self._table_seq = 0
        self._figure_seq = 0
        self._counters: dict[int, int] = {}
        self._previous: Block | None = None  # 바로 앞에 무엇이 왔는지 (표 뒤 간격 판단용)
        self._break_before = False  # 다음 본문 문단을 새 쪽에서 시작 (PageBreak)
        self._base_indent = 0  # 마지막 (※가 아닌) 문단의 왼쪽 들여쓰기 — ※ 문단은 이보다 더 들여쓴다
        self._last_item: ListItem | None = None  # 주석 줄의 단계 간격을 윗줄 기준으로 잡기 위해
        self._fit_wrapped = 0    # 엔터로 줄을 나눈 문장 수
        self._fit_condensed = 0  # 글자 간격을 좁힌 줄 수
        self._fit_needs: list[float] = []  # 우리가 더 나눈 줄에서 "한 줄에 넣으려면 필요했던 좁힘"(pt/글자)
        self._fit_warned = False
        self._anchor: _Anchor | None = None  # 주석 상자가 붙을 윗줄 문단
        self._last_para = None               # 줄 맞춤으로 나뉜 문단 중 마지막 것
        self._boxes = 0                      # 만든 텍스트 상자 수
        self._plain_depth: int | None = None  # ※가 아닌 마지막 항목의 단계
        self._shorten_notes: list[str] = []   # LLM 줄임이 실패한 이유(진단용)
        self._orphans: list[tuple[str, int]] = []      # 두세 글자가 다음 줄로 넘어간 문장 (앞 24자, 넘친 글자 수)
        self._shortened: list[tuple[str, str]] = []    # LLM이 줄여 한 줄로 만든 문장 (전, 후)

    # ── 진입점 ──────────────────────────────────────────────────────────

    def render(self, doc: Document) -> RenderResult:
        if not self.layouts:
            self.layouts = plan_tables(doc, self.profile)

        self.docx = DocxDocument(_base_template(self.profile))
        self._apply_document_defaults()
        oxml.apply_page_setup(self.docx.sections[0], self.profile.page)

        if doc.title:
            self._paragraph([Run(doc.title)], self.profile.font("title"))

        blocks = self._dateline(doc.blocks)
        self._blocks(blocks)
        if self._boxes:
            self.notes.append(f"주석 {self._boxes}개를 텍스트 상자로 넣음 (윗줄 아래에 띄움 — Word에서 위치 확인)")
        if self._fit_wrapped or self._fit_condensed:
            self.notes.append(
                f"줄 맞춤: 원문의 줄바꿈 말고 {self._fit_wrapped}개 문장을 더 나눔(이어지는 줄은 윗줄 글자에 맞춤), "
                f"{self._fit_condensed}개 줄은 글자 간격을 좁혀 한 줄로 맞춤 (글꼴 폭 계산 기준 — Word에서 확인)")
            if self._fit_needs:
                needs = sorted(self._fit_needs)
                self.notes.append(
                    f"더 나눈 줄이 한 줄에 들어가려면 글자마다 좁혀야 했던 양(pt): 최소 {needs[0]}, 중앙 "
                    f"{needs[len(needs) // 2]}, 최대 {needs[-1]} (n={len(needs)}) — 최대치 안쪽이면 좁히기로 해결됐을 줄, "
                    f"1.0 근처에 몰려 있으면 글꼴 폭 계산이 실제보다 넓다는 뜻")
        for before, after in self._shortened:
            self.notes.append(f"표현 줄임(한 줄로 맞추려고 LLM이 줄임): '{before}' → '{after}'")
        if self._shorten_notes:
            self.notes.append("표현 줄임 시도 결과(진단): " + " / ".join(self._shorten_notes[:8]))
        if self._orphans:
            detail = ", ".join(f"'{head}…' {n}자" for head, n in self._orphans[:8])
            self.notes.append(
                f"글자 간격을 최대로 좁혀도 한 줄에 못 넣고 두세 글자가 다음 줄로 넘어간 문장 {len(self._orphans)}개 "
                f"(표현을 줄이면 한 줄로 쓸 수 있음 — 넘친 글자 수): {detail}")
        return RenderResult(document=self.docx, notes=self.notes)

    def _dateline(self, blocks: list[Block]) -> list[Block]:
        """제목 바로 아래 날짜 한 줄은 본문이 아니라 날짜 서식으로 쓴다."""
        if not blocks or not self.profile.has_font("date"):
            return blocks
        first = blocks[0]
        if not isinstance(first, Paragraph):
            return blocks
        text = plain(first.runs).strip()
        if not DATE_LINE.match(text):
            return blocks
        self._paragraph([Run(text)], self.profile.font("date"))
        return blocks[1:]

    def save(self, doc: Document, path: str | Path) -> RenderResult:
        result = self.render(doc)
        result.document.save(str(path))
        return result

    # ── 문서 기본값 ─────────────────────────────────────────────────────

    def _apply_document_defaults(self) -> None:
        """Normal 스타일 자체를 프로파일 본문 서식으로 맞춘다.

        표 안 문단처럼 우리가 직접 만들지 않는 요소까지 일관되게 하기 위함이다.
        """
        if self.profile.text.balance_sbcs_dbcs:
            oxml.set_compat_flag(self.docx.settings.element, "balanceSingleByteDoubleByteWidth")
        body = self.profile.font("body")
        style = self.docx.styles["Normal"]
        if body.latin:
            style.font.name = body.latin
        if body.size:
            style.font.size = Emu(body.size)
        if body.east_asia:
            rpr = style.element.get_or_add_rPr()
            rfonts = rpr.get_or_add_rFonts()
            from docx.oxml.ns import qn

            rfonts.set(qn("w:eastAsia"), body.east_asia)
            if not body.latin:
                rfonts.set(qn("w:ascii"), body.east_asia)
                rfonts.set(qn("w:hAnsi"), body.east_asia)

    # ── 블록 디스패치 ───────────────────────────────────────────────────

    def _blocks(self, blocks: list[Block], container=None) -> None:
        for index, block in enumerate(blocks):
            following = blocks[index + 1] if index + 1 < len(blocks) else None
            self._block(block, container, following)
            if container is None:
                self._previous = block

    def _block(self, block: Block, container=None, next_block: Block | None = None) -> None:
        if container is None and not isinstance(block, (ListItem, Paragraph)):
            self._anchor = None  # 표·제목·그림 뒤의 주석은 붙일 윗줄이 없다
        if isinstance(block, Heading):
            self._after_table_gap(self._heading(block, container), container)
        elif isinstance(block, Paragraph):
            text = plain(block.runs).lstrip()
            if container is None and self._is_annotation(text):
                self._annotation(block, next_block)
                return
            spec = self._noted(self.profile.font("body"), text)
            if (container is None and isinstance(self._previous, Heading) and self._previous.page_title
                    and self.profile.has_font("date") and DATE_LINE.match(text.strip())):
                spec = self.profile.font("date")  # 쪽 제목 바로 아래 날짜
            lead = self._note_lead(text) if container is None else None
            head = " " * lead if lead else ""
            is_note = container is None and self._is_note(text)
            indent = self._note_indent() if is_note else int(spec.indent or 0)
            plan = self._fit(block.runs, spec, head, indent=indent, hanging=0, container=container)
            note_gap = self._note_gap(is_note, next_block)
            if plan is not None:
                paragraph = self._emit_fitted(plan, spec, head=head, indent=indent, hanging=0,
                                              space=note_gap, before=None, container=container)
            else:
                runs = ([Run(head)] if head else []) + block.runs  # 들여쓰기 기능 대신 공백으로 (정식보고서)
                paragraph = self._paragraph(runs, spec, container)
                if is_note:
                    paragraph.paragraph_format.left_indent = Emu(indent)
                if note_gap is not None:
                    paragraph.paragraph_format.space_after = Emu(note_gap)
            if container is None and not is_note:
                self._base_indent = 0
            self._after_table_gap(paragraph, container, is_note)
            self._set_anchor(self._last_paragraph(paragraph), spec, head, container)
        elif isinstance(block, ListItem):
            self._list_item(block, container, next_block)
        elif isinstance(block, Table):
            self._table(block, container)
        elif isinstance(block, CodeBlock):
            self._after_table_gap(self._code(block, container), container)
        elif isinstance(block, Callout):
            self._callout(block, container)
        elif isinstance(block, Image):
            self._after_table_gap(self._image(block, container), container)
        elif isinstance(block, HorizontalRule):
            self._after_table_gap(self._rule(container), container)
        elif isinstance(block, PageBreak):
            if container is None and next_block is not None and not isinstance(next_block, Table):
                # 다음 문단에 "쪽 나눔 앞"을 건다 — 나눔 문자를 넣은 빈 문단을 쓰면 새 쪽 맨 위에
                # 빈 줄이 한 줄 생긴다(쪽 제목이 맨 위에 붙지 않음).
                self._break_before = True
                return
            from docx.enum.text import WD_BREAK

            self._new_paragraph(container).add_run().add_break(WD_BREAK.PAGE)

    # ── 개별 블록 ───────────────────────────────────────────────────────

    def _heading(self, block: Heading, container=None) -> None:
        self._counters.clear()  # 제목이 나오면 항목 번호를 다시 1부터
        self._base_indent = 0
        self._last_item = None
        if block.page_title and self.profile.has_font("title"):
            # 입력마다 새 쪽 — 쪽 제목은 문서 제목 서식(큰 글씨·가운데·밑줄)
            return self._paragraph(block.runs, self.profile.font("title"), container)
        key = f"heading{block.level}"
        if not self.profile.has_font(key):
            for level in range(block.level - 1, 0, -1):
                if self.profile.has_font(f"heading{level}"):
                    key = f"heading{level}"
                    break
        return self._paragraph(block.runs, self.profile.font(key), container)

    def _table_gap(self, is_note: bool) -> int | None:
        """표 바로 다음 줄의 앞 간격. 표를 부연하는 ※ 줄은 표에 딸린 줄이라 더 좁게(tables.note_space_before)."""
        rules = self.profile.tables
        if is_note and rules.note_space_before is not None:
            return rules.note_space_before
        return rules.space_after

    def _after_table_gap(self, paragraph, container, is_note: bool = False) -> None:
        """표 바로 뒤 문단은 표와 붙어 보이므로 앞 간격을 확보한다.

        (Word는 표 자체에 '단락 뒤 간격'을 줄 수 없어 다음 문단 쪽에서 띄운다.)
        """
        gap = self._table_gap(is_note)
        if container is None and gap and isinstance(self._previous, Table):
            current = paragraph.paragraph_format.space_before
            paragraph.paragraph_format.space_before = Emu(max(int(current or 0), gap))

    def _list_item(self, block: ListItem, container=None, next_block: Block | None = None) -> None:
        level = self.profile.numbering_level(block.depth)
        spec = self.profile.font("body")
        if level.size:
            spec = spec.resized(level.size)
        rules = self.profile.text
        if (rules.level_bold and level.bold is not None and block.marker != ""
                and (block.marker is None or rules.level_bold_original)):
            # 말머리뿐 아니라 그 항목 문장 전체에 적용된다 ("1. □로 시작하는 문장은 굵은체").
            # 기본은 **도구가 말머리를 붙인 항목에만** — 원문에 말머리가 있던 줄(Confluence·Word·직접 친 □)은
            # 원문 굵기 그대로다(2026-09-30 사용자). 서식이 없는 글(txt)을 정식보고서로 만들 때만
            # level_bold_original로 원문 말머리 줄에도 적용한다(2026-10-01 사용자).
            spec = spec.model_copy(update={"bold": level.bold})
        elif block.from_heading:
            # 단계 굵게를 끈 프로파일: 굵은 건 원문 굵은 글씨(run)와 제목뿐이다.
            spec = spec.model_copy(update={"bold": True})

        marker = self._marker(block, level)
        note_text = block.marker or plain(block.runs).lstrip()
        spec = self._noted(spec, note_text)
        lead = level.lead_spaces
        if container is None:
            note_lead = self._note_lead(note_text)
            lead = note_lead if note_lead is not None else lead
            self._last_item = block
            if not self._is_note(block.marker or plain(block.runs).lstrip()):
                self._plain_depth = block.depth  # ※ 줄 뒤 간격이 "같은 계통"인지 가르는 기준 단계

        indent = level.indent
        if container is None and self._is_note(note_text):
            indent = self._note_indent()
        elif container is None:
            self._base_indent = indent
        # 말머리를 일부러 뺀 항목(꺾쇠 표기)은 내어쓰기 없이 첫 줄과 나머지 줄을 맞춘다.
        hanging = 0 if block.marker == "" else level.hanging
        space = self._item_spacing(block, level, next_block)
        before = self._space_before(block, level, self._is_note(note_text) if container is None else False)
        head = (" " * lead + marker + level.marker_sep) if marker else ""

        plan = self._fit(block.runs, spec, head, indent=indent, hanging=hanging or 0, container=container)
        if plan is not None:
            first = self._emit_fitted(plan, spec, head=head, indent=indent, hanging=hanging or 0,
                                      space=space, before=before, container=container)
            self._set_anchor(self._last_para, spec, head, container)
            return

        paragraph = self._new_paragraph(container)
        oxml.apply_paragraph_format(paragraph, spec, indent=False)
        oxml.set_list_indent(paragraph, indent, hanging)
        if space is not None:
            paragraph.paragraph_format.space_after = Emu(space)
        if before:
            paragraph.paragraph_format.space_before = Emu(before)
        if head:
            run = paragraph.add_run(head)
            oxml.apply_run_format(run, spec)
        self._runs(paragraph, block.runs, spec)
        self._set_anchor(paragraph, spec, head, container)

    def _last_paragraph(self, paragraph):
        """줄 맞춤으로 문단이 여러 개로 나뉘었으면 마지막 것(주석 상자는 마지막 줄 아래에 붙는다)."""
        return self._last_para if self._last_para is not None else paragraph

    def _set_anchor(self, paragraph, spec: FontSpec, head: str, container) -> None:
        """윗줄 문단과 그 높이·글자 시작 위치를 기억해 둔다 — 뒤따르는 `*` 주석이 텍스트 상자로 붙는다."""
        self._last_para = None
        if container is not None or not self.profile.text.annotation_box:
            return
        measure = self._measurer(spec, bool(spec.bold))
        height = measure.line_height(spec.line_spacing or 1.0) if measure.font_available else None
        if height is None:
            self._anchor = None
            return
        after = paragraph.paragraph_format.space_after
        self._anchor = _Anchor(paragraph, int(height), int(measure.width(head)), int(after or 0))

    # ── 줄 맞춤 (정식보고서: 엔터로 줄 나눔 + 글자 간격 좁히기) ────────────

    def _measurer(self, spec: FontSpec, bold: bool) -> TextMeasurer:
        return TextMeasurer(spec.east_asia, spec.latin or spec.east_asia, spec.size, bold=bold,
                            scale=spec.char_scale or 1.0, bold_widen=self.profile.text.fit_bold_factor)

    def _fit(self, runs: list[Run], spec: FontSpec, head: str, *, indent: int, hanging: int,
             container=None, extra: str = ""):
        """문장이 한 줄에 안 들어가면 (줄별 runs, 좁힐 양) 계획을 돌려준다. 계획이 필요 없으면 None.

        head = 첫 줄 앞 접두(공백+말머리), extra = 둘째 줄부터 접두 폭에 더할 글자(주석의 "* ").
        둘째 줄부터는 접두 폭만큼 공백을 쳐서 왼쪽 끝을 윗줄 글자에 맞춘다 — 내어쓰기가 있으면 내어쓰기로.
        """
        rules = self.profile.text
        if not rules.fit_lines or container is not None:
            return None
        text = "".join(run.text for run in runs)
        if not text.strip() or "\t" in text:
            return None
        hard = "\n" in text  # 글쓴이가 엔터로 나눈 줄 — 그 자리를 지키고 이어지는 줄을 윗줄 글자에 맞춘다
        measure = self._measurer(spec, bool(spec.bold))
        if not measure.font_available:
            if not self._fit_warned:
                self.notes.append(f"글꼴({spec.east_asia})을 찾지 못해 줄 맞춤(글자 간격 좁히기·줄 나눔)을 건너뜀")
                self._fit_warned = True
            return None
        latin_min = (rules.latin_min_width or 0.0) * spec.size * (spec.char_scale or 1.0)

        def char_w(measurer: TextMeasurer, c: str) -> float:
            width = measurer.char_width(c)
            # 영문·숫자는 Word에서 더 넓다. 공백은 실측 못 했으니(한글+공백 시험이 줄바꿈 위치를 못 가렸다) 글꼴 폭 그대로 —
            # 접두 공백으로 윗줄 글자에 맞추는 계산도 공백 폭에 기대고 있다.
            return width if is_wide(c) or c.isspace() or not latin_min else max(width, latin_min)

        def text_w(text: str) -> float:
            return sum(char_w(measure, c) for c in text)

        space_w = char_w(measure, " ")
        usable = self.profile.page.usable_width
        head_w = text_w(head)
        if hanging:
            first_room = cont_room = usable - indent - hanging
            cont_spaces, cont_indent = 0, indent + hanging
        else:
            first_room = usable - indent - head_w
            cont_spaces = round((head_w + text_w(extra)) / space_w) if space_w else 0
            cont_room = usable - indent - cont_spaces * space_w
            cont_indent = indent
        def layout(current: list[Run]) -> tuple[str, list[Line], int]:
            current_text = "".join(run.text for run in current)
            widths: list[float] = []
            for run in current:
                widths.extend(char_w(self._measurer(spec, bool(spec.bold or run.bold)), c) for c in run.text)
            made: list[Line] = []
            offset = 0
            count = 0
            for segment in current_text.split("\n"):
                if segment.strip():
                    count += 1
                    made += [Line(offset + line.start, offset + line.end, line.steps, line.need) for line in fit_text(
                        segment, widths[offset:offset + len(segment)],
                        first_room=cont_room if made else first_room, cont_room=cont_room,
                        max_condense=rules.condense_max or 0, step=rules.condense_step or 0,
                        margin=rules.fit_margin, pad=rules.condense_pad or 0,
                        weights=[rules.condense_wide_weight if is_wide(c) else 1.0 for c in segment])]
                offset += len(segment) + 1
            return current_text, made, count

        text, lines, segments = layout(runs)
        if not hard and len(lines) == 2 and lines[1].end - lines[1].start <= rules.orphan_max:
            # 좁히기 한도까지 써도 두세 글자가 다음 줄로 넘어간다 — 표현을 줄여 한 줄로 쓰는 것이 가장 좋다
            # (2026-10-01 사용자). LLM이 있으면 줄이고, 없으면 리포트에 남긴다.
            orphan = lines[1].end - lines[1].start
            shortened = self._shorten(runs, text, lines[0].end - lines[0].start, layout) if rules.shorten_to_fit else None
            if shortened is not None:
                runs = shortened
                text, lines, segments = layout(runs)
            else:
                self._orphans.append((text.strip()[:24], orphan))
        if not hard and len(lines) <= 1 and not any(line.steps for line in lines):
            return None
        if len(lines) > segments:
            self._fit_wrapped += 1  # 글쓴이의 줄바꿈 말고 우리가 더 나눈 문장
            # 어디서 나눴는지 가늠하려고, 한 줄에 넣으려면 글자마다 얼마나 좁혀야 했는지(pt)를 모아 둔다(글자는 안 남김)
            self._fit_needs += [round(line.need / 12700, 2) for line in lines if line.need]
        self._fit_condensed += sum(1 for line in lines if line.steps)
        pieces = [(_slice_runs(runs, line.start, line.end),
                   emu_to_dxa(line.steps * (rules.condense_step or 0))) for line in lines]
        # 글꼴 폭 계산이 Word와 달라 Word가 줄을 한 번 더 바꾸더라도 윗줄 글자에 맞도록, 접두(공백+말머리) 폭만큼
        # 내어쓰기를 같이 준다. 줄이 맞게 들어가면 눈에 안 보인다.
        return _FitPlan(pieces, cont_spaces, cont_indent,
                        first_hang=0 if hanging else int(head_w + text_w(extra)),
                        cont_hang=0 if hanging else int(cont_spaces * space_w))

    def _shorten(self, runs: list[Run], text: str, first_chars: int, layout) -> list[Run] | None:
        """LLM에게 문장을 줄이게 해 한 줄로 들어가면 그 runs를, 아니면 None. 서식이 섞인 문장은 건드리지 않는다."""
        if self.shortener is None or len({(r.bold, r.italic, r.code, r.href) for r in runs if r.text}) > 1:
            return None
        original = text.strip()
        template = next((r for r in runs if r.text), runs[0])
        for target in (first_chars, first_chars - 2, first_chars - 4):  # 한 번에 안 맞으면 더 짧게 다시
            try:
                candidate = (self.shortener(original, target) or "").strip()
            except Exception as exc:
                self._shorten_notes.append(f"'{original[:12]}…' LLM 호출 실패({type(exc).__name__})")
                return None
            if not candidate:
                self._shorten_notes.append(f"'{original[:12]}…' LLM 응답 없음(목표 {target}자)")
                continue
            if len(candidate) >= len(original) or "\n" in candidate:
                self._shorten_notes.append(
                    f"'{original[:12]}…' 응답이 안 짧아짐({len(original)}자 → {len(candidate)}자, 목표 {target}자)")
                continue
            new_runs = [template.copy_with(candidate)]
            if len(layout(new_runs)[1]) == 1:
                self._shortened.append((original, candidate))
                return new_runs
            self._shorten_notes.append(
                f"'{original[:12]}…' 줄였지만 아직 두 줄({len(original)}자 → {len(candidate)}자, 목표 {target}자)")
        self._orphans.append((original[:24], len(original) - first_chars))
        return None

    def _emit_fitted(self, plan: _FitPlan, spec: FontSpec, *, head: str, indent: int, hanging: int,
                     space: int | None, before: int | None, container=None):
        """줄마다 문단 하나 — 글쓴이가 엔터로 줄을 나눈 모양. 첫 문단을 돌려준다."""
        first = None
        for i, (line_runs, condense) in enumerate(plan.pieces):
            last = i == len(plan.pieces) - 1
            paragraph = self._new_paragraph(container)
            oxml.apply_paragraph_format(paragraph, spec, indent=False)
            fmt = paragraph.paragraph_format
            if i == 0:
                first = paragraph
                oxml.set_list_indent(paragraph, indent, hanging or plan.first_hang)
                if before:
                    fmt.space_before = Emu(before)
                if head:
                    oxml.apply_run_format(paragraph.add_run(head), spec)
            else:
                oxml.set_list_indent(paragraph, plan.cont_indent, plan.cont_hang)
                fmt.space_before = Emu(0)
                if plan.cont_spaces:
                    oxml.apply_run_format(paragraph.add_run(" " * plan.cont_spaces), spec)
            self._runs(paragraph, line_runs, spec, condense=condense)
            if last:
                self._last_para = paragraph
                if space is not None:
                    fmt.space_after = Emu(space)
            else:
                fmt.space_after = Emu(0)
                fmt.keep_with_next = True  # 한 문장의 줄들이 쪽 사이에서 떨어지지 않게
        return first

    def _note_lead(self, text: str) -> int | None:
        """※ 줄 앞에 칠 공백 수(text.note_lead_spaces). ※ 줄이 아니거나 안 쓰면 None."""
        rules = self.profile.text
        if rules.note_lead_spaces is not None and any(text.startswith(m) for m in rules.note_marks):
            return rules.note_lead_spaces
        return None

    def _is_annotation(self, text: str) -> bool:
        marks = self.profile.text.annotation_markers
        return bool(marks) and text.startswith(tuple(marks))

    def _is_annotation_block(self, block: Block | None) -> bool:
        return isinstance(block, Paragraph) and self._is_annotation(plain(block.runs).lstrip())

    def _annotation(self, block: Paragraph, next_block: Block | None) -> None:
        """"* 설명" 주석 — 윗줄에 딸린 파란 작은 글씨 문단. 단계가 바뀌는 간격은 주석이 아니라 윗줄 기준이다."""
        rules = self.profile.text
        spec = self.profile.font("annotation")
        if self._annotation_box(block, spec, next_block):
            return
        head = " " * rules.annotation_lead_spaces
        indent = int(spec.indent or 0)
        gap = self._annotation_gap(next_block)
        plan = self._fit(block.runs, spec, head, indent=indent, hanging=0, extra=rules.annotation_mark + " ")
        if plan is not None:
            paragraph = self._emit_fitted(plan, spec, head=head, indent=indent, hanging=0,
                                          space=gap, before=None)
        else:
            paragraph = self._paragraph(([Run(head)] if head else []) + block.runs, spec)
            if gap is not None:
                paragraph.paragraph_format.space_after = Emu(gap)
        self._after_table_gap(paragraph, None)

    def _annotation_box(self, block: Paragraph, spec: FontSpec, next_block: Block | None) -> bool:
        """주석을 윗줄 바로 아래의 텍스트 상자로 띄운다. 못 만들면 False — 일반 문단 주석으로 쓴다."""
        rules = self.profile.text
        anchor = self._anchor
        if not rules.annotation_box or anchor is None:
            return False
        measure = self._measurer(spec, bool(spec.bold))
        line = measure.line_height(spec.line_spacing or 1.0) if measure.font_available else None
        text = " ".join("".join(run.text for run in block.runs).split("\n")).strip()
        if line is None or not text:
            return False
        room = self.profile.page.usable_width - anchor.x
        if room <= 0:
            return False
        widths = [measure.char_width(c) for c in text]
        lines = fit_text(text, widths, first_room=room, cont_room=room, margin=rules.fit_margin)
        height = int(max(line, rules.annotation_box_height or 0) * len(lines))   # 한 줄 최소 높이 — 글자에 딱 맞으면 겹쳐 보인다
        runs = [(run.text.replace("\n", " "), bool(run.bold)) for run in block.runs if run.text]
        runs[0] = (runs[0][0].lstrip(), runs[0][1])
        self._boxes += 1
        oxml.add_text_box(anchor.paragraph, runs=runs, spec=spec, x=anchor.x, y=anchor.line + anchor.used,
                          width=int(room), height=height, number=self._boxes)
        anchor.used += height
        gap = self._annotation_gap(next_block)
        anchor.paragraph.paragraph_format.space_after = Emu(anchor.after + anchor.used + int(gap or 0))
        return True

    def _annotation_gap(self, next_block: Block | None) -> int | None:
        if self._is_annotation_block(next_block):
            return 0
        fixed = self.profile.text.gap_after_annotation
        if fixed is not None:
            return fixed  # 단락 앞 대신 주석(윗줄) 뒤에 간격을 둔다 — 다음 항목과 붙어 보이지 않게
        last = self._last_item
        if last is None:
            return None
        return self._transition_gap(last.depth, next_block)

    def _transition_gap(self, depth: int, next_block: Block | None) -> int | None:
        """윗줄(단계 depth) 뒤 간격 — 같은 단계가 이어지면 space_after(6pt), 더 얕은 단계로 올라가면 level_up(12pt,
        지면에 여유가 있으면 18pt), 내려가거나 그 밖이면 level_change(2026-10-01 사용자). ※·주석에도 똑같이 적용한다."""
        level = self.profile.numbering_level(depth)
        relaxed = self.flow.relaxed
        if isinstance(next_block, ListItem):
            if next_block.depth == depth:
                return level.space_after
            if next_block.depth < depth:
                return level.level_up_space(relaxed)
        return level.level_change_space(relaxed)

    def _is_note(self, text: str) -> bool:
        rules = self.profile.text
        return bool((rules.note_indent or rules.note_lead_spaces is not None)
                    and any(text.startswith(m) for m in rules.note_marks))

    def _note_gap(self, is_note: bool, next_block: Block | None) -> int | None:
        """※ 줄 다음에 항목이 이어지면 ※ 줄의 단락 뒤에 간격을 둔다(text.gap_after_note)."""
        rules = self.profile.text
        gap = rules.gap_after_note
        if not is_note or next_block is None or self._is_note_block(next_block):
            return None
        if gap is None:  # 따로 정한 값이 없으면 일반 항목과 같은 규칙(같은 단계 6pt, 올라가면 12·18pt)
            return (self._transition_gap(self._plain_depth, next_block)
                    if self._plain_depth is not None else None)
        same = rules.gap_after_note_same_level
        if (same is not None and isinstance(next_block, ListItem) and self._plain_depth is not None
                and next_block.depth == self._plain_depth):
            return same  # 같은 계통(단계)으로 이어진다 — 좁게
        return gap

    def _is_note_block(self, block: Block | None) -> bool:
        if isinstance(block, ListItem):
            return self._is_note(block.marker or plain(block.runs).lstrip())
        return isinstance(block, Paragraph) and self._is_note(plain(block.runs).lstrip())

    def _note_indent(self) -> int:
        """※ 참고사항: 바로 윗줄 문단의 들여쓰기 + text.note_indent (2026-09-29 사용자: +0.4cm)."""
        return self._base_indent + (self.profile.text.note_indent or 0)

    def _noted(self, spec: FontSpec, text: str) -> FontSpec:
        """※ 같은 참고사항 표시로 시작하면 본문보다 text.note_size_delta만큼 작게."""
        rules = self.profile.text
        if rules.note_size_delta and any(text.startswith(m) for m in rules.note_marks):
            return spec.resized(max(spec.size - rules.note_size_delta, 1))
        return spec

    def _marker(self, block: ListItem, level) -> str:
        """말머리 문자열. {n} 같은 자리표시자가 있으면 깊이별 번호를 매긴다."""
        template = (level.ordered_marker if block.ordered and level.ordered_marker
                    else level.marker)
        if block.marker is not None:
            # 원문 말머리를 그대로 쓴다. 번호 단계면 번호는 세어 둬야 다음 자동 번호가 맞는다.
            if template and "{" in template and block.marker:
                self._next_number(block.depth)
            return block.marker
        if not template:
            return ""
        if "{" not in template:
            return template
        return format_marker(template, self._next_number(block.depth))

    def _next_number(self, depth: int) -> int:
        for deeper in [d for d in self._counters if d > depth]:
            del self._counters[deeper]  # 상위 단계로 돌아오면 하위 번호는 초기화
        self._counters[depth] = self._counters.get(depth, 0) + 1
        return self._counters[depth]

    def _item_spacing(self, block: ListItem, level, next_block: Block | None) -> int | None:
        """단계가 바뀌는 자리(1. → □ → -)에서만 단락 뒤 간격을 준다."""
        if self._is_annotation_block(next_block):
            return 0  # 주석이 윗줄에 딸려 붙는다 — 단계 간격은 주석 줄이 대신 준다
        rules = self.profile.text
        note = self._note_gap(self._is_note(block.marker or plain(block.runs).lstrip()), next_block)
        if note is not None:
            return note
        if (rules.gap_after_section is not None and isinstance(next_block, ListItem)
                and next_block.depth == 0 and block.depth > 0):
            return rules.gap_after_section  # 새 절(3.) 앞 간격은 단락 앞이 아니라 윗줄 뒤로
        return self._transition_gap(block.depth, next_block)

    def _space_before(self, block: ListItem, level, is_note: bool = False) -> int:
        """새 절이 시작되는 자리(… - 다음의 2.)와 표 바로 뒤를 넉넉히 띄운다."""
        previous = self._previous
        if previous is None:
            return 0  # 문서 첫 항목은 제목·날짜 간격으로 충분하다
        if self._is_annotation_block(previous) and self._last_item is not None:
            previous = self._last_item  # 주석은 건너뛰고 그 윗줄로 판단

        before = 0
        deeper_before = isinstance(previous, ListItem) and previous.depth > block.depth
        if deeper_before and level.space_before:
            before = level.space_before
        gap = self._table_gap(is_note)
        if isinstance(previous, Table) and gap:
            before = max(before, gap)
        return before

    def _code(self, block: CodeBlock, container=None):
        spec = self.profile.font("code")
        paragraph = self._new_paragraph(container)
        oxml.apply_paragraph_format(paragraph, spec)
        lines = block.text.splitlines() or [""]
        for i, line in enumerate(lines):
            run = paragraph.add_run()
            if i:
                run.add_break()
            run.add_text(line)
            oxml.apply_run_format(run, spec)
        if self.profile.tables.border_width:
            oxml.add_border(paragraph, "left", self.profile.tables.border_width,
                            self.profile.tables.border_color, space="6")
        return paragraph

    def _callout(self, block: Callout, container=None) -> None:
        spec = self.profile.font("callout")
        start = len(self._paragraphs(container))
        for inner in block.blocks:
            if isinstance(inner, Paragraph):
                self._paragraph(inner.runs, spec, container)
            else:
                self._block(inner, container)
        paragraphs = self._paragraphs(container)
        if len(paragraphs) > start:
            self._after_table_gap(paragraphs[start], container)
        if self.profile.tables.border_width:
            for paragraph in paragraphs[start:]:
                oxml.add_border(paragraph, "left", self.profile.tables.border_width,
                                self.profile.tables.border_color, space="6")

    def _image(self, block: Image, container=None):
        path = Path(block.src)
        if not path.exists():
            self.notes.append(f"이미지를 찾을 수 없어 건너뜀: {block.src}")
            return None
        paragraph = self._new_paragraph(container)
        try:
            paragraph.add_run().add_picture(str(path), width=Emu(self._image_width(block)))
        except Exception as exc:  # 형식 미지원 등
            self.notes.append(f"이미지 삽입 실패({block.src}): {exc}")
            return None
        oxml.apply_paragraph_format(paragraph, self.profile.font("caption"))
        if block.caption:
            self._figure_seq += 1
            self._paragraph([Run(f"[그림 {self._figure_seq}] {block.caption}")],
                            self.profile.font("caption"), container)
        return paragraph

    def _image_width(self, block: Image) -> int:
        usable = self.profile.page.usable_width
        if not block.width_px:
            return usable
        from ..units import parse_length

        natural = parse_length(block.width_px, default_unit="px")
        return min(natural, usable)

    def _rule(self, container=None):
        paragraph = self._new_paragraph(container)
        rules = self.profile.tables
        if rules.border_width:
            oxml.add_border(paragraph, "bottom", rules.border_width, rules.border_color)
        return paragraph

    # ── 표 ──────────────────────────────────────────────────────────────

    def _table(self, block: Table, container=None) -> None:
        layout = self.layouts.get(id(block))
        if layout is None:
            layout = plan_tables(Document(blocks=[block]), self.profile)[id(block)]
        self.notes.extend(f"표 {self._table_seq + 1}: {note}" for note in layout.notes)
        if container is None:
            self.notes.append(
                f"표 {self._table_seq + 1} 위치: {self.profile.tables.align} 정렬, 왼쪽 끝 {layout.indent / 36000:.1f}mm"
                f"(윗줄 글자 시작), 폭 {layout.total_width / 36000:.1f}mm")

        section_switched = layout.landscape and container is None
        if section_switched:
            section = self.docx.add_section(WD_SECTION.NEW_PAGE)
            oxml.apply_page_setup(section, self.profile.page.landscape())

        self._table_seq += 1
        if block.caption:
            spec = self.profile.font("caption")
            if block.caption_align:
                spec = spec.model_copy(update={"align": block.caption_align})
            caption = self._paragraph([Run(block.caption)], spec, container)
            if layout.indent and container is None:  # 표 제목도 표와 같은 왼쪽 끝(가운데면 표 폭의 가운데)
                caption.paragraph_format.left_indent = Emu(layout.indent)

        cols = block.col_count
        rows = len(block.rows)
        if cols == 0 or rows == 0:
            return

        target = container if container is not None else self.docx
        table = target.add_table(rows=rows, cols=cols)
        oxml.set_fixed_layout(table, layout.total_width, self.profile.tables.align, layout.indent)
        oxml.set_table_borders(table, self.profile.tables)
        oxml.set_cell_margins(table, layout.cell_margin_x, self.profile.tables.cell_margin_y)
        oxml.set_grid(table, layout.col_widths)

        self._fill_cells(table, block, layout)
        oxml.set_header_rule(table, block.header_rows, self.profile.tables.header_rule_width,
                             self.profile.tables.border_color)

        rules = self.profile.tables
        min_height = rules.min_row_height(self.flow.relaxed)
        for index, row in enumerate(table.rows):
            if rules.keep_row_together:
                oxml.forbid_row_split(row)
            if rules.repeat_header and index < block.header_rows:
                oxml.mark_header_row(row)
            if min_height:
                oxml.set_min_row_height(row, min_height)

        self._table_notes(block, container)

        if section_switched:
            back = self.docx.add_section(WD_SECTION.NEW_PAGE)
            oxml.apply_page_setup(back, self.profile.page)

    def _table_notes(self, block: Table, container=None) -> None:
        """표 바로 아래 주석 — "* 측정 기준은 …" 형태로 작은 글씨."""
        if not block.notes:
            return
        spec = self.profile.font("table_note")
        marker = self.profile.tables.note_marker
        for runs in block.notes:
            prefix = [Run(f"{marker} ")] if marker else []
            self._paragraph(prefix + list(runs), spec, container)

    def _fill_cells(self, table, block: Table, layout: TableLayout) -> None:
        occupied: set[tuple[int, int]] = set()
        for r, row in enumerate(block.rows):
            col = 0
            for index, cell in enumerate(row.cells):
                override = layout.header_text.get((r, index))
                if override:
                    cell = _with_text(cell, override[1])
                align_override = layout.cell_align.get((r, index))
                if align_override and not cell.align:
                    cell = replace(cell, align=align_override)
                while (r, col) in occupied:
                    col += 1
                if col >= len(layout.col_widths):
                    break
                end_row = min(r + cell.rowspan - 1, len(table.rows) - 1)
                end_col = min(col + cell.colspan - 1, len(layout.col_widths) - 1)
                for rr in range(r, end_row + 1):
                    for cc in range(col, end_col + 1):
                        occupied.add((rr, cc))

                target = table.cell(r, col)
                if (end_row, end_col) != (r, col):
                    target = target.merge(table.cell(end_row, end_col))
                self._fill_cell(target, cell, layout,
                                sum(layout.col_widths[col : end_col + 1]),
                                font_override=layout.cell_font.get((r, index)))
                col = end_col + 1

    def _fill_cell(self, docx_cell, cell: Cell, layout: TableLayout, width: int,
                  *, font_override: tuple[int, float] | None = None) -> None:
        oxml.set_cell_width(docx_cell, width)
        oxml.set_vertical_align(docx_cell, self.profile.tables.valign)
        if cell.is_header and self.profile.tables.header_shading:
            oxml.shade_cell(docx_cell, self.profile.tables.header_shading)

        size, scale = font_override or (layout.font_size, layout.char_scale)
        spec = self.profile.font("table_header" if cell.is_header else "table")
        spec = spec.resized(size)
        if scale != (spec.char_scale or 1.0):
            spec = spec.model_copy(update={"char_scale": scale})
        if cell.align:
            spec = spec.model_copy(update={"align": cell.align})

        # python-docx가 만들어 둔 빈 문단을 첫 블록에 재사용한다.
        blocks = cell.blocks or [Paragraph(runs=[])]
        for i, inner in enumerate(blocks):
            reuse = docx_cell.paragraphs[0] if i == 0 else None
            if isinstance(inner, Paragraph):
                self._paragraph(inner.runs, spec, docx_cell, reuse=reuse)
            elif isinstance(inner, Heading):
                # 셀 안 제목은 본문용 제목 서식(14pt·앞 간격)이 아니라 표 글자 크기의 굵은 글씨로.
                bold = [replace(run, bold=True) for run in inner.runs]
                self._paragraph(bold, spec, docx_cell, reuse=reuse)
            elif isinstance(inner, ListItem):
                self._paragraph(self._cell_item_runs(inner), spec, docx_cell, reuse=reuse)
            else:
                self._block(inner, docx_cell)
        _drop_leading_blank(docx_cell)

    def _cell_item_runs(self, item: ListItem) -> list[Run]:
        """표 안 목록 항목: 본문용 번호 체계(1. □ -)와 들여쓰기를 쓰면 좁은 칸에서 깨지고
        글자도 본문 크기로 나온다 — 원문 말머리(또는 tables.cell_list_markers)를 앞에 붙여
        표 글자 서식으로 그대로 쓴다."""
        markers = self.profile.tables.cell_list_markers
        marker = item.marker or (markers[min(item.depth, len(markers) - 1)] if markers else "")
        head = [Run(marker + " ")] if marker else []
        return head + item.runs

    # ── 문단/런 ─────────────────────────────────────────────────────────

    def _paragraph(self, runs: list[Run], spec: FontSpec, container=None, reuse=None):
        paragraph = reuse if reuse is not None else self._new_paragraph(container)
        oxml.apply_paragraph_format(paragraph, spec)
        self._runs(paragraph, runs, spec)
        return paragraph

    def _runs(self, paragraph, runs: list[Run], spec: FontSpec, condense: int = 0) -> None:
        for item in runs:
            if not item.text:
                continue
            run_spec = spec
            if item.code and self.profile.has_font("code"):
                code = self.profile.font("code")
                run_spec = code.model_copy(update={"size": spec.size})
            updates: dict = {}
            if item.bold:
                updates["bold"] = True
            if item.italic:
                updates["italic"] = True
            if item.href and self.profile.has_font("link"):
                link = self.profile.font("link")
                updates.update({k: v for k, v in link.model_dump().items()
                                if v is not None and k in ("color", "underline")})
            if updates:
                run_spec = run_spec.model_copy(update=updates)
            run = paragraph.add_run(item.text)
            oxml.apply_run_format(run, run_spec)
            if condense:
                oxml.set_char_spacing(run, -condense)

    def _new_paragraph(self, container=None):
        target = container if container is not None else self.docx
        paragraph = target.add_paragraph()
        if container is None and self._break_before:
            paragraph.paragraph_format.page_break_before = True
            self._break_before = False
        return paragraph

    def _paragraphs(self, container=None):
        target = container if container is not None else self.docx
        return target.paragraphs


@dataclass
class _Anchor:
    paragraph: object   # 주석 상자가 붙을 윗줄 문단(docx)
    line: int           # 그 문단의 한 줄 높이(EMU) — 상자는 이 아래에 놓인다
    x: int              # 윗줄 글자가 시작하는 위치(본문 왼쪽 끝에서, EMU)
    after: int          # 문단 원래의 단락 뒤 간격
    used: int = 0       # 이미 붙인 상자들의 높이 합


@dataclass
class _FitPlan:
    pieces: list[tuple[list[Run], int]]   # (줄의 runs, 좁힌 양 1/20pt)
    cont_spaces: int                      # 둘째 줄부터 앞에 칠 공백 수
    cont_indent: int                      # 둘째 줄부터 문단 왼쪽 들여쓰기
    first_hang: int = 0                   # 첫 줄 접두 폭 — Word가 스스로 줄을 바꿀 때 이어지는 줄이 맞을 자리
    cont_hang: int = 0                    # 둘째 줄부터의 접두(공백) 폭


def _slice_runs(runs: list[Run], start: int, end: int) -> list[Run]:
    out: list[Run] = []
    pos = 0
    for run in runs:
        lo, hi = max(start, pos), min(end, pos + len(run.text))
        if lo < hi:
            out.append(run.copy_with(run.text[lo - pos:hi - pos]))
        pos += len(run.text)
    return out


def _drop_leading_blank(docx_cell) -> None:
    """첫 블록이 문단이 아니어서(코드·이미지·인용 등) 재사용 못 한 빈 첫 문단은 지운다 —
    남으면 셀 맨 위에 엔터 한 줄이 들어간 것처럼 보인다. 셀은 문단으로 끝나야 하므로
    다른 문단이 뒤에 있을 때만 지운다."""
    paragraphs = docx_cell._tc.p_lst
    if len(paragraphs) > 1 and not "".join(paragraphs[0].itertext()).strip():
        docx_cell._tc.remove(paragraphs[0])


def _with_text(cell: Cell, text: str) -> Cell:
    """머리 축약 결과로 바꾼 셀 (서식은 원래 첫 런을 따른다). IR 원본은 건드리지 않는다."""
    template = next((run for block in cell.blocks if isinstance(block, Paragraph)
                     for run in block.runs), Run(""))
    return replace(cell, blocks=[Paragraph(runs=[template.copy_with(text)])])
