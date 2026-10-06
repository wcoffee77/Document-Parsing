"""줄글 → 정식보고서 구조 (로드맵 A1·A2) — LLM은 **배치만** 하고 원문 문장은 그대로 둔다.

줄글을 문장으로 나눠 번호를 붙이고, LLM에게 "어느 절(1.)에, 어떤 묶음(□)으로, 어떤 순서로" 놓을지만 JSON으로 받는다.
- 세부 항목(-)은 **원문 문장 그대로**다 — 사실·수치를 LLM이 바꿀 길이 없다.
- 절 제목과 □ 요지는 짧게 새로 쓰게 하되, **요지에 든 숫자는 묶음의 원문 문장에 있어야** 한다(없으면 그 요지는 버린다).
- 모든 문장이 정확히 한 번, 원래 순서대로 나와야 한다. 어긋나면 한 번 고쳐 달라고 하고, 그래도 안 되면 규칙만으로 만든
  기본 구조(문장마다 □)로 돌아간다 — 어떤 경우에도 결과가 비거나 문장이 사라지지 않는다.
결과는 정식보고서 변환기가 읽는 글(`1. 절` / `□ 요지` / `- 문장` / `※ 참고`)로 낸다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable

from .transform.stylize_ko import _SENTENCE_SPLIT, _merge_punct_only_parts

Ask = Callable[[str, str], str]

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
MAX_HEADING = 24      # 절 제목 글자 수 한도(어림 — 한 줄에 들어갈 길이)
MAX_SUMMARY = 60      # □ 요지 글자 수 한도

SYSTEM = f"""당신은 사내 정식보고서 편집자입니다. 번호가 붙은 문장들을 보고서 구조에 **배치만** 합니다. 문장을 고치거나 만들지 마세요.

출력은 아래 JSON 하나뿐입니다(설명·코드 블록 금지).
{{"title": "보고서 제목(명사형, 30자 이내)",
 "sections": [
  {{"heading": "절 제목(명사형, {MAX_HEADING}자 이내, 번호 없이)",
    "groups": [
      {{"summary": "묶음의 요지(명사형 종결, {MAX_SUMMARY}자 이내, 원문에 있는 사실·숫자만. 묶음이 문장 하나면 빈 문자열)",
        "ids": [묶음에 넣을 문장 번호들],
        "notes": [참고·단서·면책(\\"확인 필요\\", \\"~에 따라 달라질 수 있음\\" 등)로 따로 둘 문장 번호들]}}
    ]}}
 ]}}

