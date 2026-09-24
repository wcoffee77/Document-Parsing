"""개조식(명사형 종결) 변환.

규칙 표는 rules/endings.yaml 에 있고 이 파일은 적용기다.
표에 없는 어미는 한글 자모를 합성해 일반 규칙으로 처리한다.
  받침 없음 → ㅁ 받침 추가   (진행하 → 진행함, 확인되 → 확인됨)
  ㄹ 받침    → ㄻ 으로       (만들 → 만듦)
  그 밖      → '음' 덧붙임   (먹 → 먹음)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

RULES_DIR = Path(__file__).resolve().parents[3] / "rules"

_HANGUL_BASE = 0xAC00
_HANGUL_LAST = 0xD7A3
_JONG_M = 16   # ㅁ
_JONG_R = 8    # ㄹ
_JONG_RM = 10  # ㄻ

# 문장 경계. 숫자 뒤의 마침표는 날짜·항목번호("2026. 9. 1.")라 자르지 않는다.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])(?<![0-9][.!?])\s+")


@dataclass
class Change:
    before: str
    after: str
    rule: str


@dataclass
class EndingRules:
    suffix_rules: list[tuple[str, str]] = field(default_factory=list)
    nominalize: list[str] = field(default_factory=list)
    keep_as_is: list[str] = field(default_factory=list)
    replacements: list[tuple[str, str]] = field(default_factory=list)
    connectives: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path | None = None) -> EndingRules:
        path = path or RULES_DIR / "endings.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(
            suffix_rules=[(a, b) for a, b in data.get("suffix_rules", [])],
            nominalize=list(data.get("nominalize", [])),
            keep_as_is=list(data.get("keep_as_is", [])),
            replacements=[(a, b) for a, b in data.get("replacements", [])],
            connectives=list(data.get("connectives", [])),
        )


class Gaechosik:
    """문장 단위 개조식 변환기."""

    def __init__(self, rules: EndingRules | None = None):
        self.rules = rules or EndingRules.load()
        self.changes: list[Change] = []

    # ── 공개 API ────────────────────────────────────────────────────────

    def convert(self, text: str) -> str:
        """문단 텍스트 전체를 개조식으로."""
        if not text.strip():
            return text
        original = text
        for before, after in self.rules.replacements:
            if before in text:
                text = text.replace(before, after)

        sentences = _SENTENCE_SPLIT.split(text)
        converted = [self.convert_sentence(s) for s in sentences]
        result = " ".join(s for s in converted if s.strip()).strip()

        if result != original.strip():
            self.changes.append(Change(original.strip(), result, "개조식"))
        return result

    def convert_sentence(self, sentence: str) -> str:
        core = sentence.rstrip()
        trailing = sentence[len(core):]
        punct = ""
        while core and core[-1] in ".!?":
            punct = core[-1] + punct
            core = core[:-1]
        core = core.rstrip()
        if not core:
            return sentence

        if any(core.endswith(word) for word in self.rules.keep_as_is):
            return sentence

        for suffix, replacement in self.rules.suffix_rules:
            if core.endswith(suffix):
                return core[: -len(suffix)] + replacement + punct + trailing

        for ending in self.rules.nominalize:
            if core.endswith(ending) and len(core) > len(ending):
                stem = core[: -len(ending)]
                return nominalize(stem) + punct + trailing

        return sentence

    def split_long(self, text: str, max_chars: int) -> list[str]:
        """긴 문장을 문장 부호와 연결어미에서 끊어 여러 항목으로."""
        parts = [s for s in _SENTENCE_SPLIT.split(text) if s.strip()]
        if max_chars <= 0:
            return parts
        out: list[str] = []
        for part in parts:
            out.extend(self._split_by_connective(part, max_chars))
        return out

    def _split_by_connective(self, sentence: str, max_chars: int) -> list[str]:
        if len(sentence) <= max_chars:
            return [sentence]
        for connective in self.rules.connectives:
            marker = connective + ", "
            index = sentence.find(marker)
            if 0 < index < len(sentence) - len(marker):
                head = sentence[: index + len(connective)]
                tail = sentence[index + len(marker) :]
                self.changes.append(Change(sentence, f"{head} / {tail}", "문장 분리"))
                return [self.convert_sentence(head + "."),
                        *self._split_by_connective(tail, max_chars)]
        return [sentence]


# ── 자모 합성 ───────────────────────────────────────────────────────────


def nominalize(stem: str) -> str:
    """어간에 명사형 어미를 붙인다."""
    stem = stem.rstrip()
    if not stem:
        return stem
    last = stem[-1]
    if not (_HANGUL_BASE <= ord(last) <= _HANGUL_LAST):
        return stem + "음"
    code = ord(last) - _HANGUL_BASE
    jong = code % 28
    if jong == 0:
        return stem[:-1] + chr(ord(last) + _JONG_M)
    if jong == _JONG_R:
        return stem[:-1] + chr(ord(last) - _JONG_R + _JONG_RM)
    return stem + "음"
