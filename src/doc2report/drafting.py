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
    structure: Structure
    notes: list[str]               # --report에 남길 판단·실패 사유
    used_llm: bool


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


def draft(text: str, ask: Ask | None = None) -> DraftResult:
    """줄글 → 구조. ask(system, user)가 없으면 설정된 LLM을 쓴다. LLM이 없거나 실패하면 기본 구조."""
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
    return DraftResult(render(structure, sentences), structure, notes, used)
