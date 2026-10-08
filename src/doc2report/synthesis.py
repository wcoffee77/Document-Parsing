"""다문서 종합(D단계, 2026-10-08): 같은 주제를 다룬 여러 보고서(.docx·Confluence·.txt) → 핵심만 뽑은 새 보고서.

이어 붙이기가 아니라 **주제별로 다시 구성**한다(현황 → 위험 → 검토안 → 대응). 역할 분담은 줄글 다듬기(drafting.py)와 같다:
- LLM: 어떤 사실을 남길지 고르고, 문서 간 중복을 합치고, 보고서 말투로 쓴다. 줄마다 근거 문장 번호(src)를 단다.
- 파이썬: 줄마다 근거 문장과 대조해 숫자·날짜·방향·확정 여부를 검증하고(drafting.review), 걸리면 다시 쓰게 하며, 끝내 걸리면 원문 문장으로
  되돌린다. 말머리·쌍점 정렬·표 방향·날짜 표기 같은 서식 후처리도 drafting의 것을 그대로 쓰고, 최종 .docx는 formal 서식(줄 맞춤 포함)이다.
- 줄글 다듬기와 다른 점: 원문 문장을 다 쓰지 않아도 되고(빠짐 점검 끔), 문서마다 값이 다르면 **가장 나중 문서**의 값을 쓰며,
  분량 목표(쪽 수)를 지시한다. 뺀 문장 중 숫자가 든 것은 --report에 남는다(사람이 확인).
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field

from .drafting import (REWRITE_SYSTEM, Ask, DraftResult, Group, Section, Structure, SynthSpec, rewrite,
                       system_prompt)
from .ir import (DATE_LINE, Callout, Document, Heading, ListItem, Paragraph, Table, plain)

DEFAULT_PAGES = (1, 2)
_SECTION_ITEM = re.compile(r"^\d{1,2}\.$")
# 글자로 쳐 둔 말머리 — 정식보고서 .docx는 목록 서식이 아니라 "□ …", "  - …"를 글자로 친 문단이다
_TYPED_MARK = re.compile(r"^(?P<lead>[ \t\u3000]*)(?P<mark>\d{1,2}\.(?=\s)|\(\d{1,2}\)|[①-⑳]|[□■ㅁ○●◦◆◇▶▷►※→∙·ㆍ‧•*＊]|[-–—](?=\s))\s*(?P<body>\S.*)$")
# 말머리 종류별 기본 단계(맥락 표시용) — 앞 공백이 있으면 그것을 따른다
_MARK_DEPTH = {"□": 0, "■": 0, "ㅁ": 0, "○": 0, "①": 0, "-": 1, "–": 1, "—": 1, "→": 1, "∙": 2, "·": 2, "ㆍ": 2, "•": 2}
_DATE = re.compile(r"(\d{4})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})")

# 종합 모드에서 REWRITE_SYSTEM의 "정보를 빼지 않는다" 규칙을 바꿔 끼운다 — 종합은 핵심만 골라야 한다.
SYNTH_RULE2 = """[절대 규칙 2 — 쓴 줄의 사실은 빠짐없이, 쓰지 않을 문장은 src에 넣지 않는다]
- 문장을 src로 쓰면 그 문장에서 가져온 사실의 숫자·조건·단서(약, 예정, 검토 中, 미정)를 줄에 그대로 남깁니다.
  쓰고 싶지 않은 사실이면 줄에 넣지 말고 그 문장을 src에서 뺍니다(원문 문장을 일부만 쓰는 것은 괜찮습니다).
- 상급자가 이해하고 결정하는 데 필요한 핵심만 고릅니다. 과정·세부 근거·같은 말 반복·이전 시점의 값은 빼도 됩니다.
  어느 줄에도 쓰지 않은 문장은 dropped에 넣거나 그냥 둡니다.
- '빨라야 ~가능'(가장 이른 시점)과 '~에 추진'(계획)은 다른 사실입니다. 섞지 말고 각각 씁니다.
"""

SYNTH_RULES = """[종합 규칙 — 여러 문서를 새 보고서 하나로]
- 입력은 같은 주제를 다룬 문서 여러 개(날짜 오름차순, 아래 문서일수록 최신)입니다. 문서별로 이어 붙이지 말고, 읽는 사람이 한 번에 이해하도록
  **주제별로 새로 구성**합니다(예: 1. 현황 / 2. 위험·쟁점 / 3. 검토안 / 4. 대응 계획·결정 요청). 절 이름은 내용에 맞게 정합니다.