규칙:
1. 모든 문장 번호가 ids 또는 notes에 **정확히 한 번**, **원래 순서 그대로** 나와야 합니다.
2. 절은 보통 2~5개(배경·현황, 문제·쟁점, 방안·제안, 일정·계획, 기대효과·참고 같은 흐름), 한 절에 묶음 1~5개.
3. 요지와 절 제목에는 원문에 없는 숫자·고유명사를 쓰지 마세요. 요지의 숫자는 그 묶음의 문장에 있는 숫자여야 합니다.
4. 요지는 '~함', '~임', '~필요' 또는 명사로 끝냅니다. '~합니다'로 끝내지 마세요.
"""


@dataclass
class Group:
    summary: str
    ids: list[int]
    notes: list[int] = field(default_factory=list)


@dataclass
class Section:
    heading: str
    groups: list[Group]


@dataclass
class Structure:
    title: str
    sections: list[Section]


@dataclass
class DraftResult:
    text: str                      # 정식보고서 변환기가 읽는 글
    structure: Structure | None    # 배치 모드의 구조(다듬기 모드는 None)
    notes: list[str]               # --report에 남길 판단·실패 사유
    used_llm: bool
    title: str = ""
    mode: str = "place"            # rewrite(다듬기) | place(배치만) | fallback(규칙 기본 구조)
    sections: int = 0


def split_sentences(text: str) -> tuple[str, list[str]]:
    """(제목, 문장 목록). 맨 위 짧은 한 줄(마침표 없음) + 빈 줄이면 제목, 아니면 제목 없음."""
    lines = [line.rstrip() for line in text.strip().splitlines()]
    title = ""
    if len(lines) > 2 and lines[0].strip() and not lines[1].strip() and len(lines[0]) <= 40 \
            and not re.search(r"[.!?]$", lines[0].strip()):
        title = lines[0].strip()
        lines = lines[2:]
    sentences: list[str] = []
    for paragraph in re.split(r"\n\s*\n", "\n".join(lines)):
        flat = " ".join(part.strip() for part in paragraph.splitlines() if part.strip())
        if not flat:
            continue
        sentences += [s.strip() for s in _merge_punct_only_parts(
            [p for p in _SENTENCE_SPLIT.split(flat) if p.strip()]) if s.strip()]
    return title, sentences


def _numbers(text: str) -> set[str]:
    return {m.group().replace(",", "").rstrip(".") for m in _NUMBER.finditer(text)}


def parse_structure(raw: str, sentences: list[str]) -> Structure:
    """LLM 응답을 읽고 검증한다. 어긋나면 ValueError(사유)."""
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < start:
        raise ValueError("JSON을 찾지 못함")
    try:
        data = json.loads(raw[start:end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 해석 실패({exc.msg})") from exc
    sections: list[Section] = []
    for raw_section in data.get("sections") or []:
        groups = [Group(str(g.get("summary") or "").strip(), [int(i) for i in g.get("ids") or []],
                        [int(i) for i in g.get("notes") or []]) for g in raw_section.get("groups") or []]
        sections.append(Section(str(raw_section.get("heading") or "").strip(), groups))
    structure = Structure(str(data.get("title") or "").strip(), sections)

    flat: list[int] = []
    for section in structure.sections:
        for group in section.groups:
            flat += sorted(group.ids + group.notes)
    if sorted(flat) != list(range(1, len(sentences) + 1)):
        missing = sorted(set(range(1, len(sentences) + 1)) - set(flat))
        extra = sorted({i for i in flat if flat.count(i) > 1 or not 1 <= i <= len(sentences)})
        raise ValueError(f"문장 번호가 정확히 한 번씩 나오지 않음(빠진 {missing[:8]}, 중복·범위밖 {extra[:8]})")
    if flat != sorted(flat):
        raise ValueError("문장 순서가 원문과 다름")
    return structure


def sanitize(structure: Structure, sentences: list[str]) -> list[str]:
    """요지·제목의 길이·숫자를 점검해 어긋난 요지는 비운다(그 묶음은 첫 문장이 □가 된다). 판단 내용을 돌려준다."""
    notes: list[str] = []
    for section in structure.sections:
        for group in section.groups:
            source = _numbers(" ".join(sentences[i - 1] for i in group.ids + group.notes))
            if group.summary:
                invented = _numbers(group.summary) - source
                if invented:
                    notes.append(f"요지 폐기(원문에 없는 숫자 {sorted(invented)}): {group.summary[:30]}")
                    group.summary = ""
                elif len(group.summary) > MAX_SUMMARY:
                    notes.append(f"요지 폐기(길이 {len(group.summary)}자 > {MAX_SUMMARY}): {group.summary[:30]}…")
                    group.summary = ""
        if len(section.heading) > MAX_HEADING:
            notes.append(f"절 제목이 {len(section.heading)}자로 길다(한도 {MAX_HEADING}): {section.heading}")
    return notes


def fallback_structure(title: str, sentences: list[str]) -> Structure:
    """규칙만으로 만든 기본 구조: 한 절, 문장마다 □."""
    return Structure(title, [Section("주요 내용", [Group("", [i + 1]) for i in range(len(sentences))])])


def render(structure: Structure, sentences: list[str]) -> str:
    """정식보고서 변환기가 읽는 글. 묶음에 요지가 있으면 □ 요지 + - 문장들, 없으면 □ 첫 문장(+ - 나머지)."""
    out: list[str] = []  # 제목은 글에 넣지 않는다 — 변환기에 title로 따로 넘긴다(안 그러면 제목이 두 번 나온다)
    for number, section in enumerate(structure.sections, 1):
        out.append(f"{number}. {section.heading}")
        for group in section.groups:
            body = [sentences[i - 1] for i in group.ids]
            if group.summary and body:
                out.append(f"□ {group.summary}")
                out += [f"- {s}" for s in body]
            elif body:
                out.append(f"□ {body[0]}")
                out += [f"- {s}" for s in body[1:]]
            out += [f"* {sentences[i - 1]}" for i in group.notes]
    return "\n".join(out) + "\n"


def place(text: str, ask: Ask | None = None) -> DraftResult:
    """배치 모드: 원문 문장 그대로 구조만. ask(system, user)가 없으면 설정된 LLM을 쓴다. LLM이 없거나 실패하면 기본 구조."""
    title, sentences = split_sentences(text)
    notes: list[str] = []
    if not sentences:
        raise ValueError("문장을 찾지 못했습니다")
    if ask is None:
        from .transform.llm_polish import ask_chat
        ask = ask_chat
    numbered = "\n".join(f"[{i}] {s}" for i, s in enumerate(sentences, 1))
    user = (f"제목 후보: {title}\n" if title else "") + f"문장 {len(sentences)}개:\n{numbered}"
    structure: Structure | None = None
    error = ""
    for attempt in range(2):
        try:
            raw = ask(SYSTEM, user if attempt == 0 else
                      f"{user}\n\n[이전 응답의 문제] {error}\n위 규칙을 지켜 JSON을 다시 출력하세요.")
            structure = parse_structure(raw, sentences)
            break
        except ValueError as exc:
            error = str(exc)
            notes.append(f"LLM 구조 응답 {attempt + 1}차 실패: {error}")
        except Exception as exc:  # noqa: BLE001 — 설정 없음·네트워크
            error = str(exc)
            notes.append(f"LLM 호출 실패: {error}")
            break
    used = structure is not None
    if structure is None:
        structure = fallback_structure(title, sentences)
        notes.append("규칙 기본 구조 사용(한 절, 문장마다 □)")
    else:
        notes += sanitize(structure, sentences)
        structure.title = structure.title or title
        if title and structure.title != title:
            structure.title = title  # 원문 제목이 있으면 그대로
    return DraftResult(render(structure, sentences), structure, notes, used, title=structure.title,
                       mode="place" if used else "fallback", sections=len(structure.sections))


# ── 다듬기 모드 (B안, 2026-10-03 사용자) ─────────────────────────────────────────────
# "내가 생각하는 바를 줄글로 쓰면 보고서로 깔끔하게 바꾸는 기능" — LLM이 문장을 보고서 말투로 다시 쓰고 배열한다(때로는 표).
# 단 **사실은 절대 바뀌면 안 된다**: 줄마다 근거 원문 번호(src)를 받아 파이썬(transform/factcheck.py)이 숫자·날짜·요일·영문·한자·
# 방향·확정 여부를 대조한다. 걸린 줄은 한 번 고쳐 달라고 하고, 그래도 걸리면 그 줄을 **원문 문장 그대로** 바꾼다.
# 문체 규칙은 정답 5건(docs/drafting-answers-analysis.md)에서 뽑았다.

REWRITE_SYSTEM = """당신은 사내 정식보고서 작성자입니다. 번호가 붙은 원문 문장(줄글)을 상급자 보고용 개조식 보고서로 다시 씁니다.
거친 문장을 보고서 말투로 매끄럽게 다듬고, 보고 흐름에 맞게 배열합니다. 내용은 원문 그대로여야 합니다.

[절대 규칙 — 사실]
1. 원문에 없는 사실·숫자·날짜·기한·요일·이름·평가를 만들지 않습니다. 숫자는 값 그대로, 표기만 바꿀 수 있습니다
   (10월 15일 → 10.15, 300만 원 → 300만원, 연 4억 원 → 4억원/년, 두 곳 → 2개, 둘째 주 → 2주차).
