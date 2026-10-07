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
    hedge_source: list[str] = field(default_factory=list)
    hedge_line: list[str] = field(default_factory=list)
    hedge_overlap: int = 2
    hedge_stopwords: list[str] = field(default_factory=list)
    hedge_predicates: dict[str, list[str]] = field(default_factory=dict)
    alternative_cues: list[str] = field(default_factory=list)
    alternative_strong_cues: list[str] = field(default_factory=list)
    parallel_cues: list[str] = field(default_factory=list)
    audit_skip_clause: list[str] = field(default_factory=list)
    progress_line: list[str] = field(default_factory=list)
    progress_source: list[str] = field(default_factory=list)
    blocked_terms: list[str] = field(default_factory=list)
    bound_source: list[str] = field(default_factory=list)
    bound_line: list[str] = field(default_factory=list)


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
    problems += _check_hedges(text, src.text, rules)
    problems += _check_bounds(text, src.text, rules)
    problems += _check_progress(text, src.text, rules)
    problems += [f"원문에 없는 말 '{t}'(다른 뜻으로 읽힘)" for t in rules.blocked_terms if t in text and t not in src.text]
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
        name = pair.get("name") or "방향"
        for mine, other in ((up, down), (down, up)):
            label = f"{name}: 원문 '{next(w for w in other if w in source) if _has_any(source, other) else ''}'"
            # 줄 안에 양쪽이 다 있으면("확보 가능하나 선정 난이도 高") 대비를 그대로 옮긴 것이라 막지 않는다
            # (2026-10-05 실측 정답 5의 오탐)
            if (_has_any(text, mine) and not _has_any(text, other)
                    and _has_any(source, other) and not _has_any(source, mine)):
                problems.append(f"원문과 방향이 반대인 표현({label})")
    pending = "|".join(re.escape(w) for w in rules.done_pending) or "(?!)"
    settled = [w for w in rules.done_words if re.search(rf"{re.escape(w)}(?!\s*(?:{pending}))", text)]
    if settled and not _has_any(source, rules.done_source):
        problems.append("원문에 없는 확정·완료 표현")
    return problems


_CLAUSE_SPLIT = re.compile(r"[,，.]|(?<=[고며서만])\s")


def _stems(text: str, stop: list[str]) -> set[str]:
    return {w[:2] for w in re.findall(r"[가-힣]{2,}", text) if w[:2] not in stop}


def _check_hedges(text: str, source: str, rules: Rules) -> list[str]:
    """원문 절은 가능성("어려워질 수 있음")인데, 그 절을 옮긴 줄이 단정("어려움")이면 문제."""
    if not rules.hedge_source or _has_any(text, rules.hedge_line):
        return []
    mine = _stems(text, rules.hedge_stopwords)
    hedge = "|".join(re.escape(h) for h in rules.hedge_source)
    for clause in _CLAUSE_SPLIT.split(source):
        found = re.search(hedge, clause)
        if not found:
            continue
        # 가능성이 걸린 서술어("어려워질 수 있"의 어려워질)를 줄이 옮겼을 때만 본다. 같은 절의 다른 말("본업 부담")만
        # 옮긴 줄은 상관없다(2026-10-05 실측 정답 4 결과의 오탐).
        words = clause[:found.start()].split()
        if not words:
            continue
        predicate = re.sub(r"[ㄹ을를]$", "", words[-1])
        forms = next((v for k, v in rules.hedge_predicates.items() if predicate.startswith(k)), [predicate[:2]])
        shared = mine & _stems(clause, rules.hedge_stopwords)
        if any(f in text for f in forms) and len(shared) >= rules.hedge_overlap:
            return [f"원문은 가능성(~수 있음 등)인데 단정으로 씀 — '{clause.strip()[:24]}'"]
    return []


def _check_bounds(text: str, source: str, rules: Rules) -> list[str]:
    """원문에서 숫자 바로 뒤에 '이상·미만·넘게'가 있었는데 줄에서는 그 숫자에 범위 표현이 없으면 문제."""
    if not rules.bound_source:
        return []
    problems: list[str] = []
    bound_src = "|".join(re.escape(b) for b in rules.bound_source)
    bound_out = "|".join(re.escape(b) for b in rules.bound_line)
    for m in re.finditer(rf"({_NUM})\s*([가-힣]{{0,3}})\s*(?:{bound_src})", _clean(source)):
        number, unit = m.group(1), m.group(2)
        # 같은 단위가 붙은 숫자만 본다("10년차 이상"의 10과 "10명"의 10은 다른 사실)
        for hit in re.finditer(rf"(?<![\d.]){re.escape(number)}\s*{re.escape(unit)}", text):
            after = text[hit.end():hit.end() + 8]
            if not re.match(rf"\s*[가-힣]{{0,3}}\s*(?:{bound_out})", after):
                problems.append(f"원문의 범위 표현이 빠짐({m.group(0).strip()})")
                break
    return problems