- 같은 사실이 여러 문서에 있으면 한 번만 쓰고 src에는 근거 문장을 모두 적습니다.
- 같은 항목의 값이 문서마다 다르면 **가장 나중 문서의 값**을 씁니다. 바뀐 것이 의미 있으면 (기존 26주 → 28주)처럼 변화를 괄호로 남기고,
  기준 시점이 있으면 함께 씁니다(10.1 기준). 이전 값만 쓰고 최신 값을 빼지 않습니다.
- 계획·예정이 나중 문서에서 완료·변경됐으면 현재 상태로 씁니다(예정 → 완료, 일정 연장).
- 아직 정해지지 않은 사항(검토 中, 미확정, 통보 없음, 협의 필요)은 미확정으로 씁니다. 확정·완료처럼 쓰지 않습니다.
- 문서에 없는 숫자를 계산해 만들지 않습니다(합계·비율·증감을 새로 구하지 않음). 원문에 있는 숫자만 씁니다.
- 문서 제목·작성 날짜·"~에 따르면" 같은 출처 표기는 쓰지 않습니다(내부 문서에 근거한 보고서입니다).
- 분량은 공백 뺀 {low}~{high}자(정식보고서 Word 약 {pages}쪽) 안으로 합니다. 많으면 핵심 위주로 줄이되 결정에 필요한 수치와 쟁점은 남깁니다.
- 대안 비교가 있으면 비교표(대안이 열)나 ①②③ 줄로 씁니다. 결정이 필요한 사항은 마지막 절에 "결정 요청"으로 모읍니다.

[종합 예시]
원문:
=== 문서 1: 사무실 이전 검토 (2026. 5. 7) ===
[1] 임대 계약이 12월 말에 만료된다.
[2] 후보지는 월 임대료 4,200만원을 제시했다.
[3] 입주는 10월 중순 가능할 것으로 알려졌으나 확정은 아니다.
=== 문서 2: 사무실 이전 진행 (2026. 6. 3) ===
[4] 임대료 협상 결과 월 3,900만원으로 합의했다.
[5] 입주 시점은 11월 초로 확정됐다.
[6] 이전 비용은 2.4억원이며 이사 업체는 선정 중이다.
[7] 회의에서는 여러 의견이 있었다.
출력:
{"title": "사무실 이전 추진 현황", "lines": [
 {"m": "1.", "text": "추진 현황", "src": [1, 4]},
 {"m": "□", "text": "임대 계약 12월 말 만료, 후보지 계약 조건 합의", "src": [1, 4]},
 {"m": "-", "text": "월 임대료 : 3,900만원 (당초 제시 4,200만원 → 협상)", "src": [2, 4]},
 {"m": "-", "text": "입주 시점 : 11월 초 확정 (기존 10월 중순 예상)", "src": [3, 5]},
 {"m": "□", "text": "이전 비용 및 업체", "src": [6]},
 {"m": "-", "text": "이전 비용 : 2.4억원", "src": [6]},
 {"m": "-", "text": "이사 업체 : 선정 中", "src": [6]}],
 "dropped": [7]}