2. 방향·정도·확정 여부를 바꾸지 않습니다(늘었다↔줄었다 금지, '검토 중'을 '확정'으로 바꾸기 금지).
   - 가능성은 가능성으로: '어려워질 수 있다' → '달성 차질 우려' / '어려울 수 있음' (X '어려움'),
     '환율에 따라 달라질 수 있다' → '환율에 따라 변동 가능' (X '상이').
   - 수량 표현 그대로: '일부' → '일부'(X '다수'), '대부분' → '대부분'.
   - 숫자 뒤 범위 표현 그대로: '3개월 넘게' → '3개월 이상'(X '3개월'), '3천만 원 이상' → '3,000만원 이상'.
   - 원문의 단서(약, 정도, 예정, 검토, 가능성)는 남깁니다.
   - 다른 뜻으로 읽히는 말을 새로 쓰지 않습니다: '매년' → '매년'·'연 단위'(X '연차' — 연차휴가로 읽힘).
   - 문장을 src로 쓰면 그 문장의 숫자(비교 기준값·작년 수치·기준표 비율 포함)를 줄에 모두 남깁니다.
     합계·내역이 함께 있으면 둘 다 씁니다(예: 합계 5,700만원 (코칭 4,500 + 워크숍 1,200), 작년 대비 +500).
     숫자가 든 문장을 dropped로 보내 숫자를 피하지 않습니다. dropped는 말투·소감·중복·부연 문장에만 씁니다.
   - 문장의 핵심 정보(주장·이유·조건·대상)는 줄여 쓰되 하나도 빠뜨리지 않습니다(예: 설문에서 '불만이 높다'는 배경, '서면 합의·정산기간 결정이 필요' 같은 조건).
   - 특정 대안에만 해당하는 내용(조건·비용·일정)은 그 대안 줄의 하위 항목(-, ∙)이나 표 칸에 넣고, 대안과 같은 단계에 따로 늘어놓지 않습니다.
   - '빨라야 ~가능'(가능한 가장 이른 시점)과 '~에 도입 추진'(저자의 계획)은 다른 사실입니다. 섞지 말고 각각 씁니다.
3. 줄마다 src에 그 줄의 근거 원문 문장 번호를 모두 적습니다. 근거 없는 줄은 쓰지 않습니다.
4. 보고에 필요 없는 문장(말투, 개인 소감, 중복, 자잘한 부연)은 쓰지 않고 dropped에 번호를 적습니다.
   모든 문장 번호는 어느 줄의 src나 dropped에 한 번 이상 나와야 합니다.

[구성]
- 보고서 유형에 맞게 절을 나눕니다(예):
  현황 보고 → □ 목표·현황(항목명 : 값) → □ 추진 방향
  방안 검토 → 1. 배 경 / 2. 검토 방안(대안 비교 표) / 3. 추진 방향
  결과 보고 → □ 운영 경과 → □ 주요 결과 → □ 향후 계획(①②③)
  추진 계획 → □ 대 상 → □ 일 정 → □ 세부 프로그램 → □ 소요 예산 → ※ 기타 사항
  이슈·건의 → □ 배경 및 이슈 → □ 검토 가능(안)(①②③) → □ 건의 사항
- 맨 위 단계는 "□"(절 제목 또는 핵심 문장). 대안 비교 표가 있을 때만 "1."(번호 절)을 쓰고 그 아래 "□".
- 말머리(m): "1."(번호 절, text는 번호 없이), "□", "-"(세부), "∙"(- 아래 세부), "①" "②" "③"(안·계획 나열),
  "→"(목표·결과), "※"(단서·확인 필요·후속 일정), "*"(바로 윗줄을 보충하는 참고 수치·기준), "표".
- 사실 나열은 "항목명 : 값"으로 씁니다(채용 목표 : 총 40명 / 대 상 : 입사 10년차 이상 30명).
- 대안이 2개면 표로 씁니다: {"m": "표", "rows": [["구분", "(1안) …", "(2안) …"], ["장점", "- …", "- …"], ["단점", "- …\\n- …", "- …"]], "src": [...]}.
  칸 안 여러 줄은 \\n으로 나눕니다. 대안이 3개 이상이면 ①②③ "안 : 비용·난점"으로 씁니다.
- 결론·제안은 마지막 절에 두고, 앞의 대안 번호를 다시 부릅니다(우선 ① …, 내년부터는 ② …).

[문장]
- 화자·말투를 지웁니다(저는, 일단, ~입니다, 보고드립니다, ~로 보입니다, ~것 같습니다).
- 문장 끝은 명사나 한자 한 글자로 끝냅니다(추진, 검토, 예정, 필요, 확보, 高, 中, 可, 必).
  '~합니다', '~함', '~임', 마침표는 쓰지 않습니다.
- 한자 약어는 高 中 現 可 必 時 順 內 人 月 만 씁니다(처우 협의 中, 확인 必, 보고時, 3회/人, 1회/月).
- 숫자: 만원·억원은 붙여 씁니다. 날짜 M.D, 기한 (~10.15일), 변화 (기존 25% → 30%), 비율 (67.5%), 분모 15명 中 12명.
- 특정 회사명(A사·B사)은 '경쟁사'로 묶습니다.
- 한 항목은 공백 빼고 대개 20~30자(정답 보고서 항목의 중앙값 23자), 길어도 40자 안팎(최대 50자). 한 문장에 사실이 여럿이면 사실마다 항목을 나눕니다.
  긴 문장을 연결어미(~는데, ~고, ~지만, ~때문에)로 이어 붙이지 말고, 줄을 나누거나 '항목 : 값', '(기존 A → B)', '(사유)'로 압축합니다.
- 전체 분량은 원문의 60~75%.
- 날짜 줄과 맺음말("- 이 상 -")은 쓰지 않습니다(변환기가 붙입니다).