def missing_numbers(source: str, output: str, rules: Rules | None = None) -> list[str]:
    """원문 숫자 중 보고서에 안 나온 것(빠진 수치 — 사람이 고를 수 있게 --report에 남긴다)."""
    rules = rules or load_rules()
    out = facts(output, rules)
    text = _clean(source)
    covered: list[tuple[int, int]] = []        # 값이 같게 옮겨진 금액·퍼센트 구간(3천만 ↔ 3,000만)
    for m in _MONEY.finditer(text):
        value = _money_value(m.group(1))
        if value is not None and value in out.money:
            covered.append(m.span())
    for m in _PERCENT.finditer(text):
        if float(m.group(1)) in out.percents:
            covered.append(m.span())
    for m in _KO_DATE.finditer(text):
        if (int(m.group(1)), int(m.group(2))) in out.dates:
            covered.append(m.span())
    missing: set[str] = set()
    for m in re.finditer(_NUM, text):
        if _norm(m.group(0)) in out.raw or any(a <= m.start() and m.end() <= b for a, b in covered):
            continue
        missing.add(_norm(m.group(0)))
    return sorted(missing, key=float)


def uncovered_by_source(sentences: list[str], lines: list[tuple[list[int], str]],
                        rules: Rules | None = None) -> dict[int, list[str]]:
    """인용한 원문 문장(번호 1부터) → 그 문장을 인용한 줄들 어디에도 없는 숫자.
    lines는 (src 번호 목록, 줄 글) 쌍. 어느 줄도 인용하지 않은 문장은 생략(dropped)이라 대상 아님."""
    rules = rules or load_rules()
    cited: dict[int, list[str]] = {}
    for src, text in lines:
        for i in src:
            cited.setdefault(i, []).append(text)
    result: dict[int, list[str]] = {}
    for i, texts in sorted(cited.items()):
        if not 1 <= i <= len(sentences):
            continue
        gone = missing_numbers(sentences[i - 1], " ".join(texts), rules)
        if gone:
            result[i] = gone
    return result


# 원문 어구를 잘라 붙인 줄임말(2026-10-07 실측: '몰아서 일하는' → '몰아일'). 이웃한 원문 두 낱말이 모두 용언 활용형(몰아-서, 일-하는)인데
# 각각의 앞부분만 잘라 붙인 말은 사전에 없는 말이다. 명사로 끝나는 낱말(선택 폭 → 선택폭)은 대상이 아니다.
_VERBAL_TAIL = ("서", "고", "며", "면", "는", "아", "어", "여", "해", "하", "한", "할", "함", "했", "던", "든", "지", "게", "기", "도록", "니", "으며", "으면")


def _verbal_cut(word: str):
    """낱말을 (앞부분, 용언 꼬리)로 자를 수 있는 모든 앞부분 — 꼬리가 용언 활용이 시작되는 글자일 때만."""
    for cut in range(1, len(word)):
        if word[cut:].startswith(_VERBAL_TAIL):
            yield word[:cut]


def coined_words(line: str, source: str) -> list[str]:
    """줄에 든, 원문 이웃 낱말 둘을 잘라 붙여 만든 줄임말(원문에 그대로는 없는 말)."""
    words = re.findall(r"[가-힣]+", source)
    flat = re.sub(r"\s", "", source)
    tokens = re.findall(r"[가-힣]+", line)
    found: list[str] = []
    for first, second in zip(words, words[1:]):
        for head in _verbal_cut(first):
            for tail in _verbal_cut(second):
                made = head + tail
                if len(made) >= 3 and made not in flat and any(made in t for t in tokens) and made not in found:
                    found.append(made)
    return found


def _check_progress(text: str, source: str, rules: Rules) -> list[str]:
    """"협의 中"처럼 '지금 하고 있다'는 표현이 줄에 있는데, 원문에는 그 일이 진행 중이라는 말이 없으면 막는다(계획·예정을 진행으로 바꾸는 왜곡)."""
    if not rules.progress_line:
        return []
    marks = "|".join(re.escape(m) for m in rules.progress_line)
    cues = rules.progress_source
    problems: list[str] = []
    for match in re.finditer(rf"([가-힣]{{2,}})\s*(?:{marks})(?=\s*(?:[)\]\-,/·]|\d|$))", text):   # '발표과제 중 우수과제'(~ 가운데)는 제외
        word = match.group(1)
        stem = word[:2]
        positions = [m.start() for m in re.finditer(re.escape(stem), source)]
        if not positions:
            continue            # 원문에 없는 낱말은 다른 점검의 몫
        shown = any(any(cue in source[pos:pos + len(word) + 12] for cue in cues) for pos in positions)
        if not shown:
            problems.append(f"'{word} 中'은 진행 중이라는 뜻인데 원문에는 진행 중이라는 말이 없음(계획·예정일 수 있음)")
    return problems
