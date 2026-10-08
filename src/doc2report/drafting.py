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
        "notes": [참고·단서·면책(\\"확인 필요\\", \\"~는 바뀔 수 있음\\" 등)로 따로 둘 문장 번호들]}}
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
말투는 보고서답게 바꾸되, 정보는 줄이지 않습니다. 원문을 보지 않은 상급자가 보고서만 읽고 내용을 정확히 이해해야 합니다.

[절대 규칙 1 — 사실을 바꾸지 않는다]
- 원문에 없는 사실·숫자·날짜·기한·요일·이름·평가를 만들지 않습니다. 숫자는 값 그대로, 표기만 바꿀 수 있습니다
  (11월 3일 → 11.3, 800만 원 → 800만원, 연 2억 원 → 2억원/년, 세 곳 → 3개, 셋째 주 → 3주차).
- 방향·정도·확정 여부를 바꾸지 않습니다(늘었다↔줄었다 금지, '검토 중'을 '확정'으로 바꾸기 금지).
- 가능성은 가능성으로: '지연될 수 있다' → '지연 우려' / '지연 가능성'(X '지연'), '계절에 따라 바뀔 수 있다' → '계절별 변동 가능'(X '상이').
- 수량·범위 표현 그대로: '일부' → '일부'(X '다수'), '2주 넘게' → '2주 이상'(X '2주'). 단서(약, 정도, 예정, 검토)는 남깁니다.
- 다른 뜻으로 읽히는 말을 새로 쓰지 않습니다(예: '매년' → '연차' X — 연차휴가로 읽힘).

[절대 규칙 2 — 정보를 빼지 않는다]
- 문장을 src로 쓰면 그 문장의 숫자(비교 기준값·작년 수치·기준표 비율·합계와 내역)를 모두 남깁니다
  (예: 총 900만원 (장비 600만원, 설치 300만원), 전년 750만원 대비 증가).
- 문장의 모든 절(이유·조건·법적 근거·주체·대상·시점)을 남깁니다. 줄이는 것은 군말·화자 표현·반복뿐입니다.
  "가능하지만 ~가 필요하고 ~가 든다"면 가능·필요·비용을 각각 씁니다.
- dropped에는 말투·개인 소감·같은 말 반복인 문장만 넣습니다. 숫자나 조건이 든 문장은 dropped에 넣지 않습니다.
- '빨라야 ~가능'(가장 이른 시점)과 '~에 추진'(계획)은 다른 사실입니다. 섞지 말고 각각 씁니다.

[절대 규칙 3 — 읽고 이해되는 말만 쓴다]
- 새 낱말을 만들지 않습니다. 원문 어구를 잘라 붙인 줄임말은 금지입니다
  (예: '나눠서 내는 방식' → '나눠내 방식' X, '분할 납부 방식' O). 줄일 때는 사전에 있는 낱말을 씁니다.
- 주체·대상·이유가 사라진 조각 어구를 쓰지 않습니다(X '합의 필요'만 덩그러니 → O '관련 법령상 노사 서면 합의 필요').

[구성]
- 보고서 유형에 맞게 절을 나눕니다(예):
  현황 보고 → □ 현황(항목명 : 값) → □ 추진 방향
  방안 검토 → 1. 배경 및 현황 / 2. 검토 방안(내용이 많고 복잡하면 표, 간단하면 ①②③) / 3. 추진 방향
  결과 보고 → □ 운영 경과 → □ 주요 결과 → □ (조정·후속) 결과 → □ 향후 계획
  추진 계획 → □ 개요(- 대상 : … / - 일정 : …) → □ 세부 내용 → □ 소요 예산
  이슈·건의 → 1. 배경 및 이슈 / 2. 검토 가능(안)(①②③) / 3. 건의 사항
- 표나 ①②③ 대안 목록은 반드시 그것을 부르는 절 제목("2. 검토 방안" 등) 아래에 둡니다. 제목 없이 표가 나오면 안 됩니다.
- 한 지표를 여러 단면으로 보여 주면 한 □ 아래 '- 구분 : 값'으로 나란히 씁니다(예: □ 지역별 판매 현황 아래 '- 권역별 : …',
  '- 매장 유형별 : …'). 그 수치에 대한 설명·평가(원인, 기준 대비 높고 낮음)는 그 수치 줄 아래 "∙"로 씁니다.
- □는 그 아래 내용을 대표하는 말로 씁니다(조정한 결과를 쓰면 '□ 조정 결과').
- 한 절 안에서 "□"와 "-"를 섞을 때는 □가 먼저이고 "-"는 □ 아래에만 둡니다. 절 바로 아래에 "-"를 쓰면 그 절에는 "□"를 쓰지 않습니다.
- 줄 글 맨 앞에 말머리(-, →, ※)를 또 쓰지 않습니다. 말머리는 m에만 씁니다. 결과·영향은 m을 "→"로, 윗줄의 부가 설명은 m을 "※"로 쓰고
  "-"와 겹치지 않습니다("-"는 나란한 항목에만 씁니다).
- 날짜 뒤에 점을 찍지 않습니다(8.22. X → 8.22 O, 8.22 ~ 23 O).
- 개요·계획의 구분은 '대상 / 일정 / 장소 / 예산'처럼 같은 종류로 나눕니다. 선발·접수·행사·발표 같은 세부 단계는 새 구분이
  아니라 '일정'의 하위(일정 : 접수(~3월 둘째 주), 발표(4월 첫째 주))로 묶습니다(X '- 대상 / - 접수 / - 발표').
- 한 □ 아래 '-'는 2~4개로 묶습니다. 같은 주제의 사실(원인과 그 근거 수치, 현황과 영향)은 한 '-'에 이어 써서 맥락이
  이어지게 하고, 낱말 몇 개씩 파편으로 나열하지 않습니다(X '- 물가 상승 / - 기준 노후 / - 응답 18명 / - 부담 발생'
  O '- 최근 3년간 물가 평균 15% 상승 / - 직원 20명 중 14명이 비용 부족으로 추가 부담 중').
- "→"는 꼭 필요할 때만 씁니다: 바로 윗줄의 직접적인 원인→결과(인과)이거나 절차·진행의 다음 단계일 때뿐입니다. 윗줄을 설명·보충하는
  내용, 참고, 나란한 계획은 "→"가 아니라 윗줄 아래의 "∙"(하위 설명)나 "※"(단서·참고)로 씁니다. 한 문서에 "→"는 많아야 한두 개입니다.
공석·결원은 '미채움'이라 쓰지 않고 '공석'이라고만 씁니다.
- 제목과 같은 말을 되풀이하는 줄(예: 제목이 '하반기 신입 연수 계획'인데 '하반기 신입 연수 운영')은 쓰지 않습니다. 그 문장은 dropped.
- 원문이 대안을 비교하면(첫째·둘째, 1안·2안, A안·B안) 내용의 양으로 형식을 고릅니다.
  · 두 안의 장점·단점을 비교하는 글은 항목이 적어도 표로 씁니다. 대안마다 장점·단점·조건이 여러 개씩이고 복잡하면 더욱 표입니다.
  · 대안이 3개 이상이거나, 장점·단점 비교가 아니라 대안마다 할 말이 한두 마디로 간단하면 ①②③ 줄로 쓰고, 안 이름 뒤에 쌍점으로 핵심(장·단점을 함께 요약)을
    한 줄로 붙입니다(O '① 점심시간 30분 연장 : 월 400만원 추가, 노사 협의 필요'). 안 이름을 되풀이하는 '내용' 줄이나
    '장점/단점' 소제목을 따로 만들지 않습니다. 더 쓸 말이 있을 때만 그 아래 짧은 "-" 한두 줄을 둡니다.
  표는 첫 행이 "구분 | (1안) … | (2안) …"(대안이 열)이고 그 아래 행(항목)은 행과 열을 바꾸지 않고 문서 내용에 맞게 정합니다
  (항목 이름과 개수는 문서마다 다릅니다: 내용·장점·단점/고려 사항, 효과·비용·리스크 등).
  **행은 그 항목에 대안별로 쓸 내용이 충분할 때만 만듭니다.** 한 칸에 "-" 한 줄뿐인 항목을 여러 개 만들어 표를 잘게 쪼개지 말고,
  성격이 비슷한 항목(단점·비용·일정·조건·제약 등)은 한 행(예: '단점/고려 사항')에 "-" 줄로 모아 담습니다. 행은 보통 2~4개입니다.
  내용이 얼마 없으면 표 대신 ①② 줄로 씁니다.
- 맨 위 단계는 "□"(절 제목 또는 핵심 문장). 대안을 비교·검토하는 문서는 "1."(번호 절)을 씁니다.
- "1." 아래 "□"는 묶음이 둘 이상이거나, "□" 자체가 내용을 담은 핵심 문장일 때만 씁니다. 내용 없는 항목명 "□" 하나만
  두지 않습니다(X '1. 배경' 아래 '□ 현황' 하나).
  · 현상·결론과 그 근거 수치가 있으면: "□ 핵심 문장" + 아래 "- 근거 수치"
    (O '□ 구성원 설문 결과, 근무 장소 관련 불만 高' / '- 응답자 120명 中 사무실 이전 희망 40%')
  · 나란한 사실뿐이면: "1. 배경 및 현황" 바로 아래 "-" 항목들. 절 제목에 '및'은 한 번만 씁니다.
- 결론·추진 방향의 요지는 "→"가 아니라 "□ 핵심 문장"으로 씁니다(□ 하나라도 핵심 문장이면 됩니다).
- 말머리(m): "1."(번호 절, text는 번호 없이), "□", "-"(세부), "∙"(- 아래 세부), "①" "②" "③"(안·계획 나열),
  "→"(윗줄의 직접 결과·다음 단계일 때만 — 설명·참고는 "∙" 또는 "※", 나란한 계획은 "-"), "※"(단서·확인 필요·후속 일정), "*"(바로 윗줄을 보충하는 참고 수치·기준), "표".
- 특정 대안에만 해당하는 내용(조건·비용·일정)은 그 대안의 표 칸이나 하위 항목(-, ∙)에 넣습니다.
- 사실 나열은 "항목명 : 값"으로 씁니다(교육 인원 : 총 120명 / 장 소 : 본사 대강당).
- 결론·제안은 마지막 절에 두고, 앞의 대안 번호를 다시 부릅니다(우선 ① …, 이후 ② …).

