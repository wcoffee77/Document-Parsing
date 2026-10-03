"""다듬은 문장이 원문의 사실을 바꾸지 않았는지 검사한다 (줄글 → 정식보고서, B안).

LLM이 다시 쓴 줄 하나와 그 줄의 근거 원문을 받아, 원문에 없는 것이 들어갔으면 문제를 돌려준다.
- 숫자: 줄의 숫자는 모두 원문에 있어야 한다. 퍼센트는 퍼센트끼리, 금액은 원 단위 값으로, 날짜는 (월, 일)로 맞춰
  표기 차이(10월 15일 ↔ 10.15, 300만 원 ↔ 300만원, 1억 2천만 원 ↔ 1억 2천만원)는 허용한다. 우리말 수("두 곳",
  "둘째 주")와 기간("8월 22일부터 이틀간" → 23일)도 원문에 있는 수로 본다.
- 요일: "9.5(토)"의 요일은 달력으로 확인한다.
- 영문 낱말·한자: 원문에 없고 허용 목록(rules/drafting.yaml)에도 없으면 막는다.
- 방향(늘다↔줄다, 가능↔어려움)과 확정 여부("검토 중" → "확정")가 원문과 어긋나면 막는다.
규칙 값은 rules/drafting.yaml에 있고 이 파일은 적용기다. 세기·대조는 파이썬이, 문장 쓰기는 LLM이 한다.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

RULES = Path(__file__).resolve().parents[3] / "rules" / "drafting.yaml"

_NUM = r"\d+(?:\.\d+)?"
_UNIT_VALUE = {"조": 10**12, "억": 10**8, "천만": 10**7, "백만": 10**6, "만": 10**4, "천": 10**3}
_MONEY = re.compile(rf"((?:{_NUM}\s*(?:조|억|천만|백만|만|천)\s*)+(?:{_NUM}\s*)?|{_NUM}\s*)원")
_MONEY_PART = re.compile(rf"({_NUM})\s*(조|억|천만|백만|만|천)?")
_PERCENT = re.compile(rf"({_NUM})\s*%")
_KO_DATE = re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일")
_DOT_DATE = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})(?![\d%])")
_DURATION = re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일\s*부터\s*(\S+?)간")
_WEEKDAY = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})\s*\(([월화수목금토일])\)")
_RANGE_WEEKDAY = re.compile(r"~\s*(\d{1,2})\s*\(([월화수목금토일])\)")
_ASCII_WORD = re.compile(r"[A-Za-z][A-Za-z&]*")
_HANJA = re.compile(r"[一-鿿]")
_EXEMPT = re.compile(r"\(?\d+\s*안\)?")       # "(1안)" "2안"은 대안 번호 — 원문의 숫자가 아니다
_WEEKDAYS = "월화수목금토일"


@dataclass
class Rules:
    allowed_hanja: str = ""
    terms: dict[str, str] = field(default_factory=dict)
    number_words: dict[str, int] = field(default_factory=dict)
    duration_days: dict[str, int] = field(default_factory=dict)
    polarity: list[dict[str, list[str]]] = field(default_factory=list)
    done_words: list[str] = field(default_factory=list)
    done_source: list[str] = field(default_factory=list)
    done_pending: list[str] = field(default_factory=list)


@lru_cache(maxsize=4)
def load_rules(path: str | None = None) -> Rules:
    data = yaml.safe_load(Path(path or RULES).read_text(encoding="utf-8")) or {}
    return Rules(**{k: v for k, v in data.items() if k in Rules.__dataclass_fields__})


def _clean(text: str) -> str:
    return re.sub(r"(?<=\d),(?=\d{3})", "", text)


def _money_value(phrase: str) -> float | None:
    total = 0.0
    found = False
    for number, unit in _MONEY_PART.findall(phrase):
        found = True
        total += float(number) * (_UNIT_VALUE[unit] if unit else 1)
    return total if found else None


@dataclass
class Facts:
    raw: set[str] = field(default_factory=set)
    percents: set[float] = field(default_factory=set)
    money: set[float] = field(default_factory=set)
    dates: set[tuple[int, int]] = field(default_factory=set)
    text: str = ""

    def has_number(self, value: str) -> bool:
        return _norm(value) in self.raw


def _norm(value: str) -> str:
    return str(float(value)).rstrip("0").rstrip(".") if "." in value else str(int(value))


def facts(text: str, rules: Rules) -> Facts:
    text = _clean(text)
    out = Facts(text=text)
    out.raw = {_norm(m) for m in re.findall(_NUM, text)}
    out.percents = {float(m) for m in _PERCENT.findall(text)}
    out.money = {v for m in _MONEY.finditer(text) if (v := _money_value(m.group(1))) is not None}
    out.dates = {(int(m), int(d)) for m, d in _KO_DATE.findall(text)}
    out.dates |= {(int(m), int(d)) for m, d in _DOT_DATE.findall(text)}
    for word, number in rules.number_words.items():
        if re.search(rf"(?:^|[\s(]){re.escape(word)}", text):
            out.raw.add(str(number))
    for month, day, word in _DURATION.findall(text):
        days = rules.duration_days.get(word)
        if days:
            for extra in range(1, days):
                out.dates.add((int(month), int(day) + extra))
                out.raw.add(str(int(day) + extra))
    for month, day in list(out.dates):
        out.raw |= {str(month), str(day)}
    return out


def check(line: str, source: str, rules: Rules | None = None, year: int | None = None) -> list[str]:
    """다듬은 줄 하나를 근거 원문과 대조해 문제 목록을 돌려준다(빈 목록이면 통과)."""
    rules = rules or load_rules()
    src = facts(source, rules)
    problems: list[str] = []
    text = _clean(line)
    problems += _check_numbers(text, src)
    if year:
        problems += _check_weekdays(text, year)
    problems += _check_words(text, src.text, rules)
    problems += _check_polarity(text, src.text, rules)
    return problems


def _check_numbers(text: str, src: Facts) -> list[str]:
    problems: list[str] = []
    covered: list[tuple[int, int]] = []

    def claim(match: re.Match) -> None:
        covered.append(match.span())

    for m in _EXEMPT.finditer(text):
        claim(m)
    for m in _PERCENT.finditer(text):
        claim(m)
        if float(m.group(1)) not in src.percents:
            problems.append(f"원문에 없는 비율 {m.group(0)}")
    for m in _MONEY.finditer(text):
        if any(a <= m.start() < b for a, b in covered):
            continue
        claim(m)
        value = _money_value(m.group(1))
        if value is not None and value not in src.money:
            problems.append(f"원문에 없는 금액 {m.group(0).strip()}")
    for m in _DOT_DATE.finditer(text):
        if any(a <= m.start() < b for a, b in covered):
            continue
        claim(m)
        month, day = int(m.group(1)), int(m.group(2))
        if (month, day) not in src.dates and not (src.has_number(m.group(0))):
            problems.append(f"원문에 없는 날짜 {m.group(0)}")
    for m in _KO_DATE.finditer(text):
        if any(a <= m.start() < b for a, b in covered):
            continue
        claim(m)
        if (int(m.group(1)), int(m.group(2))) not in src.dates:
            problems.append(f"원문에 없는 날짜 {m.group(0)}")
    for m in re.finditer(_NUM, text):
        if any(a <= m.start() < b for a, b in covered):
            continue
        if not src.has_number(m.group(0)):
            problems.append(f"원문에 없는 숫자 {m.group(0)}")
    return problems


def _check_weekdays(text: str, year: int) -> list[str]:
    problems: list[str] = []
    month = None
    for m in _WEEKDAY.finditer(text):
        month, day, name = int(m.group(1)), int(m.group(2)), m.group(3)
        problems += _weekday_problem(year, month, day, name, m.group(0))
    if month is not None:
        for m in _RANGE_WEEKDAY.finditer(text):
            problems += _weekday_problem(year, month, int(m.group(1)), m.group(2), m.group(0))
    return problems


def _weekday_problem(year: int, month: int, day: int, name: str, shown: str) -> list[str]:
    try:
        actual = _WEEKDAYS[_dt.date(year, month, day).weekday()]
    except ValueError:
        return [f"없는 날짜 {shown}"]
    return [] if actual == name else [f"요일이 틀림 {shown} (실제 {actual}요일)"]


def _check_words(text: str, source: str, rules: Rules) -> list[str]:
    problems: list[str] = []
    allowed_ascii = {w.lower() for w in _ASCII_WORD.findall(source)}
    for original, replacement in rules.terms.items():
        if original in source:
            allowed_ascii |= {w.lower() for w in _ASCII_WORD.findall(replacement)}
    for word in _ASCII_WORD.findall(text):
        if word.lower() not in allowed_ascii:
            problems.append(f"원문에 없는 영문 '{word}'")
    for char in set(_HANJA.findall(text)):
        if char not in rules.allowed_hanja and char not in source:
            problems.append(f"허용되지 않은 한자 '{char}'")
    return problems


def _has_any(text: str, words: list[str]) -> bool:
    return any(w in text for w in words)


def _check_polarity(text: str, source: str, rules: Rules) -> list[str]:
    problems: list[str] = []
    for pair in rules.polarity:
        up, down = pair.get("up", []), pair.get("down", [])
        for mine, other, label in ((up, down, "늘다·가능"), (down, up, "줄다·불가")):
            if _has_any(text, mine) and _has_any(source, other) and not _has_any(source, mine):
                problems.append(f"원문과 방향이 반대인 표현({label})")
    pending = "|".join(re.escape(w) for w in rules.done_pending) or "(?!)"
    settled = [w for w in rules.done_words if re.search(rf"{re.escape(w)}(?!\s*(?:{pending}))", text)]
    if settled and not _has_any(source, rules.done_source):
        problems.append("원문에 없는 확정·완료 표현")
    return problems


def missing_numbers(source: str, output: str, rules: Rules | None = None) -> list[str]:
    """원문 숫자 중 보고서에 안 나온 것(빠진 수치 — 사람이 고를 수 있게 --report에 남긴다)."""
    rules = rules or load_rules()
    src, out = facts(source, rules), facts(output, rules)
    shown = sorted({_norm(m) for m in re.findall(_NUM, _clean(source))} - out.raw, key=float)
    return shown