출력은 JSON 하나뿐입니다(설명·코드 블록 금지):
{"title": "보고서 제목(명사형)", "lines": [{"m": "□", "text": "...", "src": [1]}, ...], "dropped": [번호, ...]}

[예시]
원문:
[1] 신입사원 입문교육을 9월 1일부터 사흘간 진행했습니다.
[2] 대상은 하반기 입사자 85명이었고 82명이 수료했습니다.
[3] 만족도는 5점 만점에 4.3점으로 작년 4.1점보다 올랐습니다.
[4] 다만 직무 실습 시간이 부족하다는 의견이 많았습니다.
[5] 내년에는 실습을 하루 더 늘리는 방안을 검토하겠습니다.
[6] 예산은 추가로 1,500만 원 정도 필요할 것 같은데 재무팀과 협의가 필요합니다.
[7] 개인적으로는 반응이 좋아서 다행이라고 생각합니다.
출력:
{"title": "신입사원 입문교육 결과 보고", "lines": [
 {"m": "□", "text": "운영 결과", "src": [1, 2, 3]},
 {"m": "-", "text": "기 간 : 9.1 ~ 3 (3일간)", "src": [1]},
 {"m": "-", "text": "대 상 : 하반기 입사자 85명 中 82명 수료", "src": [2]},
 {"m": "-", "text": "만족도 : 4.3점/5점 (전년 4.1점 대비 상승)", "src": [3]},
 {"m": "□", "text": "개선 방향", "src": [4, 5, 6]},
 {"m": "-", "text": "직무 실습 시간 부족 의견 다수", "src": [4]},
 {"m": "→", "text": "차년도 실습 1일 확대 검토", "src": [5]},
 {"m": "※", "text": "추가 예산 약 1,500만원 소요 예상, 재무팀 협의 필요", "src": [6]}],
 "dropped": [7]}
