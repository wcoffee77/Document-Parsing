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

from .drafting import (REWRITE_SYSTEM, has_alternatives, Ask, DraftResult, Group, Section, Structure, SynthSpec, rewrite,
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
  **주제별로 새로 구성**합니다. 절(1.)은 보통 3~4개이고 이 흐름을 따릅니다:
  ① 현황(경과): 이미 일어난 일과 결과. 절 전체가 **보고서 분량의 1/4~1/3 이내**가 되게 씁니다. 결과는 **주제마다 대표 내용만**:
     원문의 결과 주제(□ 항목)는 하나도 빼지 않되, 주제마다 핵심 수치·결론 한두 줄로 줄이고 하위 세부(분류, 사유, 내역의 내역)와 과정·배경 설명은 뺍니다.
     뒤 문서가 앞 문서의 결과를 한 줄로 되풀이했다면, 그 한 줄만 쓰지 말고 **앞 문서의 주제별 대표 내용**을 근거로 씁니다.
     현황과 문제·위험이 얽혀 있으면 '현황 및 리스크'처럼 한 절로 합칩니다.
     나중 문서에서 완료된 일(심사 완료, 착수 완료 등)도 이 절에 한 줄로 씁니다 — 뒤 절에 따로 떼어 두지 않습니다.
  ② 검토 내용: 대안·후보 비교(아래 '비교' 규칙).
  ③ 대응 계획(또는 추진 계획): '□ 단기 대응'과 '□ 중장기 대응'(또는 단계별)으로 묶고 그 아래 실행 내용·일정을 씁니다.
     비용·효과는 별도 절로 떼지 않고, 그 방안을 택한 근거로 방안 아래 '-'에 씁니다(예: 추가 비용이 지연 손실보다 작아 선제 조치가 유리).
  ④ 결정 요청(필요할 때만): 승인·결정할 일 2~3줄. 기대 효과·위험은 □ 한 줄씩 요약하고 나열하지 않습니다.
- 앞부분(현황·경과)은 간결하게(대표 지표만), 뒷부분(대응·결정)은 자세히 씁니다. title은 비우지 않고, 핵심만 함축한 명사형으로 **반드시 한 줄**(공백 포함 20자 이내)로 씁니다.
- 같은 사실이 여러 문서에 있으면 한 번만 쓰고 src에는 근거 문장을 모두 적습니다.
- 같은 항목의 값이 문서마다 다르면 **가장 나중 문서의 값**을 씁니다. 바뀐 것을 남길 때는 '항목 : 기존 A → B (사유)'로 씁니다.
  화살표(→)는 **두 값 사이에만** 씁니다. 사유·원인은 괄호에 따로 씁니다('B (기존 A → 사유)'처럼 화살표 뒤에 사유를 쓰면 안 됩니다).
  기준 시점이 있으면 함께 씁니다(10.1 기준).
- 계획·예정이 나중 문서에서 완료·변경됐으면 현재 상태로 씁니다(예정 → 완료, 일정 연장).
- 아직 정해지지 않은 사항(검토 中, 미확정, 통보 없음, 협의 필요)은 미확정으로 씁니다. 확정·완료처럼 쓰지 않습니다.
- 결론·제언·목표(수치 목표, 절감 효과, 결정 요청)는 핵심이라 빼지 않습니다. 나중 문서에서 바뀐 계획이면 바뀐 내용을 쓴 줄의 src에 함께 넣습니다.
- 문서에 없는 숫자를 계산해 만들지 않습니다(합계·비율·증감을 새로 구하지 않음). 원문에 있는 숫자만 씁니다.
- 문서 제목·작성 날짜·"~에 따르면" 같은 출처 표기는 쓰지 않습니다(내부 문서에 근거한 보고서입니다).
- 분량은 공백 뺀 {low}~{high}자(정식보고서 Word 약 {pages}쪽) 안으로 합니다. 많으면 경과를 줄이고 결정에 필요한 수치와 쟁점은 남깁니다.
- 비교: 여러 대안을 **같은 항목**(단가·물량·기간·비용·보안 등)으로 비교하면 대안 수와 관계없이 표로 씁니다(첫 행 '구분 | 대안1 | 대안2 …').
  · 원문 비교표의 항목(행)은 줄이지 않고 그대로 옮깁니다.
  · 그 대안에 관한 다른 문서의 비교 내용(누적 비용·손익분기 등)도 표의 행으로 넣습니다. 표 밖에 줄글로 따로 쓰지 않습니다.
  · 원문에 대안별 검토 의견·판단이 있으면 표 마지막 행 '검토 의견'에 대안마다 요약해 넣습니다.
  · ①②③ 줄은 비교 항목 없이 대안을 한두 마디로 설명할 때만 씁니다.

[종합 예시]
원문:
=== 문서 1: 사무실 이전 후보지 검토 (2026. 5. 7) ===
(1. 검토 배경)
  [1] 현 사무실 임대 계약이 12월 말에 만료된다.
(2. 후보지)
  [2] 갑동 빌딩은 월 임대료 4,200만원이고 입주는 10월 중순 가능할 것으로 알려졌으나 확정은 아니다.
  [3] 을동 빌딩은 월 임대료 3,600만원이고 입주는 내년 2월부터 가능하다.
  [4] 갑동은 입주 시점이 맞으나 비용이 높고, 을동은 비용이 낮으나 두 달간 공백이 생긴다.
  [5] 회의에서는 여러 의견이 있었다.
=== 문서 2: 사무실 이전 진행 (2026. 6. 3) ===
(1. 진행 경과)
  [6] 갑동 빌딩과 협상해 월 임대료 3,900만원으로 합의했다.
  [7] 입주 시점은 11월 초로 확정됐다.
(2. 향후 계획)
  [8] 이전 비용은 2.4억원이며 이사 업체는 선정 중이다.
  [9] 내년 중 을동 빌딩을 제2사무실로 쓰는 방안을 검토한다.
출력:
{"title": "사무실 이전 추진 현황", "lines": [
 {"m": "1.", "text": "추진 경과", "src": [1, 6, 7]},
 {"m": "□", "text": "현 사무실 임대 계약 12월 말 만료, 갑동 빌딩 임대 조건 합의 및 11월 초 입주 확정", "src": [1, 6, 7]},
 {"m": "1.", "text": "후보지 비교", "src": [2, 3, 4]},
 {"m": "표", "rows": [["구분", "갑동 빌딩", "을동 빌딩"],
   ["월 임대료", "- 기존 4,200만원 → 3,900만원 (협상 결과)", "- 3,600만원"],
   ["입주 시점", "- 11월 초 확정", "- 내년 2월부터 가능"],
   ["검토 의견", "- 입주 시점 적합, 비용 높음", "- 비용 낮으나 두 달간 공백"]], "src": [2, 3, 4, 6, 7]},
 {"m": "1.", "text": "대응 계획", "src": [8, 9]},
 {"m": "□", "text": "단기 대응 : 11월 초 갑동 빌딩 입주", "src": [7, 8]},
 {"m": "-", "text": "이전 비용 : 2.4억원, 이사 업체 선정 中", "src": [8]},
 {"m": "□", "text": "중장기 대응 : 을동 빌딩 제2사무실 활용 검토(내년 中)", "src": [9]}],
 "dropped": [5]}
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
    key_groups: list[list[int]] = field(default_factory=list)   # 결과·결론·계획 절의 주제 묶음(맨 위 문장 + 하위 문장)
    number_ids: list[int] = field(default_factory=list)         # 결론·계획 절 문장(수치 보존 점검 대상)
    need_table: str = ""                                        # 비교 표가 꼭 있어야 하는 이유(없으면 요구 안 함)


_TABLE_REQUEST = (r"표로", r"표를", r"표\s*(형|형태|으로)", r"비교\s*표", r"표\s*(만들|작성|정리|비교)")
MAX_REQUEST_CHARS = 1000   # 사용자 요청사항 길이 상한(웹 화면 입력칸) — 지시문을 밀어낼 만큼 길면 자른다

REQUEST_RULES = """[사용자 요청사항 — 이 보고서에만 적용]
아래는 보고서를 받는 사람이 직접 적은 요청입니다. 구성·분량·강조점·절 이름·어조에 관한 요청은 위 [종합 규칙]·[구성]보다 우선해 따릅니다.
단 [절대 규칙](사실을 바꾸지 않음, 원문에 없는 사실·숫자를 만들지 않음, 쓴 줄의 사실은 빠짐없이)과 [출력 형식]은 요청과 상관없이 지킵니다 —
요청이 원문에 없는 내용을 요구하면 그 부분은 쓰지 않습니다.
요청 해석 원칙 (2026-10-09 실측: '경과는 최소한으로, 대안은 표로 비교'에서 비교 표가 빠지고 대응 계획까지 줄어든 오류를 막기 위함):
- 줄이라는 요청은 **그 말이 가리킨 부분에만** 적용합니다. '경과'는 [구성] ① 현황(경과) 절만 뜻합니다. ② 검토 내용(대안 비교)·③ 대응 계획·④ 결정 요청은
  경과가 아니므로 줄이지 않고 기본 분량·구체성 그대로 씁니다. 요청에 없는 부분을 임의로 줄이거나 빼지 않습니다.
- 한 부분을 줄이면 남는 분량은 요청에서 늘리거나 구체적으로 쓰라고 한 부분(없으면 대응 계획)에 씁니다. 전체 분량은 줄지 않습니다.
- '표로'·'표로 비교'라는 요청은 해당 내용 전부를 반드시 {"m": "표", "rows": …} 줄로 씁니다(줄글·①② 줄로 대신하지 않음). 대안 후보가 문서 여러 곳에 있으면 한 표에 모읍니다.
- '구체적으로'·'자세히'는 원문에 있는 일정·담당·수치·조건을 빠뜨리지 않고 쓴다는 뜻이지, 원문에 없는 내용을 만든다는 뜻이 아닙니다.
---
{request}
---
"""


def clean_request(request: str | None) -> str:
    """요청사항 정리 — 빈 줄·앞뒤 공백을 걷고 길이 상한으로 자른다."""
    text = "\n".join(line.rstrip() for line in (request or "").strip().splitlines() if line.strip())
    return text[:MAX_REQUEST_CHARS]


def prepare(docs: list[SourceDoc], pages: tuple[int, int] = DEFAULT_PAGES, title: str | None = None,
            request: str | None = None) -> Prepared:
    from .transform.factcheck import load_rules

    rules = load_rules()
    key_res = [re.compile(p) for p in rules.synthesis_key_sections]
    result_res = [re.compile(p) for p in rules.synthesis_result_sections]
    docs = order_docs(docs)
    sentences: list[str] = []
    ranges: list[tuple[str, int, int]] = []
    blocks: list[str] = []
    key_groups: list[list[int]] = []
    number_ids: list[int] = []
    for n, doc in enumerate(docs, 1):
        first = len(sentences) + 1
        lines = [f"=== 문서 {n}: {doc.title}" + (f" ({doc.date})" if doc.date else "") + " ==="]
        key_section = result_section = False
        group: list[int] = []
        for kind, depth, mark, text in doc.items:
            if kind == "절":
                lines.append(f"({mark + ' ' if mark and mark != '표' else ''}{text})")
                if mark != "표":   # 표의 열 머리는 절이 아니다
                    key_section = any(rx.search(text) for rx in key_res)
                    result_section = any(rx.search(text) for rx in result_res)
                    group = []
                continue
            sentences.append(text)
            lines.append("  " * depth + f"[{len(sentences)}] " + (f"{mark} " if mark and mark != "표" else "") + text)
            if key_section or result_section:
                if depth == 0 or not group:   # 맨 위 문장이 새 주제를 연다 — 하위 문장은 그 주제에 속한다
                    group = []
                    key_groups.append(group)
                group.append(len(sentences))
                if key_section:
                    number_ids.append(len(sentences))
        ranges.append((doc.title, first, len(sentences)))
        blocks.append("\n".join(lines))
    low, high = page_chars(pages)
    rules = SYNTH_RULES.replace("{low}", f"{low:,}").replace("{high}", f"{high:,}").replace(
        "{pages}", f"{pages[0]}~{pages[1]}" if pages[0] != pages[1] else str(pages[0]))
    if len(docs) == 1:   # 긴 문서 하나를 요약해 새 보고서로: 문서 간 병합 규칙 대신 핵심 선별 규칙
        rules = rules.replace(
            "- 입력은 같은 주제를 다룬 문서 여러 개(날짜 오름차순, 아래 문서일수록 최신)입니다. 문서별로 이어 붙이지 말고, 읽는 사람이 한 번에 이해하도록\n"
            "  **주제별로 새로 구성**합니다.",
            "- 입력은 긴 문서 1개입니다. 원문의 문단 순서에 얽매이지 말고, 읽는 사람이 한 번에 이해하도록 **핵심만 골라 새로 구성**합니다.", 1)
    base = REWRITE_SYSTEM
    start, end = base.index("[절대 규칙 2"), base.index("[절대 규칙 3")
    base = base[:start] + SYNTH_RULE2 + "\n" + base[end:]
    base = base.replace("[구성]", rules + "\n[구성]", 1)
    request = clean_request(request)
    if request:   # 구성 규칙 뒤·예시 앞에 둔다 — 예시보다 먼저 읽히고, 출력 형식(맨 끝)은 그대로 마지막에
        base = base.replace("[구성]", REQUEST_RULES.replace("{request}", request) + "\n[구성]", 1)
    system = system_prompt(base=base)
    out_title = title or ""
    need_table = ""
    if request and any(re.search(cue, request) for cue in _TABLE_REQUEST):
        need_table = "요청사항에 표가 있음"
    elif any(k == "절" and m == "표" for doc in docs for k, _, m, _ in doc.items):
        need_table = "원문에 비교 표가 있음"
    elif has_alternatives(sentences):
        need_table = "원문이 대안을 비교함"
    user = (f"문서 {len(docs)}개, 원문 문장 {len(sentences)}개입니다. 괄호 ( ) 안의 줄은 절 제목(맥락)이라 번호가 없고, 들여쓴 문장은 윗줄의 "
            "하위 내용입니다.\n\n" + "\n\n".join(blocks)
            + (f"\n\n[사용자 요청사항] {request}" if request else "")
            + "\n\n위 문서들을 지시대로 하나의 새 보고서로 종합해 JSON 하나로만 출력하세요(첫 글자는 {).")
    newest = max((d.when for d in docs if d.when), default=None)
    return Prepared(out_title, sentences, user, system, ranges, newest.year if newest else None, key_groups, number_ids, need_table)


def brief_source(prep: Prepared) -> str:
    """drafting.brief에 넘길 원문 — brief는 첫 줄을 제목으로 보고 떼므로 빈 제목 줄을 앞에 둔다(안 그러면 첫 문장의 숫자를
    '원문에 없는 숫자'로 세어 수치왜곡이 거짓으로 잡혔다 — 2026-10-09 웹 화면 확인 중 발견)."""
    return "\n" + "\n".join(prep.sentences)


def concat_structure(ranges: list[tuple[str, int, int]]):
    """LLM을 못 쓸 때의 기본 구조: 문서마다 한 절, 문장마다 □ — 이어 붙이기일 뿐 요약·재구성이 아니다."""
    def build(title: str, sentences: list[str]) -> Structure:
        return Structure(title, [Section(name, [Group("", [i]) for i in range(first, last + 1)])
                                 for name, first, last in ranges if last >= first])
    return build


def synthesize(docs: list[SourceDoc], ask: Ask | None = None, pages: tuple[int, int] = DEFAULT_PAGES,
               title: str | None = None, year: int | None = None, request: str | None = None) -> DraftResult:
    """여러 문서 → 종합 보고서 글(정식보고서 변환기가 읽는 글). 사실 검증은 drafting.review가 한다.
    request: 사용자 요청사항(예: 경과는 최소한으로, 향후 계획은 구체적으로) — 구성·분량·강조는 따르되 사실 규칙은 못 넘는다."""
    if not docs:
        raise ValueError("문서가 없습니다")
    prep = prepare(docs, pages, title, request)
    low, high = page_chars(pages)
    result = rewrite("", ask, year or prep.year, prepared=(prep.title, prep.sentences, prep.user, prep.system),
                     synth=SynthSpec(low, high, prep.key_groups, prep.number_ids, prep.need_table), fallback=concat_structure(prep.ranges))
    if not (result.title or "").strip():
        result.title = _fallback_title(result, docs, ask, result.notes)
    if clean_request(request):
        result.notes.insert(0, f"사용자 요청사항 반영: {clean_request(request)[:120]}")
    result.notes.insert(0, "종합 입력: " + ", ".join(f"문서{n} 문장 {a}~{b}" for n, (_, a, b) in enumerate(prep.ranges, 1))
                        + f" (날짜순: {' → '.join(d.date or '날짜 없음' for d in order_docs(docs))})")
    return result


def _fallback_title(result: DraftResult, docs: list[SourceDoc], ask: Ask | None, notes: list[str]) -> str:
    """LLM이 title을 끝내 비웠을 때(2026-10-08 실측 B 1회: 제목 없이 나옴): 보고서 글로 짧은 제목을 한 번 더 묻고, 안 되면 가장 최근 문서 제목."""
    if ask is None:
        try:
            from .transform.llm_polish import ask_chat
            ask = ask_chat
        except Exception:  # noqa: BLE001
            ask = None
    if ask is not None and result.used_llm:
        try:
            raw = (ask("보고서 본문을 읽고 전체를 대표하는 제목을 한 줄로만 씁니다. 명사형, 공백 포함 25자 이내, 마침표·따옴표·번호 없이 제목 글자만 출력합니다.",
                       result.text[:3000]) or "").strip().splitlines()
            title = raw[0].strip(" \"'.「」") if raw else ""
            if 2 <= len(title) <= 40:
                notes.append(f"제목: LLM이 정하지 않아 보고서 본문으로 다시 물어 정함 — {title}")
                return title
        except Exception:  # noqa: BLE001
            pass
    newest = order_docs(docs)[-1].title
    notes.append(f"제목: LLM이 정하지 않아 가장 최근 문서 제목을 씀 — {newest}")
    return newest
