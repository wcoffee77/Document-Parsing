"""웹 화면의 변환 옵션 ↔ 프로파일.

화면의 체크박스 하나하나는 **프로파일 값 하나**다(text.*, tables.*). 그래서 옵션을 늘릴 때 변환
코드에 분기를 추가하지 않고 여기 목록에 한 줄만 넣으면 된다 — 값은 프로파일을 model_copy로
덮어쓸 뿐이다(프로파일 파일은 그대로). 체크박스 이름·설명도 여기가 원본이고 화면은 받아 그린다.

"자동 판단"은 읽어 들인 문서를 보고 두 가지를 따로 정한다.
- 정리 정도: 제목·말머리가 있는 문단 비율 → 원문 유지(confluence 규칙) / 새로 정리(default 규칙:
  말머리 생성 + 문장 다듬기, LLM은 허용했을 때만). Confluence 페이지는 항상 원문 유지(사용자 규칙).
- 분량: 글자 수·표 개수·입력 개수 → 내용 많은 문서 서식(confluence 글자 크기) / 사내 기본 서식.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as _date

from ..ir import Document, Heading, ListItem, Paragraph, Table, is_blank, iter_tables, plain
from ..profile import PROFILE_DIR, Profile, load_profile
from ..transform.structure import has_leading_marker
from ..units import fmt_pt

# (키, 화면 이름, 설명)
MARKER_TOGGLES = [
    ("keep_leading_markers", "원문 말머리 그대로 쓰기",
     "원문에 이미 친 1. □ - ㆍ ① ※ 등을 바꾸지 않음"),
    ("auto_markers", "말머리 없는 문단에 말머리 만들기",
     "끄면 말머리 없는 제목·문단은 들여쓰기만 맞춤. 정리 안 된 글을 새 보고서로 만들 때 켬"),
    ("headings_as_levels", "제목을 1.→□→- 단계로 접기",
     "## / ### 제목을 별도 제목 서식 대신 보고서 단계로"),
    ("normalize_levels", "맨 바깥 단계는 들여쓰기 없이(0cm)", "문서가 작은 제목부터 시작해도 첫 문장을 0cm로"),
    ("level_bold", "1.·□ 단계 문장 전체 굵게", "끄면 원문에서 굵던 글씨와 제목만 굵게"),
]
POLISH_TOGGLES = [
    ("gaechosik", "개조식 어미로", "~합니다 → ~함"),
    ("noun_ending", "명사로 끝내기", "인덱스를 재설계하였습니다 → 인덱스 재설계"),
    ("split_long_sentences", "긴 문장 나누기", ""),
    ("merge_short_items", "짧은 항목 \"및\"으로 합치기", "같은 단계의 짧은 항목 둘씩"),
]
TABLE_TOGGLES = [
    ("table_captions", "표 위 【…】 문단을 표 제목으로", "꺾쇠·정렬 그대로, 말머리 없이"),
]
TABLE_CHOICES = {"align": [("right", "오른쪽"), ("center", "가운데"), ("left", "왼쪽")]}
FORMAT_KEYS = ("font", "size", "line_spacing", "title_size", "table_size")

_STRUCTURED_RATIO = 0.3  # 제목·말머리가 있는 문단이 이 비율 이상이면 "정리된 문서"
_HEAVY_CHARS = 3000      # 본문 글자 수가 이 이상이면 "내용 많은 문서"
_HEAVY_TABLES = 3        # 표가 이 개수 이상이어도


@dataclass
class Decision:
    profile: Profile
    polish: str
    reasons: list[str] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def profile_names() -> list[str]:
    return sorted(p.stem for p in PROFILE_DIR.glob("*.yaml"))


def profile_info(name: str) -> dict:
    """화면이 체크박스 기본값·선택지를 채우는 데 쓰는 프로파일 요약."""
    prof = load_profile(name)
    text = prof.text
    return {
        "name": name,
        "description": prof.description or name,
        "text": {key: bool(getattr(text, key)) for key, _, _ in
                 MARKER_TOGGLES + POLISH_TOGGLES + TABLE_TOGGLES},
        "polish": text.polish or "rules",
        "tables": {"allow_landscape": prof.tables.allow_landscape, "align": prof.tables.align},
        "format": {
            "font": prof.font("body").east_asia or prof.font("body").latin or "",
            "size": fmt_pt(prof.font("body").size),
            "line_spacing": str(prof.font("body").line_spacing or ""),
            "title_size": fmt_pt(prof.font("title").size) if prof.has_font("title") else "",
            "table_size": fmt_pt(prof.table_font_ladder()[0]),
        },
        "choices": {k: [str(v) for v in values] for k, values in prof.choices.model_dump().items()},
    }


def schema() -> dict:
    def rows(items):
        return [{"key": k, "label": label, "help": help_} for k, label, help_ in items]

    return {"markers": rows(MARKER_TOGGLES), "polish": rows(POLISH_TOGGLES),
            "tables": rows(TABLE_TOGGLES),
            "table_align": [{"value": v, "label": label} for v, label in TABLE_CHOICES["align"]],
            "auto": {"chars": _HEAVY_CHARS, "tables": _HEAVY_TABLES, "ratio": _STRUCTURED_RATIO,
                     "heavy_profile": "confluence"}}


def manual_profile(options: dict) -> tuple[Profile, str]:
    """직접 선택 모드: 고른 프로파일 위에 체크박스 값을 덮어쓴다."""
    name = options.get("profile") or "default"
    if name not in profile_names():
        raise ValueError(f"알 수 없는 프로파일: {name}")
    prof = load_profile(name)
    current = profile_info(name)["format"]
    fmt = {k: v for k, v in (options.get("format") or {}).items()
           if k in FORMAT_KEYS and v and str(v) != current.get(k)}  # 바꾼 값만 덮어쓴다
    if fmt:
        prof = prof.with_overrides(**fmt)
    known = {k for k, _, _ in MARKER_TOGGLES + POLISH_TOGGLES + TABLE_TOGGLES}
    text_updates = {k: bool(v) for k, v in (options.get("text") or {}).items() if k in known}
    table_opts = options.get("tables") or {}
    table_updates = {}
    if "allow_landscape" in table_opts:
        table_updates["allow_landscape"] = bool(table_opts["allow_landscape"])
    if table_opts.get("align") in dict(TABLE_CHOICES["align"]):
        table_updates["align"] = table_opts["align"]
    prof = prof.model_copy(update={"text": prof.text.model_copy(update=text_updates),
                                   "tables": prof.tables.model_copy(update=table_updates)})
    polish = options.get("polish") or prof.text.polish or "rules"
    if polish not in ("none", "rules", "llm"):
        raise ValueError(f"알 수 없는 문장 다듬기 방식: {polish}")
    return prof, polish


def auto_decide(docs: list[Document], kinds: list[str], *, allow_llm: bool,
                llm_ready: bool) -> Decision:
    base = load_profile("default")
    blocks = [b for d in docs for b in d.blocks
              if isinstance(b, (Heading, Paragraph, ListItem)) and not is_blank(plain(b.runs))]
    marked = sum(1 for b in blocks if not isinstance(b, Paragraph)
                 or has_leading_marker(b.runs, base.text.leading_markers))
    ratio = marked / len(blocks) if blocks else 1.0
    chars = sum(len(plain(b.runs)) for b in blocks)
    tables = sum(1 for d in docs for _ in iter_tables(d))

    reasons: list[str] = []
    if "confluence" in kinds:
        structured = True
        reasons.append("Confluence 페이지가 있어 원문 문장·말머리를 그대로 둠(문장 다듬기 안 함)")
    else:
        structured = ratio >= _STRUCTURED_RATIO
        if structured:
            reasons.append(f"제목·말머리가 있는 문단 {ratio:.0%} → 정리된 문서로 보고 원문 문장·말머리 유지")
        else:
            reasons.append(f"제목·말머리가 있는 문단 {ratio:.0%} → 정리 안 된 글로 보고 "
                           "말머리를 만들고 문장을 개조식으로 다듬음")

    heavy = chars >= _HEAVY_CHARS or tables >= _HEAVY_TABLES or len(docs) >= 2
    fonts = load_profile("confluence" if heavy else "default")
    size_text = (f"본문 {fmt_pt(fonts.font('body').size)}·제목 {fmt_pt(fonts.font('title').size)}·"
                 f"표 {fmt_pt(fonts.table_font_ladder()[0])}부터")
    volume = f"본문 {chars:,}자·표 {tables}개·입력 {len(docs)}개"
    reasons.append(f"{volume} → " + ("내용 많은 문서 서식" if heavy else "사내 기본 서식")
                   + f"({size_text})")

    text_profile = load_profile("confluence" if structured else "default")
    prof = fonts.model_copy(update={"text": text_profile.text})
    if structured:
        polish = "none"
    elif allow_llm and llm_ready:
        polish = "llm"
        reasons.append("LLM 사용을 허용해 규칙 적용 뒤 LLM으로 한 번 더 다듬음")
    else:
        polish = "rules"
        if allow_llm:
            reasons.append("LLM이 설정되지 않아 파이썬 규칙으로만 다듬음")
    return Decision(profile=prof, polish=polish, reasons=reasons,
                    summary={"structured": structured, "heavy": heavy, "ratio": round(ratio, 2),
                             "chars": chars, "tables": tables, "polish": polish})


def date_text(value: str | None, profile: Profile) -> str | None:
    """화면의 날짜 선택 → 제목 아래 날짜 줄. "" = 넣지 않음, "today", "2026-10-01"."""
    value = (value or "").strip()
    if not value:
        return None
    if value in ("today", "오늘"):
        return "today"
    try:
        chosen = _date.fromisoformat(value)
    except ValueError:
        return value  # 사용자가 직접 쓴 표기 그대로
    fmt = profile.text.date_format or "{y}. {m}. {d}"
    return fmt.format(y=chosen.year, m=chosen.month, d=chosen.day)