"""

def system_prompt(exclude_docs: set[int] | None = None) -> str:
    """지시문 + 문장 → 보고서 줄 변환 예시(rules/report_style.yaml). exclude_docs는 채점용(그 정답에서 뽑은 예시를 뺀다)."""
    from .transform.report_style import examples_text

    shown = examples_text(exclude_docs=exclude_docs)
    if not shown:
        return REWRITE_SYSTEM
    return (REWRITE_SYSTEM + "\n[문장 변환 예시 — 같은 방식으로 압축하되, 원문에 없는 사실은 절대 넣지 않습니다]\n" + shown + "\n")


_ORDINAL = re.compile(r"^[①-⑳]$")
_SECTION_MARK = re.compile(r"^\d{1,2}\.$")
_PLAIN_MARKS = ("□", "-", "∙", "→", "※", "*")
_LABEL = re.compile(r"^(?P<label>[^:：\d][^:：]{0,15}?)\s*:\s+(?P<value>\S.*)$")
_POLITE_END = re.compile(r"(?:습니다|니다|어요|아요|해요|세요|입니다)\.?$")


@dataclass
class Line:
    m: str
    text: str = ""
    src: list[int] = field(default_factory=list)
    rows: list[list[str]] | None = None
    original: bool = False         # 사실 검증에 걸려 원문 문장으로 바꾼 줄

    @property
    def is_table(self) -> bool:
        return self.rows is not None

    def content(self) -> str:
        if self.rows is not None:
            return " ".join(cell for row in self.rows for cell in row)
        return self.text


@dataclass
class Rewrite:
    title: str
    lines: list[Line]
    dropped: list[int]


def _valid_mark(mark: str) -> bool:
    return mark in _PLAIN_MARKS or mark == "표" or bool(_ORDINAL.match(mark) or _SECTION_MARK.match(mark))


def parse_rewrite(raw: str, count: int) -> Rewrite:
    """LLM 응답 → Rewrite. 형식이 어긋나면 ValueError(사유)."""
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < start:
        raise ValueError("JSON을 찾지 못함")
    try:
        data = json.loads(raw[start:end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 해석 실패({exc.msg})") from exc
    lines: list[Line] = []
    for item in data.get("lines") or []:
        mark = str(item.get("m") or "").strip()
        if mark in ("1", "2", "3", "4", "5", "6", "7", "8", "9"):
            mark += "."
        if not _valid_mark(mark):
            raise ValueError(f"알 수 없는 말머리 '{mark}'")
        try:
            src = [int(i) for i in item.get("src") or []]
        except (TypeError, ValueError) as exc:
            raise ValueError("src가 숫자 목록이 아님") from exc
        bad = [i for i in src if not 1 <= i <= count]
        if bad:
            raise ValueError(f"없는 문장 번호 {bad}")
        if mark == "표":
            rows = item.get("rows")
            if not isinstance(rows, list) or len(rows) < 2 or not all(isinstance(r, list) for r in rows):
                raise ValueError("표(rows)가 두 행 이상의 목록이 아님")
            lines.append(Line(mark, "", src, [[str(c).strip() for c in r] for r in rows]))
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            raise ValueError(f"글이 빈 줄({mark})")
        lines.append(Line(mark, text, src))
    if not lines:
        raise ValueError("줄이 하나도 없음")
    dropped = [int(i) for i in data.get("dropped") or [] if str(i).isdigit()]
    return Rewrite(str(data.get("title") or "").strip(), lines, dropped)


def review(rewrite: Rewrite, sentences: list[str], title: str, year: int | None,
           rules=None) -> tuple[dict[int, list[str]], list[str]]:
    """(줄 번호 → 사실 문제, 형식 문제 목록). 사실 문제가 남은 줄은 원문으로 바꾼다. 형식 문제는 다시 써 달라고만 한다."""
    from .transform.factcheck import check, load_rules, uncovered_by_source
    from .transform.report_style import lint

    rules = rules or load_rules()
    everything = " ".join(sentences)
    facts: dict[int, list[str]] = {}
    style: list[str] = []
    for index, line in enumerate(rewrite.lines):
        if not line.src:
            facts[index] = ["근거 문장 번호(src)가 없음"]
            continue
        source = " ".join(sentences[i - 1] for i in line.src)
        problems = check(line.content(), source, rules, year)
        if problems:
            facts[index] = problems
        for piece in _text_pieces(line):
            issues = lint(piece)
            if any(i.hard for i in issues):
                style.append(f"{index + 1}번째 줄이 서술체·구어체(필수 수정 — {', '.join(str(i) for i in issues if i.hard)}): {piece[:30]}")
            elif issues:
                style.append(f"{index + 1}번째 줄이 길거나 늘어짐({', '.join(str(i) for i in issues)}): {piece[:30]}")
    if rewrite.title:
        problems = check(rewrite.title, f"{title} {everything}", rules, year)
        if problems:
            facts[-1] = problems
    used = {i for line in rewrite.lines for i in line.src} | set(rewrite.dropped)
    missing = [i for i in range(1, len(sentences) + 1) if i not in used]
    if missing:
        style.append(f"문장 {missing}이(가) 어느 줄의 src에도, dropped에도 없음")
    for i in sorted(set(rewrite.dropped)):
        if 1 <= i <= len(sentences) and re.search(r"\d", sentences[i - 1]) and i not in {j for l in rewrite.lines for j in l.src}:
            style.append(f"문장 [{i}]에 숫자가 있는데 dropped로 보냄 — 줄로 쓰고 숫자를 남기세요")
    for i, numbers in uncovered_by_source(sentences, _cited_lines(rewrite), rules).items():
        style.append(f"문장 [{i}]의 수치 {', '.join(numbers)}이(가) 그 문장을 쓴 줄에 없음 — 줄에 넣거나, 숫자를 뺄 거면 그 문장을 dropped로")
    return facts, style


def _cited_lines(rewrite: Rewrite) -> list[tuple[list[int], str]]:
    return [(line.src, line.content()) for line in rewrite.lines]


def _text_pieces(line: "Line") -> list[str]:
    """줄의 점검 단위 — 표는 칸 안 줄마다."""
    if line.rows is None:
        return [line.text]
    return [part for row in line.rows[1:] for cell in row[1:] for part in cell.split("\n") if part.strip()]


def _problem_message(rewrite: Rewrite, facts: dict[int, list[str]], style: list[str]) -> str:
    out = []
    for index, problems in sorted(facts.items()):
        where = "제목" if index < 0 else f"{index + 1}번째 줄({rewrite.lines[index].m} {rewrite.lines[index].content()[:30]})"
        out.append(f"- {where}: {', '.join(problems)}")
    out += [f"- {s}" for s in style]
    return "\n".join(out)


def _rule_sentence(sentence: str, year: int | None) -> str:
    """원문 문장을 규칙만으로 개조식으로(문장 끝 명사화·군말 삭제·표기 정리). 사실 검증을 통과해야 쓰고 아니면 원문 그대로."""
    from .transform.factcheck import check
    from .transform.report_style import fix

    fixed = fix(sentence)
    return fixed if fixed and not check(fixed, sentence, year=year) else sentence


def _restore_originals(rewrite: Rewrite, facts: dict[int, list[str]], sentences: list[str],
                       original_title: str, year: int | None = None) -> list[str]:
    """사실 검증에 끝까지 걸린 줄을 원문 문장으로 바꾼다(문장 끝만 규칙으로 개조식). 판단 내용을 돌려준다."""
    notes: list[str] = []
    replaced: list[Line] = []
    for index, line in enumerate(rewrite.lines):
        if index not in facts:
            replaced.append(line)
            continue
        source = [sentences[i - 1] for i in line.src]
        shown = line.content()[:40]
        notes.append(f"사실 검증 실패 → 원문 문장으로 대체(문장 끝만 규칙으로 개조식, {', '.join(facts[index])}): {shown}")
        if not source:
            continue  # 근거 없는 줄은 뺀다
        if line.is_table:
            replaced += [Line("-", _rule_sentence(s, year), [i], original=True) for s, i in zip(source, line.src)]
        else:
            replaced.append(Line(line.m, " ".join(_rule_sentence(s, year) for s in source), line.src, original=True))
    rewrite.lines = replaced
    if -1 in facts:
        notes.append(f"제목 검증 실패({', '.join(facts[-1])}) → 원문 제목 사용: {rewrite.title}")
        rewrite.title = original_title
    return notes


def _apply_style_fix(rewrite: Rewrite, sentences: list[str], year: int | None) -> list[str]:
    """LLM이 끝내 서술체·구어체로 남긴 줄을 규칙으로 고친다. 사실 검증을 다시 통과할 때만 바꾼다. 판단 내용을 돌려준다."""
    from .transform.factcheck import check
    from .transform.report_style import fix, hard_issues

    notes: list[str] = []

    def mend(piece: str, source: str) -> str:
        if not hard_issues(piece):
            return piece
        fixed = fix(piece)
        if fixed == piece or check(fixed, source, year=year) or hard_issues(fixed):
            return piece
        notes.append(f"규칙 교정(서술체 → 개조식): '{piece[:30]}' → '{fixed[:30]}'")
        return fixed

    for line in rewrite.lines:
        if line.original:
            continue
        source = " ".join(sentences[i - 1] for i in line.src)
        if line.rows is None:
            line.text = mend(line.text, source)
        else:
            line.rows = [row[:1] + [cell and "\n".join(mend(part, source) for part in cell.split("\n")) for cell in row[1:]]
                         for row in line.rows]
    return notes


def _style_residue(rewrite: Rewrite) -> list[str]:
    """고친 뒤에도 남은 약한 문제(길이·연결어미 과다·구어 부사) — 사람이 볼 수 있게 --report에."""
    from .transform.report_style import lint

    out: list[str] = []
    for index, line in enumerate(rewrite.lines):
        if line.original:
            continue
        for piece in _text_pieces(line):
            issues = [i for i in lint(piece) if not i.hard]
            if issues:
                out.append(f"{index + 1}번째 줄 문체 점검({', '.join(str(i) for i in issues)}): {piece[:34]}")
    return out


def _display_width(text: str) -> int:
    import unicodedata

    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def _spaced_label(label: str) -> str:
    """두 글자 항목명은 가운데를 띄운다(기간 → 기 간, 정답 5건)."""
    from .transform.report_style import load_rules

    return f"{label[0]} {label[1]}" if label in load_rules().spaced_labels else label


def tidy_labels(lines: list[Line]) -> None:
    """"항목명 : 값" 정리 — 두 글자 항목명 띄우기, 같은 말머리로 이어지는 항목끼리 쌍점 세로 맞춤(정답 4·5)."""
    run: list[tuple[Line, str, str]] = []

    def flush() -> None:
        if len(run) >= 2:
            width = max(_display_width(label) for _, label, _ in run)
            for line, label, value in run:
                line.text = f"{label}{' ' * (width - _display_width(label))} : {value}"
        elif run:
            line, label, value = run[0]
            line.text = f"{label} : {value}"
        run.clear()

    def kind(mark: str) -> str:
        return "①" if _ORDINAL.match(mark) else mark

    previous_kind = None
    for line in lines:
        match = None if line.is_table or line.original else _LABEL.match(line.text)
        if _SECTION_MARK.match(line.m) and not line.original:
            line.text = _spaced_label(line.text.strip())
        if match is None or kind(line.m) != previous_kind:
            flush()
        if match is not None:
            run.append((line, _spaced_label(match.group("label").strip()), match.group("value").strip()))
        previous_kind = kind(line.m)
    flush()


def rewrite_text(rewrite: Rewrite) -> str:
    """정식보고서 변환기가 읽는 글. 번호 절은 차례로 다시 매기고, 표는 탭 표(칸 안 줄바꿈은 <br>)로 쓴다."""
    out: list[str] = []
    section = 0
    for line in rewrite.lines:
        if line.is_table:
            if out and out[-1]:
                out.append("")
            for row in line.rows or []:
                out.append("\t".join(cell.replace("\t", " ").replace("\n", "<br>") or " " for cell in row))
            out.append("")
            continue
        if _SECTION_MARK.match(line.m):
            section += 1
            out.append(f"{section}. {line.text}")
        else:
            out.append(f"{line.m} {line.text}")
    return "\n".join(out).strip() + "\n"


def rewrite(text: str, ask: Ask | None = None, year: int | None = None,
            holdout: set[int] | None = None) -> DraftResult:
    """다듬기 모드: 줄글 → 보고서 말투의 개조식 글(사실은 원문 그대로). 형식이 끝내 안 맞으면 배치 모드로."""
    import datetime

    title, sentences = split_sentences(text)
    if not sentences:
        raise ValueError("문장을 찾지 못했습니다")
    if ask is None:
        from .transform.llm_polish import ask_chat
        ask = ask_chat
    year = year or datetime.date.today().year
    numbered = "\n".join(f"[{i}] {s}" for i, s in enumerate(sentences, 1))
    user = (f"원문 제목: {title}\n" if title else "") + f"원문 문장 {len(sentences)}개:\n{numbered}"
    notes: list[str] = []
    result: Rewrite | None = None
    facts: dict[int, list[str]] = {}
    message = user
    unavailable = False
    system = system_prompt(holdout)
    format_errors = 0
    revised = False
    while True:
        raw = ""
        try:
            raw = ask(system, message)
            candidate = parse_rewrite(raw, len(sentences))
        except ValueError as exc:
            # 형식 오류는 내용 수정 기회와 따로 센다(2026-10-05 실측: 첫 응답 형식 오류가 수정 기회를 먹어 사실 문제를
            # 다시 고쳐 쓰게 못 하고 원문으로 대체됐다)
            format_errors += 1
            notes.append(f"LLM 다듬기 응답 형식 오류 {format_errors}회: {exc} ({_raw_hint(raw)})")
            if format_errors >= MAX_FORMAT_RETRIES:
                break
            message = f"{user}\n\n[이전 응답의 문제] {exc}\n설명 없이 JSON 하나만 출력하세요."
            continue
        except Exception as exc:  # noqa: BLE001 — 설정 없음·네트워크
            notes.append(f"LLM 호출 실패: {exc}")
            unavailable = True
            break
        facts, style = review(candidate, sentences, title, year)
        result = candidate
        if not facts and not style:
            break
        notes.append(f"LLM 다듬기 {'수정본' if revised else '1차'} 검증: 사실 문제 {len(facts)}줄, 형식 문제 {len(style)}건")
        if revised:
            break
        revised = True
        previous = raw[raw.find("{"):raw.rfind("}") + 1]
        message = (f"{user}\n\n[이전 응답]\n{previous}\n\n[검증에서 걸린 것 — 원문 사실과 다르거나 규칙 위반]\n"
                   f"{_problem_message(candidate, facts, style)}\n"
                   "걸린 줄만 원문 사실대로 고치고 나머지는 그대로 두어 JSON 전체를 다시 출력하세요.")
    if result is None and unavailable:
        structure = fallback_structure(title, sentences)
        ruled = [_rule_sentence(sentence, year) for sentence in sentences]
        notes.append("규칙 기본 구조 사용(한 절, 문장마다 □ — 원문 문장, 끝만 규칙으로 개조식). "
                     "문장을 압축하려면 LLM 설정이 필요합니다")
        return DraftResult(render(structure, ruled), structure, notes, False, title=title,
                           mode="fallback", sections=len(structure.sections))
    if result is None:
        notes.append("다듬기 실패 → 배치 모드(원문 문장 그대로)")
        placed = place(text, ask)
        placed.notes = notes + placed.notes
        return placed

    if facts:
        notes += _repair_lines(result, facts, sentences, ask, year)
    notes += _restore_originals(result, facts, sentences, title, year)
    notes += _apply_style_fix(result, sentences, year)
    notes += _repair_numbers(result, sentences, ask, year)
    notes += _audit_content(result, sentences, ask, year)
    notes += _style_residue(result)
    tidy_labels(result.lines)
    body = rewrite_text(result)
    notes += _coverage_notes(result, sentences, body)
    sections = sum(1 for line in result.lines if _SECTION_MARK.match(line.m)) or sum(
        1 for line in result.lines if line.m == "□")
    return DraftResult(body, None, notes, True, title=result.title or title, mode="rewrite", sections=sections)


MAX_FORMAT_RETRIES = 3     # 형식 오류(JSON 아님)로 다시 묻는 최대 횟수 — 내용 수정 1회와 별도
LINE_REPAIR_TRIES = 2      # 사실 검증에 걸린 줄을 줄 단위로 다시 쓰게 하는 횟수

REPAIR_SYSTEM = """당신은 사내 정식보고서 편집자입니다. 보고서 한 줄이 근거 원문과 사실이 다르다고 검증에서 걸렸습니다.
근거 원문의 사실(숫자·날짜·방향·확정 여부)과 정확히 같게, 보고서 말투(명사나 한자 약어로 끝, 마침표 없음, 20~40자)로
그 줄만 다시 쓰세요. 원문에 없는 숫자·날짜·요일·한자·평가는 넣지 않습니다. 근거 원문에 없는 내용이면 빼고 씁니다.
출력은 고친 줄 한 줄뿐입니다(말머리·설명·따옴표 없이)."""


def _raw_hint(raw: str) -> str:
    """형식 오류 진단: 응답 길이·앞부분·끝난 이유(원문이 아니라 LLM 응답만, 짧게)."""
    try:
        from .transform.llm_polish import LAST_CALL
    except ImportError:  # pragma: no cover
        LAST_CALL = {}
    head = re.sub(r"\s+", " ", raw or "")[:60]
    extra = ", ".join(f"{k}={v}" for k, v in LAST_CALL.items())
    return f"응답 {len(raw or '')}자, 앞부분 '{head}'" + (f", {extra}" if extra else "")


def _repair_lines(rewrite: Rewrite, facts: dict[int, list[str]], sentences: list[str], ask: Ask,
                  year: int | None) -> list[str]:
    """수정본에서도 사실 검증에 걸린 줄을 줄 단위로 다시 쓰게 한다(짧은 지시문 — 한 번에 한 가지). 통과하면 facts에서 뺀다."""
    from .transform.factcheck import check
    from .transform.report_style import hard_issues

    notes: list[str] = []
    for index in sorted(i for i in facts if i >= 0):
        line = rewrite.lines[index]
        if line.is_table or not line.src:
            continue
        source = " ".join(sentences[i - 1] for i in line.src)
        problems = facts[index]
        for _ in range(LINE_REPAIR_TRIES):
            user = (f"근거 원문:\n{source}\n\n고칠 줄: {line.text}\n검증에서 걸린 것: {', '.join(problems)}")
            try:
                answer = ask(REPAIR_SYSTEM, user)
            except Exception:  # noqa: BLE001
                return notes
            fixed = re.sub(r"^\s*(?:□|-|∙|→|※|\*|[①-⑳]|\d+\.)\s*", "", (answer or "").strip().splitlines()[0]
                           if (answer or "").strip() else "").strip().strip('"\'')
            if not fixed:
                continue
            problems = check(fixed, source, year=year)
            if not problems and not hard_issues(fixed):
                notes.append(f"줄 단위 다시 쓰기로 해결: '{line.text[:30]}' → '{fixed[:30]}'")
                line.text = fixed
                del facts[index]
                break
            problems = problems or ["서술체·구어체"]
    return notes


NUMBER_REPAIR_SYSTEM = """당신은 사내 정식보고서 편집자입니다. 보고서 한 줄에서 근거 원문의 숫자가 빠졌습니다.
근거 원문의 사실과 같게, 빠진 숫자를 모두 넣어 그 줄만 다시 쓰세요(합계와 내역이 있으면 둘 다: 합계 5,700만원 (코칭 4,500 + 워크숍 1,200)).
보고서 말투(명사나 한자 약어로 끝, 마침표 없음), 원문에 없는 숫자·평가는 넣지 않습니다. 출력은 고친 줄 한 줄뿐입니다(말머리·설명·따옴표 없이)."""


def _repair_numbers(rewrite: Rewrite, sentences: list[str], ask: Ask, year: int | None) -> list[str]:
    """수정본에도 숫자가 빠진 문장은 그 문장을 쓴 줄(표 아님) 하나를 줄 단위로 다시 쓰게 한다. 사실·문체 검증과 숫자 채움을 모두
    통과할 때만 채택하고, 아니면 그대로 둔다(--report의 '수치 누락'으로 사람이 본다)."""
    from .transform.factcheck import check, missing_numbers, uncovered_by_source
    from .transform.report_style import hard_issues

    notes: list[str] = []
    for i, numbers in uncovered_by_source(sentences, _cited_lines(rewrite)).items():
        holders = [l for l in rewrite.lines if i in l.src and not l.is_table]
        if not holders:
            continue
        line = holders[0]
        source = " ".join(sentences[j - 1] for j in line.src)
        for _ in range(LINE_REPAIR_TRIES):
            user = f"근거 원문:\n{source}\n\n고칠 줄: {line.text}\n빠진 숫자: {', '.join(numbers)}"
            try:
                answer = ask(NUMBER_REPAIR_SYSTEM, user)
            except Exception:  # noqa: BLE001
                return notes
            first = (answer or "").strip().splitlines()[0] if (answer or "").strip() else ""
            fixed = re.sub(r"^\s*(?:□|-|∙|→|※|\*|[①-⑳]|\d+\.)\s*", "", first).strip().strip('"\'')
            if not fixed:
                continue
            if check(fixed, source, year=year) or hard_issues(fixed):
                continue
            others = " ".join(l.content() for l in rewrite.lines if l is not line and i in l.src)
            if missing_numbers(sentences[i - 1], f"{fixed} {others}"):
                continue
            notes.append(f"수치 누락 줄 단위 보강: '{line.text[:25]}' → '{fixed[:40]}'")
            line.text = fixed
            break
    return notes


AUDIT_SYSTEM = """당신은 보고서 검수자입니다. 번호 붙은 원문 문장과 보고서가 주어집니다.
각 원문 문장의 핵심 정보(주장·이유·조건·대상·시점)가 보고서에 들어 있는지 확인하세요.
줄여 쓴 것, 표기가 바뀐 것, 말투가 바뀐 것은 빠진 것이 아닙니다. 의미 있는 정보가 통째로 없을 때만 빠진 것입니다.
출력은 JSON 하나뿐입니다: {"missing":[{"sent":문장번호,"info":"빠진 내용을 원문 말로 15자 안팎"}]}. 빠진 것이 없으면 {"missing":[]}."""

CONTENT_REPAIR_SYSTEM = """당신은 사내 정식보고서 편집자입니다. 보고서에서 근거 원문의 일부 정보가 빠졌습니다.
빠진 정보만 담은 보고서 한 줄을 쓰세요(명사나 한자 약어로 끝, 마침표 없음, 40자 이내).
원문에 없는 숫자·날짜·평가는 넣지 않고, 가능성은 가능성으로(수 있음), 범위 표현(이상·이하)은 그대로 옮깁니다.
출력은 그 한 줄뿐입니다(말머리·설명·따옴표 없이)."""

_CHILD_MARK = {"□": "-", "-": "∙", "∙": "∙", "①": "-", "→": "∙"}
MAX_AUDIT_ITEMS = 6


def _audit_content(rewrite: Rewrite, sentences: list[str], ask: Ask, year: int | None) -> list[str]:
    """LLM 검수: 인용한 문장의 핵심 정보가 보고서에서 통째로 빠졌는지 보고, 빠진 정보는 그 줄 아래 하위 항목으로 보강한다.
    사실·문체 검증을 통과한 줄만 넣는다. 어떤 실패도 조용히 건너뛴다(--report에 남기고 원래 줄을 유지)."""
    from .transform.factcheck import check
    from .transform.report_style import hard_issues

    notes: list[str] = []
    cited = {i for l in rewrite.lines for i in l.src}
    if not cited:
        return notes
    shown = "\n".join(f"[{i}] {sentences[i - 1]}" for i in sorted(cited) if 1 <= i <= len(sentences))
    body = "\n".join(f"{l.m} {l.content()}" if not l.is_table else f"{l.m} " + " / ".join(" ".join(r) for r in (l.rows or []))
                     for l in rewrite.lines)
    try:
        answer = ask(AUDIT_SYSTEM, f"원문 문장:\n{shown}\n\n보고서:\n{body}")
        data = json.loads(answer[answer.find("{"):answer.rfind("}") + 1])
        items = [(int(m["sent"]), str(m["info"]).strip()) for m in data.get("missing") or []]
    except Exception as exc:  # noqa: BLE001
        notes.append(f"내용 검수 건너뜀({type(exc).__name__})")
        return notes
    added = 0
    for sent, info in items[:MAX_AUDIT_ITEMS]:
        if sent not in cited or not info or not 1 <= sent <= len(sentences):
            continue
        holders = [k for k, l in enumerate(rewrite.lines) if sent in l.src]
        if not holders:
            continue
        source = sentences[sent - 1]
        try:
            reply = ask(CONTENT_REPAIR_SYSTEM, f"근거 원문:\n{source}\n\n빠진 정보: {info}")
        except Exception:  # noqa: BLE001
            return notes
        first = (reply or "").strip().splitlines()[0] if (reply or "").strip() else ""
        fixed = re.sub(r"^\s*(?:□|-|∙|→|※|\*|[①-⑳]|\d+\.)\s*", "", first).strip().strip('"\'')
        if not fixed or check(fixed, source, year=year) or hard_issues(fixed):
            notes.append(f"내용 누락 의심(보강 실패): 문장 [{sent}] — {info}")
            continue
        at = holders[-1]
        rewrite.lines.insert(at + 1, Line(_CHILD_MARK.get(rewrite.lines[at].m, "-"), fixed, [sent]))
        added += 1
        notes.append(f"내용 누락 보강: 문장 [{sent}] — {info} → '{fixed[:30]}'")
    return notes


def _coverage_notes(rewrite: Rewrite, sentences: list[str], body: str) -> list[str]:
    """사람이 검수할 것: 생략한 원문 문장, 보고서에 안 나온 원문 수치."""
    from .transform.factcheck import missing_numbers, uncovered_by_source

    notes: list[str] = []
    for i, numbers in uncovered_by_source(sentences, _cited_lines(rewrite)).items():
        notes.append(f"수치 누락(인용한 문장 [{i}] 기준): {', '.join(numbers)} — {sentences[i - 1][:40]}")
    used = {i for line in rewrite.lines for i in line.src}
    for i in sorted(set(rewrite.dropped) | (set(range(1, len(sentences) + 1)) - used)):
        if i not in used:
            notes.append(f"생략한 원문 문장 [{i}]: {sentences[i - 1]}")
    missing = missing_numbers(" ".join(sentences), body)
    if missing:
        notes.append(f"보고서에 안 나온 원문 수치(필요하면 넣을 것): {', '.join(missing)}")
    return notes


def draft(text: str, ask: Ask | None = None, mode: str = "rewrite", year: int | None = None,
          holdout: set[int] | None = None) -> DraftResult:
    """줄글 → 보고서 글. mode="rewrite"(기본: 말투를 다듬고 배열, 사실 검증) | "place"(원문 문장 그대로 배치만)."""
    if mode == "place":
        return place(text, ask)
    return rewrite(text, ask, year, holdout)
