"""구어체·서술체 → 보고서(개조식) 문체: 점검(lint)과 규칙 교정(fix).

LLM이 다시 쓴 줄이 아직 구어체인지 규칙으로 점검하고(강한 점검은 다시 쓰게 하는 사유), 걸린 줄은 **사실을 건드리지 않는**
규칙(군말 삭제·표기 정리·문장 끝 명사화)으로 고친다. 같은 규칙이 LLM이 없거나 사실 검증에 실패했을 때의 대체 문장
(원문 문장을 규칙만으로 개조식으로)도 만든다. 규칙 값은 rules/report_style.yaml, 사실 검증은 transform/factcheck.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

RULES = Path(__file__).resolve().parents[3] / "rules" / "report_style.yaml"


@dataclass
class Issue:
    kind: str          # polite | plain | speaker | period | long | connectives | adverb | filler
    hard: bool         # 강한 점검 — 다시 쓰게 하는 사유
    detail: str = ""

    def __str__(self) -> str:
        return f"{self.kind}({self.detail})" if self.detail else self.kind


@dataclass
class StyleRules:
    limits: dict = field(default_factory=dict)
    polite_endings: list[str] = field(default_factory=list)
    plain_ending: str = ""
    speaker: list[str] = field(default_factory=list)
    leading_fillers: list[str] = field(default_factory=list)
    colloquial_adverbs: list[str] = field(default_factory=list)
    connectives: list[str] = field(default_factory=list)
    notation: list[list[str]] = field(default_factory=list)
    strip_trailing: list[str] = field(default_factory=list)
    irregular_endings: list[list[str]] = field(default_factory=list)
    spaced_labels: list[str] = field(default_factory=list)
    examples: list[dict] = field(default_factory=list)


@lru_cache(maxsize=4)
def load_rules(path: str | None = None) -> StyleRules:
    data = yaml.safe_load(Path(path or RULES).read_text(encoding="utf-8")) or {}
    return StyleRules(**{k: v for k, v in data.items() if k in StyleRules.__dataclass_fields__})


def _body(text: str) -> str:
    """말머리·항목명을 뺀 본문(점검 대상)."""
    return re.sub(r"^\s*(?:□|-|∙|→|※|\*|[①-⑳]|\d+\.)\s*", "", text.strip())


def _width(text: str) -> int:
    return len(re.sub(r"\s", "", text))


def lint(text: str, rules: StyleRules | None = None) -> list[Issue]:
    """줄 하나의 구어체·서술체 점검. 표 칸 안 줄도 줄마다 넘긴다."""
    rules = rules or load_rules()
    body = _body(text)
    issues: list[Issue] = []
    tail = re.sub(r"[\s.!?。]+$", "", body)
    if any(tail.endswith(e) for e in rules.polite_endings):
        issues.append(Issue("polite", True, tail[-4:]))
    elif rules.plain_ending and re.search(rules.plain_ending + r"$", tail):
        issues.append(Issue("plain", True, tail[-4:]))
    for word in rules.speaker:
        if word in body:
            issues.append(Issue("speaker", True, word))
            break
    if re.search(r"[.!?。]\s*$", body):
        issues.append(Issue("period", True))
    if any(re.match(rf"{re.escape(f)}[\s,]", body) for f in rules.leading_fillers):
        issues.append(Issue("filler", False, body.split()[0]))
    limit = int(rules.limits.get("line_chars", 36))
    if _width(body) > limit:
        issues.append(Issue("long", False, f"{_width(body)}자"))
    hits = [c for c in rules.connectives if c in body]
    if len(hits) > int(rules.limits.get("connectives_max", 2)):
        issues.append(Issue("connectives", False, ",".join(hits[:4])))
    adverbs = [a for a in rules.colloquial_adverbs if re.search(rf"(?:^|\s){a}\s", body)]
    if adverbs:
        issues.append(Issue("adverb", False, ",".join(adverbs)))
    return issues


def hard_issues(text: str, rules: StyleRules | None = None) -> list[Issue]:
    return [i for i in lint(text, rules) if i.hard]


def _gaechosik():
    from .stylize_ko import Gaechosik

    return Gaechosik(noun_ending=True)


def fix(text: str, rules: StyleRules | None = None) -> str:
    """사실을 바꾸지 않는 규칙 교정: 군말 삭제 → 표기 정리 → 문장 끝 명사화 → 마침표 삭제.
    말머리·항목명("기 간 : …")은 그대로 두고 본문만 고친다."""
    rules = rules or load_rules()
    match = re.match(r"^(\s*(?:□|-|∙|→|※|\*|[①-⑳]|\d+\.)\s*)(.*)$", text, re.S)
    head, body = (match.group(1), match.group(2)) if match else ("", text)
    for filler in rules.leading_fillers:
        body = re.sub(rf"^{re.escape(filler)}[\s,]+", "", body)
    for pattern, repl in rules.notation:
        body = re.sub(pattern, repl, body)
    stripped = re.sub(r"[\s.!?。]+$", "", body)
    needs_ending = (any(stripped.endswith(e) for e in rules.polite_endings)
                    or bool(rules.plain_ending and re.search(rules.plain_ending + r"$", stripped)))
    if needs_ending:
        body = _gaechosik().convert(stripped)
        body = _b_final_to_m(re.sub(r"[\s.!?。]+$", "", body))
    for pattern in rules.strip_trailing:
        body = re.sub(pattern, "", body)
    for wrong, right in rules.irregular_endings:
        if body.endswith(wrong):
            body = body[: -len(wrong)] + right
    return head + body.strip()


def _b_final_to_m(text: str) -> str:
    """"~ㅂ니다"가 규칙표에 없어 남았으면(크+ㅂ니다 = 큽니다) ㅂ받침을 ㅁ으로 바꿔 명사형으로(큽니다 → 큼)."""
    if not text.endswith("니다") or len(text) < 3:
        return text
    syllable = text[-3]
    code = ord(syllable) - 0xAC00
    if 0 <= code < 11172 and code % 28 == 17:      # 종성 ㅂ
        return text[:-3] + chr(0xAC00 + code - 1) + ""     # ㅂ(17) → ㅁ(16)
    return text


def examples_text(rules: StyleRules | None = None, exclude_docs: set[int] | None = None,
                  limit: int = 60) -> str:
    """LLM 지시문에 넣을 변환 예시(문장 → 보고서 줄). exclude_docs의 예시는 뺀다(채점 때 베낀 것인지 가리려고)."""
    rules = rules or load_rules()
    exclude = exclude_docs or set()
    picked, seen = [], set()
    for example in rules.examples:
        if example.get("doc") in exclude:
            continue
        picked.append(example)
        seen.add(example.get("kind"))
    picked = picked[:limit]
    out = []
    for example in picked:
        sources = " ".join(example["src"])
        lines = " / ".join(example["out"])
        out.append(f"- [{example['kind']}]\n  원문: {sources}\n  보고서: {lines}")
    return "\n".join(out)