"""


@dataclass
class SourceDoc:
    title: str
    date: str                                  # 원문 표기 그대로 ("2026. 9. 12"), 없으면 ""
    when: datetime.date | None
    items: list[tuple[str, int, str, str]] = field(default_factory=list)
    # (종류, 깊이, 말머리, 글): 종류 = "절"(번호 제목 — 문장이 아니라 맥락) | "문장"
    origin: str = ""


def _parse_date(text: str) -> datetime.date | None:
    match = _DATE.search(text or "")
    if not match:
        return None
    try:
        return datetime.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def split_typed_marker(text: str) -> tuple[str, str, int]:
    """(말머리, 본문, 단계). 말머리가 없으면 ("", 전체, 0). 단계는 앞 공백(2칸당 1단계)이 있으면 그것, 없으면 말머리 종류로."""
    match = _TYPED_MARK.match(text.replace("\n", " "))
    if match is None:
        return "", text.strip(), 0
    mark, body = match.group("mark"), match.group("body").strip()
    lead = len(match.group("lead").replace("\t", "    ").replace("\u3000", "  "))
    if _SECTION_ITEM.match(mark):
        return mark, body, 0
    depth = (lead - 1) // 2 if lead else _MARK_DEPTH.get(mark, 1)
    return mark, body, max(0, depth)


def _cell_text(cell) -> str:
    parts = []
    for block in cell.blocks:
        if isinstance(block, (Paragraph, ListItem, Heading)):
            text = plain(block.runs).strip()
            if text:
                parts.append(text)
    return " / ".join(parts)


def _table_sentences(table: Table) -> list[str]:
    """표는 행마다 한 문장: "구분 '비용': (1안)=…; (2안)=…" — 칸 값은 그대로 두고 어느 열의 값인지만 붙인다."""
    rows = [[_cell_text(c) for c in row.cells] for row in table.rows]
    if len(rows) < 2:
        return [" | ".join(r) for r in rows if any(r)]
    head, body = rows[0], rows[1:]
    out = []
    for row in body:
        if not any(row):
            continue
        label = row[0]
        pairs = "; ".join(f"{head[i] if i < len(head) and head[i] else f'열{i}'}={v}" for i, v in enumerate(row) if i and v)
        out.append(f"표 '{head[0] or '구분'}' = {label} → {pairs}" if label else f"표: {pairs}")
    return out


def flatten(doc: Document, origin: str = "") -> SourceDoc:
    """IR 문서 → 번호 붙일 문장 목록(+ 맥락용 절 제목). 서식은 버리고 글만."""
    title = (doc.title or "").strip()
    date = ""
    items: list[tuple[str, int, str, str]] = []

    def walk(blocks, depth_shift: int = 0):
        nonlocal title, date
        for block in blocks:
            if isinstance(block, Heading):
                text = plain(block.runs).strip()
                if block.page_title or (not title and block.level == 1 and not items):
                    title = title or text
                elif text:
                    items.append(("절", 0, "", text))
            elif isinstance(block, Paragraph):
                raw = plain(block.runs)
                text = raw.strip()
                if not text:
                    continue
                if DATE_LINE.match(text):
                    date = date or text
                    continue
                if re.fullmatch(r"[-–—]\s*이\s*상\s*[-–—]", text):
                    continue
                mark, body, depth = split_typed_marker(raw)
                if _SECTION_ITEM.match(mark):
                    items.append(("절", 0, mark, body))
                else:
                    items.append(("문장", depth, mark, body))
            elif isinstance(block, ListItem):
                text = plain(block.runs).strip()
                if not text:
                    continue
                mark = (block.marker or "").strip()
                if (_SECTION_ITEM.match(mark) or (block.ordered and block.depth == 0 and not block.marker)) and block.depth == 0:
                    items.append(("절", 0, mark, text))
                else:
                    items.append(("문장", block.depth, mark, text))
            elif isinstance(block, Table):
                head = [_cell_text(c) for c in block.rows[0].cells] if block.rows else []
                if head:
                    items.append(("절", 0, "표", "열: " + " | ".join(h for h in head if h)))
                for sentence in _table_sentences(block):
                    items.append(("문장", 1, "표", sentence))
                for note in block.notes:
                    items.append(("문장", 1, "※", plain(note).strip()))
            elif isinstance(block, Callout):
                walk(block.blocks)

    walk(doc.blocks)
    return SourceDoc(title or origin, date, _parse_date(date), items, origin)


def order_docs(docs: list[SourceDoc]) -> list[SourceDoc]:
    """날짜 오름차순(최신이 아래). 날짜가 없는 문서가 있으면 입력 순서를 그대로 둔다."""
    if all(d.when for d in docs):
        return sorted(docs, key=lambda d: d.when)
    return list(docs)


def page_chars(pages: tuple[int, int]) -> tuple[int, int]:
    """쪽 수 목표 → 보고서 글자 수(공백 뺀) 하한·상한. 한 쪽 약 1,100자는 정식보고서 샘플의 실측에서 잡은 어림이다."""
    from .transform.report_style import load_rules

    per_page = int(load_rules().limits.get("chars_per_page", 1100))
    low, high = pages
    return int(per_page * max(low, 1) * 0.6), int(per_page * high)


@dataclass
class Prepared:
    title: str
    sentences: list[str]
    user: str
    system: str
    ranges: list[tuple[str, int, int]]         # (문서 제목, 첫 문장 번호, 끝 문장 번호)
    year: int | None


def prepare(docs: list[SourceDoc], pages: tuple[int, int] = DEFAULT_PAGES, title: str | None = None) -> Prepared:
    docs = order_docs(docs)
    sentences: list[str] = []
    ranges: list[tuple[str, int, int]] = []
    blocks: list[str] = []
    for n, doc in enumerate(docs, 1):
        first = len(sentences) + 1
        lines = [f"=== 문서 {n}: {doc.title}" + (f" ({doc.date})" if doc.date else "") + " ==="]
        for kind, depth, mark, text in doc.items:
            if kind == "절":
                lines.append(f"({mark + ' ' if mark and mark != '표' else ''}{text})")
                continue
            sentences.append(text)
            lines.append("  " * depth + f"[{len(sentences)}] " + (f"{mark} " if mark and mark != "표" else "") + text)
        ranges.append((doc.title, first, len(sentences)))
        blocks.append("\n".join(lines))
    low, high = page_chars(pages)
    rules = SYNTH_RULES.replace("{low}", f"{low:,}").replace("{high}", f"{high:,}").replace(
        "{pages}", f"{pages[0]}~{pages[1]}" if pages[0] != pages[1] else str(pages[0]))
    base = REWRITE_SYSTEM
    start, end = base.index("[절대 규칙 2"), base.index("[절대 규칙 3")
    base = base[:start] + SYNTH_RULE2 + "\n" + base[end:]
    base = base.replace("[구성]", rules + "\n[구성]", 1)
    system = system_prompt(base=base)
    out_title = title or ""
    user = (f"문서 {len(docs)}개, 원문 문장 {len(sentences)}개입니다. 괄호 ( ) 안의 줄은 절 제목(맥락)이라 번호가 없고, 들여쓴 문장은 윗줄의 "
            "하위 내용입니다.\n\n" + "\n\n".join(blocks)
            + "\n\n위 문서들을 지시대로 하나의 새 보고서로 종합해 JSON 하나로만 출력하세요(첫 글자는 {).")
    newest = max((d.when for d in docs if d.when), default=None)
    return Prepared(out_title, sentences, user, system, ranges, newest.year if newest else None)


def concat_structure(ranges: list[tuple[str, int, int]]):
    """LLM을 못 쓸 때의 기본 구조: 문서마다 한 절, 문장마다 □ — 이어 붙이기일 뿐 요약·재구성이 아니다."""
    def build(title: str, sentences: list[str]) -> Structure:
        return Structure(title, [Section(name, [Group("", [i]) for i in range(first, last + 1)])
                                 for name, first, last in ranges if last >= first])
    return build


def synthesize(docs: list[SourceDoc], ask: Ask | None = None, pages: tuple[int, int] = DEFAULT_PAGES,
               title: str | None = None, year: int | None = None) -> DraftResult:
    """여러 문서 → 종합 보고서 글(정식보고서 변환기가 읽는 글). 사실 검증은 drafting.review가 한다."""
    if len(docs) < 2:
        raise ValueError("종합하려면 문서가 둘 이상 필요합니다")
    prep = prepare(docs, pages, title)
    low, high = page_chars(pages)
    result = rewrite("", ask, year or prep.year, prepared=(prep.title, prep.sentences, prep.user, prep.system),
                     synth=SynthSpec(low, high), fallback=concat_structure(prep.ranges))
    result.notes.insert(0, "종합 입력: " + ", ".join(f"문서{n} 문장 {a}~{b}" for n, (_, a, b) in enumerate(prep.ranges, 1))
                        + f" (날짜순: {' → '.join(d.date or '날짜 없음' for d in order_docs(docs))})")
    return result