[문장]
- 화자·말투를 지웁니다(저는, 일단, ~입니다, 보고드립니다, ~로 보입니다, ~것 같습니다).
- 문장 끝은 명사나 한자 한 글자로 끝냅니다(추진, 검토, 예정, 필요, 확보, 高, 中, 可, 必).
  '~합니다', '~함', '~임', 마침표는 쓰지 않습니다.
- 한자 약어는 高 中 現 可 必 時 順 內 人 月 만 씁니다(협의 中, 확인 必, 점검時, 2회/人, 1회/月).
- 숫자: 만원·억원은 붙여 씁니다. 날짜 M.D, 기한 (~11.3일), 변화 (기존 10% → 15%), 분모 20명 中 16명.
- 특정 회사명(A사·B사)은 '경쟁사'로 묶습니다.
- 한 항목은 한 줄(공백 포함 32자 안팎)에 들어가게 씁니다. 넘으면 군더더기를 덜어 줄이고, 사실이 여럿이면 사실마다 항목을
  나눕니다(X '- 현장 실습 : 4명씩 5개 조로 나눠 지역 매장을 하나씩 맡아 운영한 뒤 11월 말 결과 발표'
  O '- 현장 실습 : 조별 매장 운영 및 11월 말 결과 발표(4명/조)').
- 높고 낮음은 '高·低' 또는 '높음·낮음'으로 씁니다('저조'의 반대말로 '고조'를 쓰지 않습니다 — '고조'는 분위기·긴장이 커진다는 뜻입니다).
- 날짜 줄과 맺음말("- 이 상 -")은 쓰지 않습니다(변환기가 붙입니다).

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
 {"m": "-", "text": "차년도 실습 1일 확대 검토", "src": [5]},
 {"m": "※", "text": "추가 예산 약 1,500만원 소요 예상, 재무팀 협의 필요", "src": [6]}],
 "dropped": [7]}

[대안 2개 예시]
원문:
[1] 사내 식당 혼잡 해소 방안은 두 가지입니다.
[2] 첫째는 배식 시간을 30분 늘리는 것인데 추가 인건비가 월 400만 원 정도 들고 노사 협의가 필요합니다.
[3] 둘째는 2층 휴게실을 식당으로 바꾸는 것인데 공사 기간이 6주 걸리고 공사비가 1억 원 정도이며 소방 점검을 다시 받아야 합니다.
출력:
{"title": "사내 식당 혼잡 해소 방안", "lines": [
 {"m": "1.", "text": "검토 방안", "src": [1]},
 {"m": "표", "rows": [["구분", "(1안) 배식 시간 30분 연장", "(2안) 2층 휴게실 식당 전환"],
   ["비용", "- 추가 인건비 약 400만원/月", "- 공사비 약 1억원"],
   ["고려 사항", "- 노사 협의 필요", "- 공사 기간 6주 소요\\n- 소방 점검 재수검 필요"]], "src": [2, 3]}],
 "dropped": []}
"""

FORMAT_TAIL = """
[출력 형식 — 반드시 지킴]
보고서를 글로 쓰지 말고, 아래 모양의 JSON 하나만 출력합니다. 첫 글자는 { 이고 마지막 글자는 } 입니다(설명·코드 블록 금지).
{"title": "보고서 제목(명사형)", "lines": [{"m": "□", "text": "...", "src": [1]}, {"m": "표", "rows": [["구분", "…"], ["…", "…"]], "src": [2, 3]}], "dropped": [번호, ...]}
"""

def system_prompt(exclude_docs: set[int] | None = None, base: str | None = None) -> str:
    """지시문 + 문장 → 보고서 줄 변환 예시(rules/report_style.yaml). exclude_docs는 채점용(그 정답에서 뽑은 예시를 뺀다)."""
    from .transform.report_style import examples_text

    shown = examples_text(exclude_docs=exclude_docs)
    base = base or REWRITE_SYSTEM
    if not shown:
        return base + FORMAT_TAIL
    # 출력 형식은 맨 끝에 둔다 — 글로 된 예시("보고서: …")로 끝나면 LLM이 JSON 대신 보고서 글을 쓴다(2026-10-07 실측: 형식 오류 3회)
    return (base + "\n[문장 변환 예시 — 말투만 이렇게 바꾸고, 정보는 줄이지 않으며 원문에 없는 사실은 넣지 않습니다]\n"
            + shown + "\n" + FORMAT_TAIL)


_ORDINAL = re.compile(r"^[①-⑳]$")
_SECTION_MARK = re.compile(r"^\d{1,2}\.$")
_PLAIN_MARKS = ("□", "-", "∙", "→", "※", "*")
_LABEL = re.compile(r"^(?P<label>[^:：\d][^:：]{0,15}?)\s*:\s+(?P<value>\S.*)$")
_POLITE_END = re.compile(r"(?:습니다|니다|어요|아요|해요|세요|입니다)\.?$")


@dataclass
class SynthSpec:
    """다문서 종합 모드(synthesis.py) — 원문 일부만 쓰는 것이 정상이라 '빠짐없이' 점검을 끄고 분량 점검을 켠다."""
    min_chars: int = 0     # 보고서 글자 수(공백 뺀) 목표 하한·상한 — 상한을 크게 넘으면 줄여 쓰게 한다
    max_chars: int = 0
    key_ids: list[int] = field(default_factory=list)   # 결론·제언·계획 절 문장 — 하나도 안 쓰면 다시 쓰게 한다


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
    warnings: list[str] = field(default_factory=list)


# LLM이 □ 대신 자판으로 치기 쉬운 글자를 쓰는 경우(2026-10-07 실측 응답 'ㅁ 배경 …')
_MARK_ALIASES = {"ㅁ": "□", "■": "□", "o": "□", "○": "□", "·": "∙", "ㆍ": "∙", "•": "∙", "(1)": "①", "(2)": "②", "(3)": "③"}


def _valid_mark(mark: str) -> bool:
    return mark in _PLAIN_MARKS or mark == "표" or bool(_ORDINAL.match(mark) or _SECTION_MARK.match(mark))


_TEXT_MARKER = re.compile(r"^([→※*□∙·ㅁ-]|[①-⑳]|\(\d{1,2}\))\s+")


def _split_text_marker(mark: str, text: str, warnings: list[str]) -> tuple[str, str]:
    """줄 글 맨 앞에 말머리가 또 들어 있으면 정리한다("- → 결과"처럼 겹쳐 찍히던 것 — 2026-10-09 사용자). →·※·*는 그 줄의
    성격을 정하는 말머리라 m을 그것으로 바꾸고, 그 밖의 말머리는 m과 겹치니 글에서 뗀다."""
    found = _TEXT_MARKER.match(text)
    if found is None or mark in ("표", "1.") or _SECTION_MARK.match(mark):
        return mark, text
    first = _MARK_ALIASES.get(found.group(1), found.group(1))
    paren = re.fullmatch(r"\((\d{1,2})\)", first)
    if paren and 1 <= int(paren.group(1)) <= 20:
        first = chr(ord("①") + int(paren.group(1)) - 1)
    rest = text[found.end():].strip()
    if not rest:
        return mark, text
    if _ORDINAL.match(first) and not _ORDINAL.match(mark):
        # "- (1) 방안 : …"처럼 원문자·번호 앞에 "-"가 겹치면 "-"를 뺀다(2026-10-09 사용자 건2)
        warnings.append(f"말머리 겹침 보정: '{mark}' + '{first}' → '{first}'")
        return first, rest
    if first in ("→", "※", "*") and first != mark:
        warnings.append(f"말머리 겹침 보정: '{mark}' + '{first}' → '{first}'")
        return first, rest
    if first == mark or first in ("□", "∙", "-"):
        warnings.append(f"말머리 겹침 보정: 글 앞 '{first}'를 뗌")
        return mark, rest
    return mark, text


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
    warnings: list[str] = []
    for item in data.get("lines") or []:
        mark = str(item.get("m") or "").strip()
        mark = _MARK_ALIASES.get(mark, mark)
        if mark in ("1", "2", "3", "4", "5", "6", "7", "8", "9"):
            mark += "."
        if not _valid_mark(mark):
            # 2026-10-07 실측(건4): m에 '대'처럼 말머리가 아닌 글자가 와 형식 오류가 났다. 줄 내용은 src로 검증되므로 "-"로 받고 알린다.
            if item.get("text") or item.get("rows"):
                warnings.append(f"알 수 없는 말머리 '{mark}'를 '-'로 보정")
                mark = "-"
            else:
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
        mark, text = _split_text_marker(mark, text, warnings)
        lines.append(Line(mark, text, src))
    if not lines:
        raise ValueError("줄이 하나도 없음")
    dropped = [int(i) for i in data.get("dropped") or [] if str(i).isdigit()]
    return Rewrite(str(data.get("title") or "").strip(), lines, dropped, warnings)


def review(rewrite: Rewrite, sentences: list[str], title: str, year: int | None,
           rules=None, synth: SynthSpec | None = None) -> tuple[dict[int, list[str]], list[str]]:
    """(줄 번호 → 사실 문제, 형식 문제 목록). 사실 문제가 남은 줄은 원문으로 바꾼다. 형식 문제는 다시 써 달라고만 한다."""
    from .transform.factcheck import check, coined_words, load_rules, uncovered_by_source
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
    if missing and synth is None:
        style.append(f"문장 {missing}이(가) 어느 줄의 src에도, dropped에도 없음")
    for index, line in enumerate(rewrite.lines):
        if line.src:
            made = coined_words(line.content(), " ".join(sentences[i - 1] for i in line.src if 1 <= i <= len(sentences)))
            if made:
                style.append(f"{index + 1}번째 줄에 원문 어구를 잘라 붙인 사전에 없는 말 {made} — 뜻이 통하는 낱말로 풀어 쓰세요")
    if synth is None and has_alternatives(sentences, rules):
        if not any(l.is_table or _ORDINAL.match(l.m) for l in rewrite.lines):
            style.append("원문이 대안을 비교하는데(첫째·둘째 등) 표도 ①② 줄도 없음 — 대안 2개면 표(구분/장점/단점·비용·조건 칸, "
                         "원문 절마다 한 줄), 3개 이상이면 ①②③ 줄로 쓰세요")
        if sum(1 for l in rewrite.lines if _SECTION_MARK.match(l.m)) < 2:
            # 2026-10-07 사용자: 정답은 1. 배경 / 2. 검토 방안 / 3. 추진 방향으로 체계적인데 결과는 □ 두 개로 뭉뚱그려졌다
            style.append("대안을 검토하는 보고서인데 번호 절이 없음 — 1. 배경 / 2. 검토 방안(표) / 3. 추진 방향처럼 "
                         "\"1.\" 절로 나누고 그 아래에 □·- 를 쓰세요")
    cell_limit = _table_cell_limit()
    for index, line in enumerate(rewrite.lines):
        if line.is_table:
            long = [p for p in _text_pieces(line) if len(re.sub(r"\s|^-", "", p)) > cell_limit]
            if long:
                style.append(f"{index + 1}번째 줄(표)의 칸 안 줄이 김({len(long)}개, 예: {long[0][:30]}) — 칸 안 한 줄에는 조건 하나만, "
                             f"공백 빼고 {cell_limit}자 이내의 명사형으로(예: '- 관련 법령상 노사 서면 합의 필요'). 내용은 빼지 말고 줄을 나누세요")
    if synth is not None and synth.max_chars:
        size = sum(len(re.sub(r"\s", "", piece)) for line in rewrite.lines for piece in _text_pieces(line))
        if size > synth.max_chars * 1.25:
            style.append(f"보고서가 공백 뺀 {size}자로 목표({synth.min_chars}~{synth.max_chars}자)보다 훨씬 김 — 핵심만 남기고 "
                         "과정·세부·중복·이전 시점 값은 빼세요(쓰지 않을 문장은 src에 넣지 마세요)")
    if synth is not None and synth.key_ids:
        cited = {i for line in rewrite.lines for i in line.src}
        lost = [i for i in synth.key_ids if i not in cited]
        if lost:
            style.append(f"결론·제언·계획 절의 문장 {lost}이(가) 어느 줄의 src에도 없음 — 결론·목표·절감 효과·결정 사항은 핵심이니 쓰고, "
                         "나중 문서에서 바뀐 계획이면 바뀐 내용을 쓴 줄의 src에 함께 넣으세요")
    ratio = _report_ratio(rewrite, sentences)
    if synth is None and ratio is not None and ratio < _min_ratio():
        style.append(f"보고서가 원문의 {ratio:.0%}로 과도하게 축약됨(기준 {_min_ratio():.0%} 이상) — 조건·이유·주체를 되살려 맥락을 알 수 있게 쓰고, 표 칸도 원문 절마다 한 줄로 모두 쓰세요")
    for i in sorted(set(rewrite.dropped)) if synth is None else []:
        if 1 <= i <= len(sentences) and re.search(r"\d", sentences[i - 1]) and i not in {j for l in rewrite.lines for j in l.src}:
            style.append(f"문장 [{i}]에 숫자가 있는데 dropped로 보냄 — 줄로 쓰고 숫자를 남기세요")
    for i, numbers in (uncovered_by_source(sentences, _cited_lines(rewrite), rules).items() if synth is None else []):
        style.append(f"문장 [{i}]의 수치 {', '.join(numbers)}이(가) 그 문장을 쓴 줄에 없음 — 줄에 넣거나, 숫자를 뺄 거면 그 문장을 dropped로")
    return facts, style


def has_alternatives(sentences: list[str], rules=None) -> bool:
    """원문이 대안을 비교하는 글인가(rules/drafting.yaml의 alternative_cues)."""
    from .transform.factcheck import load_rules

    rules = rules or load_rules()
    text = " ".join(sentences)
    # '방안은 세 가지' 같은 강한 단서는 하나로 충분하다(2026-10-08 사용자 건5: 단서가 하나뿐이라 번호 절·검토안 요구가 빠졌다)
    if any(re.search(cue, text) for cue in rules.alternative_strong_cues):
        return True
    return sum(1 for cue in rules.alternative_cues if re.search(cue, text)) >= 2


def _table_cell_limit() -> int:
    from .transform.report_style import load_rules

    return int(load_rules().limits.get("table_cell_chars", 32))


def _min_ratio() -> float:
    from .transform.report_style import load_rules

    return float(load_rules().limits.get("min_ratio", 0))


def _report_ratio(rewrite: Rewrite, sentences: list[str]) -> float | None:
    source = sum(len(re.sub(r"\s", "", t)) for t in sentences)
    if not source:
        return None
    mine = sum(len(re.sub(r"\s", "", l.content())) for l in rewrite.lines)
    return mine / source


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
            holdout: set[int] | None = None, *, prepared: tuple[str, list[str], str, str] | None = None,
            synth: SynthSpec | None = None, fallback=None) -> DraftResult:
    """다듬기 모드: 줄글 → 보고서 말투의 개조식 글(사실은 원문 그대로). 형식이 끝내 안 맞으면 배치 모드로.

    prepared = (제목, 번호 붙일 문장 목록, 사용자 메시지, 지시문) — 다문서 종합(synthesis.py)이 입력과 지시문을 직접 만들어 넘긴다.
    synth가 있으면 종합 모드: 문장을 다 쓰지 않아도 되고(빠짐 점검 끔) 분량을 점검한다."""
    import datetime

    if prepared is not None:
        title, sentences, prepared_user, prepared_system = prepared
    else:
        title, sentences = split_sentences(text)
    if not sentences:
        raise ValueError("문장을 찾지 못했습니다")
    ask_json = ask
    if ask is None:
        from .transform.llm_polish import ask_chat, ask_json
        ask = ask_chat
    year = year or datetime.date.today().year
    numbered = "\n".join(f"[{i}] {s}" for i, s in enumerate(sentences, 1))
    user = ((f"원문 제목: {title}\n" if title else "") + f"원문 문장 {len(sentences)}개:\n{numbered}"
            + "\n\n위 원문을 지시대로 다시 써서 JSON 하나로만 출력하세요(첫 글자는 {).")
    if prepared is not None:
        user = prepared_user
    notes: list[str] = []
    result: Rewrite | None = None
    facts: dict[int, list[str]] = {}
    message = user
    unavailable = False
    system = prepared_system if prepared is not None else system_prompt(holdout)
    format_errors = 0
    revised = 0
    while True:
        raw = ""
        try:
            raw = ask_json(system, message)
            try:
                candidate = parse_rewrite(raw, len(sentences))
            except ValueError as exc:
                # 2026-10-07 실측: JSON 대신 보고서 글('ㅁ 배경 및 이슈 - …')로 답했다. 같은 긴 지시문을 다시 보내면 같은 답이
                # 되풀이되므로, 그 글을 짧은 지시문으로 JSON(근거 번호 포함)으로 옮기게 한다 — LLM이 쓴 내용을 살린다.
                rescued = _rescue_plain_text(raw, numbered, len(sentences), ask_json)
                if rescued is None:
                    raise
                notes.append(f"LLM 다듬기 응답이 JSON이 아니라 글이어서 JSON으로 옮김 ({exc}; {_raw_hint(raw)})")
                candidate = rescued
        except ValueError as exc:
            # 형식 오류는 내용 수정 기회와 따로 센다(2026-10-05 실측: 첫 응답 형식 오류가 수정 기회를 먹어 사실 문제를
            # 다시 고쳐 쓰게 못 하고 원문으로 대체됐다)
            format_errors += 1
            notes.append(f"LLM 다듬기 응답 형식 오류 {format_errors}회: {exc} ({_raw_hint(raw)})")
            if format_errors >= MAX_FORMAT_RETRIES:
                break
            message = f"{user}\n\n[이전 응답의 문제] {exc}\n보고서 글이 아니라 JSON 하나만 출력하세요. 첫 글자는 {{ 입니다."
            continue
        except Exception as exc:  # noqa: BLE001 — 설정 없음·네트워크
            notes.append(f"LLM 호출 실패: {exc}")
            unavailable = True
            break
        facts, style = review(candidate, sentences, title, year, synth=synth)
        notes += [f"형식 보정: {w}" for w in candidate.warnings]
        result = candidate
        if not facts and not style:
            break
        notes.append(f"LLM 다듬기 {f'수정본 {revised}' if revised else '1차'} 검증: 사실 문제 {len(facts)}줄, 형식 문제 {len(style)}건")
        structural = [s for s in style if any(k in s for k in _STRUCTURAL_KEYS)]
        # 수정은 한 번이 기본, 구조 문제(표·번호 절·줄임말·긴 표 칸)가 남으면 한 번 더(2026-10-07: 검사가 늘어 한 번에 다 못 고침)
        if revised >= (2 if structural else 1):
            break
        revised += 1
        previous = raw[raw.find("{"):raw.rfind("}") + 1]
        message = (f"{user}\n\n[이전 응답]\n{previous}\n\n[검증에서 걸린 것 — 원문 사실과 다르거나 규칙 위반]\n"
                   f"{_problem_message(candidate, facts, style)}\n"
                   "걸린 줄만 원문 사실대로 고치고 나머지는 그대로 두어 JSON 전체를 다시 출력하세요.")
    if result is None:
        # 형식 오류가 끝내 안 풀리면 배치 모드(원문 문장 그대로 — 2026-10-07 실측 d2.docx가 100% 서술체)로 가지 않고
        # 원문 문장 끝만 규칙으로 개조식으로 바꾼 기본 구조를 쓴다.
        structure = fallback(title, sentences) if fallback is not None else fallback_structure(title, sentences)
        ruled = [_rule_sentence(sentence, year) for sentence in sentences]   # 종합이면 문서별로 이어 붙인 구조
        why = "LLM 설정이 없거나 연결 실패" if unavailable else "LLM 응답 형식 오류가 끝내 안 풀림"
        notes.append(f"규칙 기본 구조 사용({why}; 한 절, 문장마다 □ — 원문 문장, 끝만 규칙으로 개조식). "
                     "문장 압축·재배열은 하지 못했습니다")
        return DraftResult(render(structure, ruled), structure, notes, False, title=title,
                           mode="fallback", sections=len(structure.sections))

    if facts:
        notes += _repair_lines(result, facts, sentences, ask, year)
    notes += _restore_originals(result, facts, sentences, title, year)
    notes += _apply_style_fix(result, sentences, year)
    if synth is None:   # 종합은 원문의 일부만 쓰는 것이 정상이라 수치·내용을 '되살리는' 보강은 하지 않는다
        notes += _repair_numbers(result, sentences, ask, year)
    notes += _repair_coined(result, sentences, ask, year)
    if synth is None:
        notes += _audit_content(result, sentences, ask, year, ask_json)
    notes += _style_residue(result)
    # 마지막 상태를 한 번 더 점검해 남은 문제를 그대로 알린다(예전엔 "형식 문제 2건"이라는 개수만 남아 무엇이 남았는지 report로 알 수 없었다)
    try:
        _, leftover = review(result, sentences, title, year, synth=synth)
        notes += [f"최종 점검에서 남음: {item}" for item in leftover]
    except Exception:  # noqa: BLE001
        pass
    notes += orient_tables(result.lines)
    if synth is None:   # 종합은 같은 항목으로 여러 후보를 비교하는 표를 그대로 둔다(2026-10-08 사용자: 대체 공급사 3곳 비교는 표)
        notes += tables_to_ordinals(result.lines)
    notes += fix_change_arrows(result.lines)
    notes += consolidate_table_rows(result.lines)
    notes += compact_ordinals(result.lines)
    notes += drop_title_echoes(result, title)
    notes += lift_lone_groups(result.lines)
    notes += fix_level_order(result.lines)
    notes += fix_arrows(result.lines, sentences)
    notes += restrict_arrows(result.lines, sentences)
    notes += normalize_dates(result.lines, sentences)
    notes += add_weekdays(result.lines, sentences, year)
    tidy_labels(result.lines)
    body = rewrite_text(result)
    notes += _coverage_notes(result, sentences, body, synth=synth is not None)
    sections = sum(1 for line in result.lines if _SECTION_MARK.match(line.m)) or sum(
        1 for line in result.lines if line.m == "□")
    return DraftResult(body, None, notes, True, title=result.title or title, mode="rewrite", sections=sections)


RESCUE_SYSTEM = """당신은 보고서 정리 담당입니다. 번호 붙은 원문 문장과, 그 원문으로 이미 써 둔 보고서 글이 주어집니다.
보고서 글의 내용과 말머리·순서는 그대로 두고, 줄마다 근거 원문 문장 번호(src)를 붙여 JSON으로만 옮기세요.
"ㅁ"·"o" 같은 말머리는 "□"로, 번호 절 "1." 등은 m에 그대로, 표는 {"m": "표", "rows": [[칸, …], …]} 로 씁니다.
보고서 글에서 쓰이지 않은 원문 번호는 dropped에 넣습니다. 출력은 JSON 하나뿐입니다(첫 글자 {):
{"title": "...", "lines": [{"m": "□", "text": "...", "src": [1]}], "dropped": []}"""


def _rescue_plain_text(raw: str, numbered: str, count: int, ask_json: Ask) -> "Rewrite | None":
    """LLM이 JSON 대신 보고서 글을 썼을 때 — 그 글을 JSON(근거 번호 포함)으로 옮겨 받는다. 글이 아니거나 실패하면 None."""
    text = (raw or "").strip()
    if len(text) < 20 or not re.search(r"^\s*(?:□|ㅁ|-|∙|·|※|\*|→|[①-⑳]|\d+\.|o\s)", text, re.M):
        return None
    try:
        answer = ask_json(RESCUE_SYSTEM, f"원문 문장:\n{numbered}\n\n보고서 글:\n{text}")
        return parse_rewrite(answer, count)
    except Exception:  # noqa: BLE001
        return None


_STRUCTURAL_KEYS = ("표도 ①② 줄도 없음", "번호 절이 없음", "사전에 없는 말", "칸 안 줄이 김")
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
근거 원문의 사실과 같게, 빠진 숫자를 모두 넣어 그 줄만 다시 쓰세요(합계와 내역이 있으면 둘 다: 총 900만원 (장비 600만원, 설치 300만원)).
보고서 말투(명사나 한자 약어로 끝, 마침표 없음), 원문에 없는 숫자·평가는 넣지 않습니다. 출력은 고친 줄 한 줄뿐입니다(말머리·설명·따옴표 없이)."""


def _repair_numbers(rewrite: Rewrite, sentences: list[str], ask: Ask, year: int | None) -> list[str]:
    """수정본에도 숫자가 빠진 문장은 그 문장을 쓴 줄(표 아님) 하나를 줄 단위로 다시 쓰게 한다. 사실·문체 검증과 숫자 채움을 모두
    통과할 때만 채택하고, 아니면 그대로 둔다(--report의 '수치 누락'으로 사람이 본다)."""
    from .transform.factcheck import check, missing_numbers, uncovered_by_source
    from .transform.report_style import hard_issues

    notes: list[str] = []
    for i, numbers in uncovered_by_source(sentences, _cited_lines(rewrite)).items():
        holders = _number_holders(rewrite, i, sentences[i - 1])
        if not holders:
            continue
        if _repair_number_line(rewrite, holders, i, numbers, sentences, ask, year, notes):
            continue
        # 2026-10-08 사용자 실측: '응답자 312명'이 끝내 빠졌다 — 빠져서는 안 되는 수치. LLM 수리가 실패하면 원문의 '낱말 + 수치'를
        # 그 문장을 쓴 줄 끝 괄호로 붙인다(원문 글자 그대로라 사실이 바뀌지 않는다).
        line = holders[0]
        phrases = [_number_phrase(sentences[i - 1], n) for n in numbers]
        appended = f"{line.text} ({', '.join(phrases)})"
        if not check(appended, " ".join(sentences[j - 1] for j in line.src), year=year):
            notes.append(f"수치 누락 원문 어구로 보강: '{line.text[:25]}' 끝에 ({', '.join(phrases)})")
            line.text = appended
    return notes


def _number_holders(rewrite: Rewrite, i: int, sentence: str) -> list[Line]:
    """문장 i를 쓴 줄(표 아님) — 그 문장의 다른 숫자를 이미 담은 줄, 긴 줄 순. 내용 없는 항목명 줄('□ 현황')은 맨 뒤."""
    wanted = set(_NUMBER.findall(sentence))
    holders = [l for l in rewrite.lines if i in l.src and not l.is_table]
    return sorted(holders, key=lambda l: (_is_bare_label(l.text), -len(wanted & set(_NUMBER.findall(l.text))), -len(l.text)))


def _number_phrase(sentence: str, number: str) -> str:
    """원문에서 수치와 그 앞 낱말('응답자 312명') — 앞 낱말이 조사로 끝나거나 길면 수치만."""
    digits = ",?".join(re.escape(c) for c in number)       # 원문은 5,200처럼 쉼표가 있을 수 있다
    match = re.search(r"(?:([가-힣A-Za-z&]{1,8})\s+)?(" + digits + r"(?:[가-힣%]{0,2})(?:\s?원)?)", sentence)
    if not match:
        return number
    word = match.group(1) or ""
    if word and re.search(r"(?:은|는|이|가|을|를|에|의|로|와|과|도|만)$", word) and len(word) > 2:
        word = ""
    value = re.sub(r"\s+원$", "원", match.group(2))
    return f"{word} {value}".strip()


def _repair_number_line(rewrite: Rewrite, holders: list[Line], i: int, numbers: list[str], sentences: list[str],
                        ask: Ask, year: int | None, notes: list[str]) -> bool:
    from .transform.factcheck import check, missing_numbers
    from .transform.report_style import hard_issues

    for line in holders[:2]:
        source = " ".join(sentences[j - 1] for j in line.src)
        for _ in range(LINE_REPAIR_TRIES):
            user = f"근거 원문:\n{source}\n\n고칠 줄: {line.text}\n빠진 숫자: {', '.join(numbers)}"
            try:
                answer = ask(NUMBER_REPAIR_SYSTEM, user)
            except Exception:  # noqa: BLE001
                return False
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
            return True
    return False


AUDIT_SYSTEM = """당신은 보고서 검수자입니다. 원문 문장을 절로 나눈 목록([문장-절] 번호)과, 줄 번호가 붙은 보고서가 주어집니다.
1) **모든 절**에 대해, 그 절의 정보(이유·조건·법적 근거·주체·대상·시점·수치)가 들어 있는 보고서 줄 번호를 답하세요. 어느 줄에도 없으면 null.
   - 같은 낱말이 보고서에 있어도 그 절이 말하는 내용(필요·결정·발생·변경 등 서술)이 없으면 null입니다
     (예: 절이 "총량을 정해야 한다"인데 보고서에는 "총량 기준"이라는 말만 있고 정해야 한다는 내용이 없으면 null).
   - 줄여 쓴 것·표기나 말투가 바뀐 것은 들어 있는 것입니다(표는 칸 안 내용도 그 줄 번호로).
   - 화자 표현·소감('~라고 봅니다')·"방안은 두 가지입니다" 같은 군말 절만 null이어도 됩니다.
2) 원문을 보지 않고 보고서만 읽는 상급자가 뜻을 알 수 없는 줄(주체·대상·이유가 사라진 조각 어구, 사전에 없는 줄임말)을 찾으세요.
출력은 JSON 하나뿐: {"clauses":[{"id":"7-2","line":4},{"id":"7-3","line":null,"info":"빠진 내용을 원문 말로 15자 안팎"}],
"unclear":[{"line":보고서 줄 번호,"sent":근거 문장번호,"why":"왜 모르겠는지 10자 안팎"}]}. unclear가 없으면 빈 목록."""

CONTENT_REPAIR_SYSTEM = """당신은 사내 정식보고서 편집자입니다. 보고서에서 근거 원문의 일부 정보가 빠졌습니다.
빠진 정보만 담은 보고서 한 줄을 쓰세요(명사나 한자 약어로 끝, 마침표 없음, 40자 이내).
원문에 없는 숫자·날짜·평가는 넣지 않고, 가능성은 가능성으로(수 있음), 범위 표현(이상·이하)은 그대로 옮깁니다.
출력은 그 한 줄뿐입니다(말머리·설명·따옴표 없이)."""

CLARIFY_SYSTEM = """당신은 사내 정식보고서 편집자입니다. 보고서 한 줄이 너무 줄어 맥락을 알 수 없다고 검수에서 지적됐습니다.
근거 원문의 사실만으로, 주체·대상·이유(법적 근거 포함)를 되살려 그 줄만 다시 쓰세요(명사나 한자 약어로 끝, 마침표 없음, 50자 이내).
원문에 없는 숫자·날짜·평가는 넣지 않고, 가능성은 가능성으로, 범위 표현은 그대로 옮깁니다. 출력은 그 한 줄뿐입니다(말머리·설명·따옴표 없이)."""

_CHILD_MARK = {"□": "-", "-": "∙", "∙": "∙", "①": "-", "→": "∙"}
MAX_AUDIT_ITEMS = 12


# 쉼표, 그리고 낱말 끝 연결어미(~고·~며·~서·~는데·~지만)에서만 나눈다. '~에서'(장소)·'~만'(조사)·숫자 안('2천만 원')은 나누지 않는다.
_CLAUSE_SPLIT = re.compile(r"(?<=[,，])\s*|(?<=[가-힣][고며])\s+(?=[가-힣])(?!있)|(?<=[^에\s]서)\s+(?=[가-힣])|(?<=는데)\s+|(?<=지만)\s+")


def split_clauses(sentence: str) -> list[str]:
    """원문 문장 → 절(쉼표·~고·~며·~서·~는데·~지만에서 나눔). 검수 LLM이 절마다 닫힌 판정을 하게 한다."""
    parts = [p.strip(" ,，") for p in _CLAUSE_SPLIT.split(sentence) if p.strip(" ,，")]
    merged: list[str] = []
    carry = ""
    for part in parts:
        part = f"{carry} {part}".strip() if carry else part
        carry = ""
        if len(re.findall(r"[가-힣]{2,}", part)) < 2:     # '다만'처럼 짧은 조각은 다음 절에(끝이면 앞 절에) 붙인다
            carry = part
            continue
        merged.append(part)
    if carry:
        if merged:
            merged[-1] += " " + carry
        else:
            merged.append(carry)
    return merged or [sentence]


def _load_rules():
    from .transform.factcheck import load_rules

    return load_rules()


def _clause_sentence(item: dict) -> int:
    """검수 응답의 "clause": "7-2"(또는 예전 형식 "sent": 7) → 문장 번호."""
    if "clause" in item:
        return int(str(item["clause"]).split("-")[0].strip("[] "))
    return int(item["sent"])


_CONS_ROW = re.compile(r"단점|고려|조건|한계|제약|비용|리스크|위험|난점")
_PROS_ROW = re.compile(r"장점|효과|기대|이점")
_CONS_CLAUSE = re.compile(r"필요|비용|소요|어렵|어려|제한|우려|협의|부담|늦|지연|합의")


def _add_to_table(line: "Line", text: str, source: str) -> bool:
    """표로 쓴 대안 비교에서 빠진 절을 맞는 칸에 넣는다: 열 = 근거 문장과 낱말이 가장 많이 겹치는 대안,
    행 = 조건·비용류 절이면 단점·고려 사항 행, 아니면 장점 행. 알맞은 열·행을 못 고르면 False(표 아래 줄로 쓴다)."""
    rows = line.rows or []
    if len(rows) < 2 or len(rows[0]) < 3:
        return False
    stems = {w[:2] for w in re.findall(r"[가-힣]{2,}", source)}
    scores = []
    for col in range(1, len(rows[0])):
        cells = " ".join(row[col] for row in rows if col < len(row))
        scores.append((len(stems & {w[:2] for w in re.findall(r"[가-힣]{2,}", cells)}), col))
    best, col = max(scores)
    if best == 0 or sum(1 for score, _ in scores if score == best) > 1:
        return False
    wanted = _CONS_ROW if _CONS_CLAUSE.search(text) else _PROS_ROW
    row = next((r for r in rows[1:] if r and wanted.search(r[0])), None)
    if row is None or col >= len(row):
        return False
    row[col] = (row[col].rstrip() + "\n" if row[col].strip() else "") + f"- {text}"
    return True


def _repair_coined(rewrite: Rewrite, sentences: list[str], ask: Ask, year: int | None) -> list[str]:
    """수정본에도 남은 줄임말(원문 어구를 잘라 붙인 말)을 줄 단위로 풀어 쓰게 한다. 줄임말이 사라지고 사실·문체 검증을
    통과할 때만 채택하고, 아니면 그대로 두고 --report에 남긴다."""
    from .transform.factcheck import check, coined_words
    from .transform.report_style import hard_issues

    notes: list[str] = []

    def fix_piece(piece: str, source: str, made: list[str]) -> str:
        for _ in range(LINE_REPAIR_TRIES):
            try:
                reply = ask(CLARIFY_SYSTEM, f"근거 원문:\n{source}\n\n고칠 줄: {piece}\n"
                                            f"문제: 사전에 없는 줄임말 {made} — 원문의 뜻이 통하는 낱말로 풀어 쓸 것")
            except Exception:  # noqa: BLE001
                return ""
            first = (reply or "").strip().splitlines()[0] if (reply or "").strip() else ""
            fixed = re.sub(r"^\s*(?:□|-|∙|→|※|\*|[①-⑳]|\d+\.)\s*", "", first).strip().strip('"\'')
            if fixed and not coined_words(fixed, source) and not check(fixed, source, year=year) and not hard_issues(fixed):
                return fixed
        return ""

    for line in rewrite.lines:
        if not line.src:
            continue
        source = " ".join(sentences[i - 1] for i in line.src if 1 <= i <= len(sentences))
        if line.is_table:
            # 2026-10-07 사용자 PC 재현: 표 칸 안의 '몰아일'은 수리 대상이 아니라 재작성 두 번 뒤에도 남고 --report에도 안 나왔다.
            for row in line.rows or []:
                for col, cell in enumerate(row):
                    parts = cell.split("\n")
                    for k, part in enumerate(parts):
                        made = coined_words(part, source)
                        if not made:
                            continue
                        mark = "- " if part.lstrip().startswith("-") else ""
                        fixed = fix_piece(re.sub(r"^\s*-\s*", "", part), source, made)
                        if fixed:
                            notes.append(f"줄임말 풀어 씀(표 칸) {made}: '{part[:25]}' → '{fixed[:40]}'")
                            parts[k] = mark + fixed
                        else:
                            notes.append(f"줄임말 남음(표 칸, 고치지 못함) {made}: {part[:40]}")
                    row[col] = "\n".join(parts)
            continue
        made = coined_words(line.text, source)
        if not made:
            continue
        fixed = fix_piece(line.text, source, made)
        if fixed:
            notes.append(f"줄임말 풀어 씀 {made}: '{line.text[:25]}' → '{fixed[:40]}'")
            line.text = fixed
        else:
            notes.append(f"줄임말 남음(고치지 못함) {made}: {line.text[:40]}")
    return notes


def _audit_content(rewrite: Rewrite, sentences: list[str], ask: Ask, year: int | None,
                   ask_json: Ask | None = None) -> list[str]:
    """LLM 검수: 인용한 문장의 핵심 정보가 보고서에서 통째로 빠졌는지 보고, 빠진 정보는 그 줄 아래 하위 항목으로 보강한다.
    사실·문체 검증을 통과한 줄만 넣는다. 어떤 실패도 조용히 건너뛴다(--report에 남기고 원래 줄을 유지)."""
    from .transform.factcheck import check
    from .transform.report_style import hard_issues

    notes: list[str] = []
    cited = {i for l in rewrite.lines for i in l.src}
    if not cited:
        return notes
    # 절 단위로 닫힌 질문을 한다 — "빠진 게 있나"라는 열린 질문에는 실측에서 매번 '없음'만 돌아왔다(2026-10-07)
    shown = "\n".join(f"[{i}-{k}] {clause}" for i in sorted(cited) if 1 <= i <= len(sentences)
                      for k, clause in enumerate(split_clauses(sentences[i - 1]), 1))
    # 줄 번호를 붙여 보낸다 — 예전엔 번호 없이 보내고 '줄 번호'를 물어 LLM이 가리킬 수가 없었다
    body = "\n".join(f"{n}) {l.m} {l.content()}" if not l.is_table
                     else f"{n}) 표 " + " / ".join(" | ".join(r) for r in (l.rows or []))
                     for n, l in enumerate(rewrite.lines, 1))
    try:
        answer = (ask_json or ask)(AUDIT_SYSTEM, f"원문 절:\n{shown}\n\n보고서:\n{body}")
        data = json.loads(answer[answer.find("{"):answer.rfind("}") + 1])
        items = [(_clause_sentence(m), str(m.get("info") or "").strip()) for m in data.get("missing") or []]
        clause_text = {f"{i}-{k}": c for i in sorted(cited) if 1 <= i <= len(sentences)
                       for k, c in enumerate(split_clauses(sentences[i - 1]), 1)}
        for m in data.get("clauses") or []:
            line_no = m.get("line")
            if not isinstance(line_no, int) or not 1 <= line_no <= len(rewrite.lines):
                cid = str(m.get("id") or "").strip("[] ")
                skip = _load_rules().audit_skip_clause
                if cid in clause_text and not any(re.search(pat, clause_text[cid]) for pat in skip):
                    items.append((_clause_sentence({"clause": cid}), str(m.get("info") or clause_text[cid])[:40]))
        unclear = [(int(m["line"]), int(m["sent"]), str(m.get("why") or "").strip()) for m in data.get("unclear") or []]
    except Exception as exc:  # noqa: BLE001
        notes.append(f"내용 검수 건너뜀({type(exc).__name__})")
        return notes
    for number, sent, why in unclear[:MAX_AUDIT_ITEMS]:
        if not 1 <= number <= len(rewrite.lines) or not 1 <= sent <= len(sentences):
            continue
        line = rewrite.lines[number - 1]
        if line.is_table or sent not in line.src:
            notes.append(f"이해 불가 의심(고치지 못함): {number}번째 줄 — {why}")
            continue
        source = sentences[sent - 1]
        try:
            reply = ask(CLARIFY_SYSTEM, f"근거 원문:\n{source}\n\n고칠 줄: {line.text}\n문제: {why}")
        except Exception:  # noqa: BLE001
            return notes
        first = (reply or "").strip().splitlines()[0] if (reply or "").strip() else ""
        fixed = re.sub(r"^\s*(?:□|-|∙|→|※|\*|[①-⑳]|\d+\.)\s*", "", first).strip().strip('"\'')
        if not fixed or check(fixed, source, year=year) or hard_issues(fixed):
            notes.append(f"이해 불가 의심(고치지 못함): {number}번째 줄 — {why}")
            continue
        notes.append(f"이해 불가 줄 풀어 씀: '{line.text[:20]}' → '{fixed[:40]}'")
        line.text = fixed
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
        if rewrite.lines[at].is_table and _add_to_table(rewrite.lines[at], fixed, source):
            added += 1
            notes.append(f"내용 누락 보강(표 칸): 문장 [{sent}] — {info} → '{fixed[:30]}'")
            continue
        rewrite.lines.insert(at + 1, Line(_CHILD_MARK.get(rewrite.lines[at].m, "-"), fixed, [sent]))
        added += 1
        notes.append(f"내용 누락 보강: 문장 [{sent}] — {info} → '{fixed[:30]}'")
    return notes


def _coverage_notes(rewrite: Rewrite, sentences: list[str], body: str, synth: bool = False) -> list[str]:
    """사람이 검수할 것: 생략한 원문 문장, 보고서에 안 나온 원문 수치. 종합이면 뺀 것이 많으니 숫자 든 문장만 따로 모아 알린다."""
    from .transform.factcheck import missing_numbers, uncovered_by_source

    notes: list[str] = []
    if synth:
        used = {i for line in rewrite.lines for i in line.src}
        left = [i for i in range(1, len(sentences) + 1) if i not in used]
        notes.append(f"종합: 원문 문장 {len(sentences)}개 중 {len(used)}개를 근거로 씀, {len(left)}개는 뺌")
        notes += [f"뺀 원문 문장 [{i}]: {sentences[i - 1]}" for i in left if re.search(r"\d", sentences[i - 1])]
        return notes
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


# 남은 문제로 세는 판단 노트의 머리말(원문 글자 없이 개수만 셀 수 있게)
_LEFTOVER_PREFIXES = ("최종 점검에서 남음", "줄임말 남음", "이해 불가 의심", "내용 누락 의심", "수치 누락(")


def problem_count(result: DraftResult) -> int:
    """후보 비교용 점수 — 형식 오류 + 원문 대체 + 끝내 못 고친 문제 수(작을수록 좋다). 배치·규칙 기본 구조는 크게 감점."""
    notes = result.notes
    score = sum(1 for n in notes if "형식 오류" in n)
    score += sum(1 for n in notes if "원문 문장으로 대체" in n)
    score += sum(1 for n in notes if n.startswith(_LEFTOVER_PREFIXES))
    if result.mode != "rewrite":
        score += 1000
    return score


def brief(result: DraftResult, source: str, year: int | None = None) -> str:
    """한 줄 요약 블록(원문 글자 없이 개수·유형만) — `draft` 명령 끝에 출력해 문서를 읽지 않고도 상태를 판단하게 한다.

    정답 글이 없는 실사용용이라 정답 대비 항목(핵심수치 보존 등)은 없다. 그건 tools/eval_drafting.py."""
    import datetime

    from .transform.factcheck import check, load_rules
    from .transform.report_style import lint

    year = year or datetime.date.today().year
    rules = load_rules()
    body = source.split("\n", 1)[1] if "\n" in source else source
    chars = lambda t: len(re.sub(r"\s", "", t))  # noqa: E731
    lines = [l for l in result.text.splitlines() if l.strip()]
    contents = [re.sub(r"^\s*(\d{1,2}\.|[□\-∙·→※*①-⑳])\s*", "", l) for l in lines[1:]]
    hard = sum(1 for t in contents if any(i.hard for i in lint(t)))
    invented = {p for t in contents for p in check(t, body, rules, year)
                if any(k in p for k in ("숫자", "금액", "비율", "날짜", "요일"))}
    notes = result.notes
    count = lambda *keys: sum(1 for n in notes if n.startswith(keys))  # noqa: E731
    table = "표" if any("\t" in l for l in lines) else ("①②" if any(l.lstrip().startswith("①") for l in lines) else "없음")
    numbered = sum(1 for l in lines if re.match(r"\s*\d+\.\s", l))
    ratio = f"{chars(chr(10).join(lines)) / max(chars(body), 1):.0%}"
    return (f"분량 {ratio} | 서술체 {hard} | 수치왜곡 {len(invented)}"
            f" | 형식오류 {sum(1 for n in notes if '형식 오류' in n)}회"
            f" | 원문대체 {sum(1 for n in notes if '원문 문장으로 대체' in n)}"
            f" | 수치누락 {count('수치 누락(')} | 줄임말 남음 {count('줄임말 남음')}"
            f" | 이해불가 남음 {count('이해 불가 의심')} | 내용 누락 의심 {count('내용 누락 의심')}"
            f"\n방식 {result.mode} | 대안표 {table} | 번호절 {numbered}"
            f" | 검증회차 {sum(1 for n in notes if '검증: 사실 문제' in n)} | 남은 문제 {problem_count(result)}")


def draft_best(text: str, runs: int = 1, ask: Ask | None = None, mode: str = "rewrite", year: int | None = None,
               holdout: set[int] | None = None) -> DraftResult:
    """같은 입력을 runs번 돌려 남은 문제(`problem_count`)가 가장 적은 결과를 쓴다(같으면 먼저 나온 것).

    LLM은 온도 0이어도 실행마다 결과가 달라진다(2026-10-07 실측: 같은 입력으로 구조·칸이 갈림). 채택하지 않은 후보의
    점수는 notes에 남긴다 — 후보를 조용히 버리지 않는다."""
    results: list[DraftResult] = []
    for _ in range(max(1, runs) if mode == "rewrite" else 1):
        results.append(draft(text, ask, mode, year, holdout))
        if problem_count(results[-1]) == 0:
            break  # 더 돌려 봐야 나아질 게 없다
    best = min(results, key=problem_count)  # min은 동점이면 먼저 나온 것
    if len(results) > 1:
        scores = ", ".join(f"{i}번째 {problem_count(r) if problem_count(r) < 1000 else '배치·기본 구조'}" for i, r in enumerate(results, 1))
        best.notes.append(f"여러 번 실행({len(results)}회) 후 {results.index(best) + 1}번째 결과 채택 — 남은 문제 점수: {scores}")
    return best


# ── 구조 보정 (2026-10-08 사용자) ──────────────────────────────────────────────

_ATTRIBUTE_HEAD = re.compile(r"장점|단점|효과|기대|이점|고려|조건|한계|제약|비용|리스크|위험|난점|내용|요건|일정|개요|방식|시행|기간")
_OPTION_HEAD = re.compile(r"안\)|안$|^\(?\d안|첫째|둘째|셋째|[①-⑳]|^[A-C]안")


def orient_tables(lines: list[Line]) -> list[str]:
    """대안 비교 표는 대안이 열, 항목(장점·단점·비용)이 행이다. LLM이 뒤집어 쓰면(첫 행이 장점·단점…, 첫 열이 1안·2안) 행과 열을
    바꾼다 — 단점 칸이 좁은 열에 몰려 표 균형이 깨졌다(2026-10-08 사용자)."""
    notes: list[str] = []
    for line in lines:
        rows = line.rows
        if not rows or len(rows) < 2 or len({len(r) for r in rows}) != 1 or len(rows[0]) < 3:
            continue
        head = rows[0][1:]
        first_col = [r[0] for r in rows[1:]]
        if (sum(1 for c in head if _ATTRIBUTE_HEAD.search(c)) >= 2
                and sum(1 for c in first_col if _OPTION_HEAD.search(c.strip())) >= 2
                and not any(_ATTRIBUTE_HEAD.search(c) for c in first_col)):
            line.rows = [list(col) for col in zip(*rows)]
            notes.append("구조 보정: 대안 비교 표의 행·열을 바꿈(대안이 열, 장점·단점 등이 행)")
    return notes


def _is_bare_label(text: str) -> bool:
    """내용 없는 항목명('현황', '단계적 추진 계획') — 숫자·쌍점·쉼표 없고 공백 빼고 12자 이하, 문장 끝 서술(高·필요 등) 없음."""
    body = re.sub(r"\s", "", text)
    return (0 < len(body) <= 12 and not re.search(r"[\d:：,，()（）]", body)
            and not re.search(r"(?:高|低|中|可|必|필요|예정|추진|확보|완료|증가|감소|발생|부족)$", body))


def lift_lone_groups(lines: list[Line]) -> list[str]:
    """번호 절(1.) 아래 □가 하나뿐이고 그 □가 내용 없는 항목명이면 □를 빼고 절 제목에 합친다(2026-10-08 사용자 원칙:
    '1. 배경 / □ 현황 / - …' → '1. 배경 및 현황 / - …'). □가 핵심 문장이거나 둘 이상이면 그대로 둔다."""
    notes: list[str] = []
    starts = [k for k, l in enumerate(lines) if _SECTION_MARK.match(l.m)]
    for at in reversed(starts):
        end = next((k for k in range(at + 1, len(lines)) if _SECTION_MARK.match(lines[k].m)), len(lines))
        boxes = [k for k in range(at + 1, end) if lines[k].m == "□"]
        if len(boxes) != 1:
            continue
        box = lines[boxes[0]]
        has_children = any(lines[k].m not in ("□", "표") for k in range(boxes[0] + 1, end))
        if not has_children or not _is_bare_label(box.text):
            continue
        section = lines[at]
        label, heading = box.text.strip(), section.text.strip()
        children = [k for k in range(boxes[0] + 1, end) if lines[k].m in ("-", "→")]
        if (len(children) >= 2 and not _NUMBER.search(lines[children[0]].text) and not _LABEL.match(lines[children[0]].text)
                and all(_NUMBER.search(lines[k].text) for k in children[1:])):
            # 첫 '-'가 현상·결론이고 나머지가 그 근거 수치면, 그 첫 줄을 □ 핵심 문장으로 올린다(2026-10-08 사용자 건2:
            # '□ R&D 조직 설문 결과, 불만 高' 아래 '- 응답자 312명 중 …')
            first = lines[children[0]]
            box.text, box.src = first.text, sorted(set(box.src) | set(first.src))
            del lines[children[0]]
            notes.append(f"구조 보정: '{heading}' 절의 항목명 □ '{label}' 대신 첫 항목을 □ 핵심 문장으로 올림 — 아래 수치 항목은 그 근거")
            continue
        # 절 제목에 이미 '및'이나 괄호가 있으면 더 붙이지 않는다('배경 및 현황 및 설문 결과' X — 2026-10-08 사용자)
        if label.replace(" ", "") not in heading.replace(" ", "") and not re.search(r"\s및\s|[()（）]", heading):
            joined = f"{heading} 및 {label}" if len(label.replace(" ", "")) <= 4 else f"{heading} ({label})"
            section.text = joined
        section.src = sorted(set(section.src) | set(box.src))
        del lines[boxes[0]]
        notes.append(f"구조 보정: '{heading}' 절 아래 하나뿐인 항목명 □ '{label}'를 빼고 절 제목을 '{section.text}'로")
    return notes


def fix_arrows(lines: list[Line], sentences: list[str], rules=None) -> list[str]:
    """'→'는 바로 윗줄의 결과·목표에만 쓴다(2026-10-08 사용자). 절(1.) 바로 아래 첫 줄이면 □로, 근거 원문이 병렬 표현
    ('같이 검토'·'아울러' 등, rules/drafting.yaml::parallel_cues)이면 '-'로 바꾼다."""
    cues = (rules or _load_rules()).parallel_cues
    notes: list[str] = []
    for k, line in enumerate(lines):
        if line.m != "→" or k == 0:
            continue
        if _SECTION_MARK.match(lines[k - 1].m):
            line.m = "□"
            notes.append(f"구조 보정: 절 바로 아래 '→' 줄을 □로 — {line.text[:20]}")
        elif line.src and all(any(re.search(c, sentences[i - 1]) for c in cues)
                              for i in line.src if 1 <= i <= len(sentences)):
            line.m = "-"
            notes.append(f"구조 보정: 윗줄의 결과가 아닌 병렬 항목이라 '→'를 '-'로 — {line.text[:20]}")
    return notes


def _stems(text: str) -> set[str]:
    return {w[:2] for w in re.findall(r"[가-힣]{2,}", text)}


def drop_title_echoes(rewrite: Rewrite, title: str) -> list[str]:
    """제목을 되풀이할 뿐인 줄(숫자 없음, 낱말 60% 이상이 제목과 같음)은 뺀다(2026-10-08 사용자 건4: '차세대 리더 육성
    프로그램 …'이 제목과 같은 말). 근거 문장은 생략(dropped)으로 남긴다. 그 결과 아래가 빈 항목명 □는 같이 뺀다."""
    heading = _stems(f"{title} {rewrite.title}")
    notes: list[str] = []
    keep: list[Line] = []
    for line in rewrite.lines:
        words = _stems(line.text)
        if (not line.is_table and line.m in ("-", "∙", "→", "□") and not _NUMBER.search(line.text)
                and ":" not in line.text and len(words) >= 3 and len(words & heading) / len(words) >= 0.6):
            rewrite.dropped = sorted(set(rewrite.dropped) | set(line.src))
            notes.append(f"구조 보정: 제목과 같은 말을 되풀이한 줄을 뺌 — {line.text[:30]}")
            continue
        keep.append(line)
    rewrite.lines[:] = [l for k, l in enumerate(keep)
                        if not (l.m == "□" and _is_bare_label(l.text)
                                and (k + 1 == len(keep) or keep[k + 1].m in ("□", "표") or _SECTION_MARK.match(keep[k + 1].m)))]
    return notes


_ORDINALS = "①②③④⑤⑥⑦⑧⑨"
ORDINAL_ITEMS_MAX = 3      # 대안 2개 비교 표에서, 대안마다 항목이 이 개수 이하면 표 대신 ①② 줄(내용이 간단하다고 본다)


_CHANGE_ARROW = re.compile(
    r"(?P<new>\S[^()]*?)\s*\(\s*(?P<was>기존|당초|종전|이전)\s*(?P<old>[^()→]*?\d[^()→]*?)\s*→\s*(?P<why>[^()]+?)\s*\)")
_VALUE_LIKE = re.compile(r"^[~약\s]*[\d,.]+\s*(?:%p?|[가-힣]{0,3})\s*$")   # "28주", "30%", "3,900만원" — 화살표 뒤에 와도 되는 값


def fix_change_arrows(lines: list[Line]) -> list[str]:
    """'28주 (기존 26주 → 8월 전력 제한 영향)'처럼 화살표 뒤에 값이 아니라 사유를 쓴 것을 '기존 26주 → 28주 (8월 전력 제한 영향)'으로.
    화살표는 두 값 사이에만 쓴다(2026-10-08 사용자, 종합 실측 A). 새 값에 숫자가 있고 화살표 뒤에는 숫자가 없을 때만 고친다."""
    notes: list[str] = []

    def mend(text: str) -> str:
        def swap(m: re.Match) -> str:
            new, old, why = m.group("new").strip(), m.group("old").strip(), m.group("why").strip()
            if not re.search(r"\d", new) or _VALUE_LIKE.match(why):
                return m.group(0)
            return f"{m.group('was')} {old} → {new} ({why})"
        label = re.match(r"^(\s*-\s+)?(.*?:\s*)?", text)
        head, body = (text[:label.end()], text[label.end():]) if label else ("", text)
        fixed = head + _CHANGE_ARROW.sub(swap, body)
        if fixed != text:
            notes.append(f"변화 표기 보정(화살표는 값 사이에만): '{text[:34]}' → '{fixed[:34]}'")
        return fixed

    for line in lines:
        if line.rows is None:
            line.text = mend(line.text)
        else:
            line.rows = [row[:1] + ["\n".join(mend(p) for p in cell.split("\n")) for cell in row[1:]] for row in line.rows]
    return notes


def tables_to_ordinals(lines: list[Line]) -> list[str]:
    """대안이 셋 이상이거나 내용이 간단한(대안마다 항목 3개 이하) 비교 표는 ①②③ 줄로 바꾼다 — 안을 나열해 설명하는 편이 읽기 쉽다(2026-10-08 사용자 건5,
    정답 5와 같은 방식). 항목마다 '- 항목 : 내용' 줄로 풀어 둔 것을 `compact_ordinals`가 한 줄 요약으로 줄인다."""
    notes: list[str] = []
    out: list[Line] = []
    for line in lines:
        rows = line.rows
        options = rows[0][1:] if rows else []
        if (not rows or len(options) < 2 or len(options) > len(_ORDINALS) or len({len(r) for r in rows}) != 1
                or sum(1 for c in options if _OPTION_HEAD.search(c.strip())) < 2):
            out.append(line)
            continue
        if len(options) == 2:
            # 장점·단점을 비교하는 두 안은 표가 적합하다(2026-10-09 사용자: 문서 2가 칸마다 한 줄이라 ①②로 바뀌었다).
            labels = [r[0].replace("\n", " ") for r in rows[1:]]
            if any(_TABLE_PROS.search(l) for l in labels) and any(re.search(r"단점|고려|한계|제약|리스크|위험", l) for l in labels):
                out.append(line)
                continue
            # 그 밖의 두 안은 내용이 간단하면(대안마다 항목이 ORDINAL_ITEMS_MAX개 이하) 표보다 ①② 줄이 낫다
            counts = [sum(len([i for i in row[j].split("\n") if i.strip(" -")]) for row in rows[1:]) for j in (1, 2)]
            if max(counts) > ORDINAL_ITEMS_MAX:
                out.append(line)
                continue
        for j, option in enumerate(options, 1):
            name = re.sub(r"^\(?\s*(?:\d|[A-C])\s*안\s*\)?\s*", "", option.replace("\n", " ")).strip() or option
            out.append(Line(_ORDINALS[j - 1], name, list(line.src)))
            for row in rows[1:]:
                pieces = [re.sub(r"^\s*-\s*", "", p).strip() for p in row[j].split("\n") if p.strip(" -")]
                attr = row[0].replace("\n", " ").strip()
                if pieces:
                    out.append(Line("-", f"{attr} : {', '.join(pieces)}", list(line.src)))
        notes.append(f"구조 보정: 대안 {len(options)}개 비교 표를 ①②③ 줄로 바꿈")
    lines[:] = out
    return notes


_WEEKDAYS = "월화수목금토일"


def add_weekdays(lines: list[Line], sentences: list[str], year: int | None) -> list[str]:
    """보고서 날짜 M.D 뒤에 요일을 붙인다(9.5 → 9.5(토), 2026-10-08 사용자). 근거 원문에 'M월 D일'이 있을 때만 — 9.5점 같은
    소수와 헷갈리지 않게. 요일은 달력으로 계산한다."""
    import datetime

    if not year:
        return []
    notes: list[str] = []
    pattern = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})(?![\d.%]|\s*\(|일|점|배|명|건|개|회|시간|년)")

    def fix(text: str, source: str) -> str:
        def one(m: re.Match) -> str:
            month, day = int(m.group(1)), int(m.group(2))
            if not re.search(rf"(?<!\d){month}\s*월\s*{day}\s*일", source):
                return m.group(0)
            try:
                weekday = _WEEKDAYS[datetime.date(year, month, day).weekday()]
            except ValueError:
                return m.group(0)
            return f"{m.group(0)}({weekday})"
        text = pattern.sub(one, text)

        def end_of_range(m: re.Match) -> str:
            # "8.22(토) ~ 23" → "8.22(토) ~ 23(일)": 범위 끝 날짜는 앞 날짜와 같은 달(2026-10-08 사용자)
            month, day = int(m.group(1)), int(m.group(3))
            try:
                weekday = _WEEKDAYS[datetime.date(year, month, day).weekday()]
            except ValueError:
                return m.group(0)
            return f"{m.group(0)}({weekday})"
        return re.sub(r"(?<![\d.])(\d{1,2})\.(\d{1,2})\([월화수목금토일]\)\s*~\s*(\d{1,2})(?![\d.월일]|\([월화수목금토일]\))",
                      end_of_range, text)

    for line in lines:
        source = " ".join(sentences[i - 1] for i in line.src if 1 <= i <= len(sentences))
        if line.is_table:
            line.rows = [[fix(c, source) for c in row] for row in line.rows or []]
            continue
        fixed = fix(line.text, source)
        if fixed != line.text:
            notes.append(f"날짜에 요일 붙임: {line.text[:25]} → {fixed[:30]}")
            line.text = fixed
    return notes


def fix_level_order(lines: list[Line]) -> list[str]:
    """한 절 안에서 □보다 앞에 나온 '-'는 □로 올린다. 정식보고서는 말머리 단계를 나온 순서로 정하므로 '-'가 먼저 나오면
    그 뒤의 □가 '-'보다 깊은 단계가 되어 머리말 체계가 통째로 뒤집힌다(2026-10-09 사용자 건5: '- … / ㅁ …' 뒤섞임).
    □ 없이 '-'만 있는 절은 그대로 둔다."""
    notes: list[str] = []
    bounds = [k for k, l in enumerate(lines) if _SECTION_MARK.match(l.m)] or [-1]
    if bounds[0] != -1 and bounds[0] > 0:
        bounds.insert(0, -1)
    for n, at in enumerate(bounds):
        end = bounds[n + 1] if n + 1 < len(bounds) else len(lines)
        body = range(at + 1, end)
        first_box = next((k for k in body if lines[k].m == "□"), None)
        if first_box is None:
            continue
        for k in body:
            if k >= first_box:
                break
            if lines[k].m == "-":
                lines[k].m = "□"
                notes.append(f"구조 보정: □보다 앞선 '-'를 □로 올림 — {lines[k].text[:20]}")
    return notes


def normalize_dates(lines: list[Line], sentences: list[str]) -> list[str]:
    """날짜 뒤 점을 뗀다: '8.22.~23. 진행' → '8.22 ~ 23 진행'(2026-10-09 사용자: 요일은 없어도 되지만 점은 안 된다).
    근거 원문에 'M월 D일'이 있는 날짜에만 적용한다(소수·버전과 구분)."""
    notes: list[str] = []

    def fix(text: str, source: str) -> str:
        def known(month: str, day: str) -> bool:
            return bool(re.search(rf"(?<!\d){int(month)}\s*월\s*{int(day)}\s*일", source))

        text = re.sub(r"(?<![\d.])(\d{1,2}\.\d{1,2})\.(?![\d])", lambda m: m.group(1) if known(*m.group(1).split(".")) else m.group(0), text)

        def span(m: re.Match) -> str:
            if not known(*m.group(1).split(".")):
                return m.group(0)
            return f"{m.group(1)}{m.group(2) or ''} ~ {m.group(3)}{m.group(4) or ''}"
        text = re.sub(r"(?<![\d.])(\d{1,2}\.\d{1,2})(\([월화수목금토일]\))?\s*~\s*(\d{1,2})\.?(\([월화수목금토일]\))?(?![\d.월일])", span, text)
        return text

    for line in lines:
        source = " ".join(sentences[i - 1] for i in line.src if 1 <= i <= len(sentences))
        if line.is_table:
            line.rows = [[fix(c, source) for c in row] for row in line.rows or []]
            continue
        fixed = fix(line.text, source)
        if fixed != line.text:
            notes.append(f"날짜 표기 정리: {line.text[:25]} → {fixed[:25]}")
            line.text = fixed
    return notes


_TABLE_CONTENT = re.compile(r"^(내용|개요|방식|요지|주요\s*내용|설명)")
_TABLE_PROS = re.compile(r"장점|효과|기대|이점")
_CONS_FAMILY = re.compile(r"단점|고려|조건|한계|제약|비용|리스크|위험|일정|시기|소요|요건|난점")


def consolidate_table_rows(lines: list[Line]) -> list[str]:
    """대안 비교 표에서 한 칸에 한 줄뿐인 '단점·비용·일정·조건…' 행이 여러 개로 쪼개지면 한 행('단점/고려 사항')으로 모은다
    (2026-10-09 사용자: 항목 이름·개수는 문서마다 달라야 하지만, 칸마다 한 줄뿐인 항목을 많이 만들어 표를 잘게 쪼개면 가독성·맥락이
    떨어진다). 내용·장점 등 다른 행은 그대로 둔다. 비용·일정처럼 이름이 단점이 아닌 행의 항목은 앞에 '비용 : '을 붙인다.
    대안 비교 표(머리가 1안·2안…)만 대상이다."""
    notes: list[str] = []
    for line in lines:
        rows = line.rows
        if not rows or len(rows) < 4 or len({len(r) for r in rows}) != 1 or len(rows[0]) < 3:
            continue
        if sum(1 for c in rows[0][1:] if _OPTION_HEAD.search(c.strip())) < 2:
            continue

        def items(cell: str) -> list[str]:
            return [i.strip() for i in cell.split("\n") if i.strip(" -")]

        family = [k for k, r in enumerate(rows) if k and _CONS_FAMILY.search(r[0]) and not _TABLE_PROS.search(r[0])]
        thin = [k for k in family if all(len(items(c)) <= 1 for c in rows[k][1:])]
        if len(family) < 2 or not thin:
            continue
        width = len(rows[0])
        named = [rows[k][0].replace("\n", " ").strip() for k in family]
        label = next((n for n in named if re.search(r"단점|고려|한계|제약", n)), None)
        merged_label = label if label and len(family) == 1 else "단점/고려 사항"
        cells = []
        for c in range(1, width):
            parts: list[str] = []
            for k in family:
                name = rows[k][0].replace("\n", " ").strip()
                plain = re.search(r"단점|고려|한계|제약|조건|리스크|위험", name)
                for n, item in enumerate(items(rows[k][c])):
                    body = re.sub(r"^-\s*", "", item)
                    if not plain and n == 0:
                        body = f"{name} : {body}"
                    parts.append(f"- {body}")
            cells.append("\n".join(parts))
        new = [r for k, r in enumerate(rows) if k not in family or k == family[0]]
        new[new.index(rows[family[0]])] = [merged_label] + cells
        line.rows = new
        notes.append(f"구조 보정: 대안 비교 표의 '{'·'.join(named)}' 행 {len(family)}개를 '{merged_label}' 한 행으로 합침"
                     f"(칸마다 한 줄뿐인 행이 있어 표가 잘게 쪼개짐)")
    return notes


def restrict_arrows(lines: list[Line], sentences: list[str], rules=None) -> list[str]:
    """"→"는 꼭 필요할 때만(2026-10-09 사용자 건3·4: 인과·진행이 아닌 설명에 화살표를 썼다). 근거 원문에 원인·결과를 잇는 말
    (rules/drafting.yaml::arrow_cues)이 없으면 "→"를 하위 설명 "∙"(윗줄이 -·∙·→일 때) 또는 "-"로 바꾸고, 한 번호 절(또는 문서)
    안에서 "→"는 첫 하나만 남긴다."""
    cues = (rules or _load_rules()).arrow_cues
    notes: list[str] = []
    kept_in_section = False
    for k, line in enumerate(lines):
        if _SECTION_MARK.match(line.m):
            kept_in_section = False
            continue
        if line.m != "→":
            continue
        source = " ".join(sentences[i - 1] for i in line.src if 1 <= i <= len(sentences))
        causal = bool(cues) and any(re.search(c, source) for c in cues)
        if causal and not kept_in_section:
            kept_in_section = True
            continue
        previous = lines[k - 1].m if k else ""
        line.m = "∙" if previous in ("-", "∙", "→") else "-"
        notes.append(f"구조 보정: 인과·진행이 아닌 '→'를 '{line.m}'로 — {line.text[:20]}")
    return notes


_ATTR_LINE = re.compile(r"^(?P<attr>[가-힣/·]{2,8}(?:\s*사항)?)\s*:\s*(?P<text>\S.*)$")
_ATTR_CONTENT = re.compile(r"^(내용|개요|방식|요지|설명|방안)$")
_ATTR_JUDGE = re.compile(r"^(장점|단점|효과|장단점|고려\s*사항|단점/고려\s*사항|한계|제약|비용|일정|조건|리스크|위험|특징)$")
SUMMARY_LIMIT = 34       # 안 이름 뒤에 한 줄로 붙일 요약의 길이(공백 뺀 글자 수)


def compact_ordinals(lines: list[Line]) -> list[str]:
    """①②③ 대안 줄을 간결하게 한다(2026-10-09 사용자 건5: 안 이름과 같은 '내용' 줄, '장점/단점' 소제목이 붙어 장황했다).
    ① 안 이름을 되풀이하는 '내용 : …' 줄은 뺀다. ② 남은 항목을 쉼표로 이어 짧으면(공백 빼고 SUMMARY_LIMIT자 이하)
    '① 안 이름 : 요약' 한 줄로, 길면 항목 줄을 그대로 둔다('장점 : …' 같은 이름은 유지). 새 말을 만들지 않고 있는 조각만 이어 붙인다."""
    notes: list[str] = []
    i = 0
    while i < len(lines):
        head = lines[i]
        if head.is_table or not _ORDINAL.match(head.m):
            i += 1
            continue
        j = i + 1
        while j < len(lines) and lines[j].m in ("-", "∙") and not lines[j].is_table:
            j += 1
        children = lines[i + 1:j]
        if not children or " : " in head.text:
            i = j
            continue
        title = _stems(head.text)
        kept: list[tuple[str | None, str, Line]] = []
        for child in children:
            found = _ATTR_LINE.match(child.text)
            attr, body = (found.group("attr").strip(), found.group("text").strip()) if found and (
                _ATTR_CONTENT.match(found.group("attr").strip()) or _ATTR_JUDGE.match(found.group("attr").strip())) else (None, child.text)
            words = _stems(body)
            echoes = attr is not None and _ATTR_CONTENT.match(attr) and (
                body.replace(" ", "") in head.text.replace(" ", "") or head.text.replace(" ", "") in body.replace(" ", "")
                or (len(words) >= 2 and len(words & title) / len(words) >= 0.6))
            if echoes:
                head.src = sorted(set(head.src) | set(child.src))
                continue
            kept.append((attr, body, child))
        removed = len(children) - len(kept)
        pieces = [body for attr, body, _ in kept]
        summary = ", ".join(pieces)
        if kept and len(summary.replace(" ", "")) <= SUMMARY_LIMIT:
            head.text = f"{head.text} : {summary}"
            head.src = sorted(set(head.src) | {n for _, _, c in kept for n in c.src})
            lines[i + 1:j] = []
            notes.append(f"구조 보정: ①②③ 안 '{head.text[:20]}'을 한 줄로 요약(항목 {len(children)}개 → 0개)")
            j = i + 1
        else:
            lines[i + 1:j] = [c for _, _, c in kept]
            j = i + 1 + len(kept)
            if removed:
                notes.append(f"구조 보정: ①②③ 안 '{head.text[:20]}' 아래 안 이름을 되풀이한 '내용' 줄 {removed}개를 뺌")
        i = j
    return notes
