"""선택적 LLM 문구 다듬기 (`--polish llm`, 웹 화면의 "LLM으로 맞춤법·표현·어조 다듬기").

역할 분담(2026-09-29 사용자): 문장 끝을 개조식·명사형으로 바꾸고 긴 문장을 나누는 일은 파이썬 규칙이
한다. LLM은 그 위에서 **맞춤법·띄어쓰기, 정식 보고서 어조, 모호한 표현**만 고친다 — 문장 끝 형태는
건드리지 않게 해서(규칙이 명사로 줄여 둔 문장에 LLM이 "~함"을 다시 붙이던 문제 방지) 규칙을 끈
Confluence 문서에도 켤 수 있다. 제목(제목에서 접힌 항목)은 보내지 않는다.
기본값은 규칙 기반이며, 키/엔드포인트가 없거나 호출에 실패하면 조용히 규칙 결과로 돌아간다.

백엔드는 두 가지:
- Anthropic API (기본) — `ANTHROPIC_API_KEY`
- OpenAI 호환 온프렘 엔드포인트(vLLM/Ollama/TGI 등, Qwen 계열 포함) —
  `DOC2REPORT_LLM_BASE_URL`을 설정하면 이쪽을 쓴다. 이때 `DOC2REPORT_MODEL`(모델명)은 필수,
  `DOC2REPORT_LLM_API_KEY`는 서버가 요구할 때만.

보내지 않는 것: 표 안 내용, 코드 블록, 숫자만 있는 문단.
바꾸지 않는 것: 사실·수치·고유명사 (프롬프트로 고정하고, 길이가 크게 달라지면 원문 유지).
"""

from __future__ import annotations

import os
import re

import httpx

from ..ir import Block, Callout, Document, ListItem, Paragraph, Run, Table, plain
from ..profile import Profile
from .stylize_ko import Change

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"
_SYSTEM = (
    "너는 한국 회사의 보고서 교열 담당자다. 주어진 문장을 정식 보고서에 맞게 다듬어라.\n"
    "할 일:\n"
    "1. 맞춤법·띄어쓰기·오탈자를 바로잡는다.\n"
    "2. 구어체·군더더기·비격식 표현을 정식 보고서 어조로 고친다.\n"
    "3. 뜻이 모호한 표현('좀', '많이', '빠르게', '어느 정도', '등등')은 문장 안의 정보만으로 더 분명하게 "
    "고친다. 문장에 없는 수치·사실을 새로 만들지 않는다 — 분명하게 할 정보가 없으면 그대로 둔다.\n"
    "지킬 것:\n"
    "4. 사실·수치·날짜·고유명사·약어는 절대 바꾸지 않는다. 내용을 추가·추측·요약하지 않는다.\n"
    "5. 문장 끝 형태는 원문 그대로 둔다. 명사로 끝난 문장('인덱스 재설계')에 '~함/~임'을 붙이지 않고, "
    "'~함/~음'으로 끝난 문장은 그대로, '~습니다'로 끝난 문장도 그대로 둔다.\n"
    "6. 이미 바른 문장은 그대로 돌려준다.\n"
    "입력은 한 줄에 하나의 문장이며, 같은 개수의 줄로만 답한다. 설명은 쓰지 않는다."
)
_SHORTEN_SYSTEM = (
    "너는 한국 회사의 보고서 교열 담당자다. 주어진 문장을 지정한 글자 수 이내로 줄여라.\n"
    "지킬 것: 사실·수치·날짜·고유명사·약어는 바꾸지 않는다. 문장 끝 형태(명사형·~함·~음 등)는 원문 그대로 둔다. "
    "의미가 같은 중복·군더더기·수식어를 빼거나 더 짧은 말로 바꾼다. 없는 내용을 만들지 않는다.\n"
    "입력은 '최대 N자: 문장' 한 줄이다. 줄인 문장 한 줄만 답한다. 설명은 쓰지 않는다."
)
_MAX_DRIFT = 1.6  # 결과가 원문보다 이 배 이상 길어지면 무언가 잘못된 것으로 본다
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)


def polish_document(doc: Document, profile: Profile) -> tuple[Document, list[Change]]:
    texts: list[str] = []
    targets: list[Paragraph | ListItem] = []
    _collect(doc.blocks, texts, targets)
    if not texts:
        return doc, []

    try:
        polished = _ask_llm(texts)
    except Exception as exc:  # 키 없음·네트워크·응답 형식 오류
        return doc, [Change("(LLM)", f"규칙 기반 결과 유지 — {exc}", "LLM 건너뜀")]

    changes: list[Change] = []
    for block, before, after in zip(targets, texts, polished):
        after = after.strip()
        if not after or after == before:
            continue
        if len(after) > len(before) * _MAX_DRIFT:
            changes.append(Change(before, after, "LLM 결과 폐기(길이 이상)"))
            continue
        template = block.runs[0] if block.runs else Run("")
        block.runs = [template.copy_with(after)]
        changes.append(Change(before, after, "LLM"))
    return doc, changes


def llm_status() -> dict:
    """어떤 LLM으로 다듬을지 (웹 화면 표시용 — 키 값은 내보내지 않는다)."""
    base_url = os.environ.get("DOC2REPORT_LLM_BASE_URL")
    if base_url:
        return {"configured": bool(os.environ.get("DOC2REPORT_MODEL")), "backend": "온프렘(OpenAI 호환)",
                "model": os.environ.get("DOC2REPORT_MODEL", ""), "endpoint": base_url}
    if os.environ.get("ANTHROPIC_API_KEY"):
        return {"configured": True, "backend": "Anthropic API",
                "model": os.environ.get("DOC2REPORT_MODEL", DEFAULT_ANTHROPIC_MODEL), "endpoint": ""}
    return {"configured": False, "backend": "", "model": "", "endpoint": ""}


def llm_try(sample: str) -> str:
    """연결 확인용 — 문장 하나를 실제로 다듬어 돌려준다(실패하면 예외)."""
    return _ask_llm([sample])[0]


def _collect(blocks: list[Block], texts: list[str], targets: list) -> None:
    for block in blocks:
        if isinstance(block, ListItem) and block.from_heading:
            continue  # 제목은 어조를 바꿀 대상이 아니다
        if isinstance(block, (Paragraph, ListItem)):
            text = plain(block.runs).strip()
            if "\n" in text:
                continue  # 글쓴이가 엔터로 나눈 줄(정식보고서 줄 맞춤) — 한 줄씩 답하는 형식에 안 맞고 줄 위치를 지켜야 한다
            if text and any(ch.isalpha() for ch in text):
                texts.append(text)
                targets.append(block)
        elif isinstance(block, Callout):
            _collect(block.blocks, texts, targets)
        elif isinstance(block, Table):
            continue  # 표는 보내지 않는다


def shorten_sentence(text: str, max_chars: int) -> str | None:
    """문장을 max_chars자 이내로 줄여 돌려준다(줄 맞춤에서 두세 글자가 넘치는 문장용). 실패하면 None."""
    try:
        lines = _ask_llm([f"최대 {max_chars}자: {text}"], system=_SHORTEN_SYSTEM)
    except Exception:
        return None
    return lines[0].strip() if lines and lines[0].strip() else None


def _ask_llm(texts: list[str], system: str = _SYSTEM) -> list[str]:
    base_url = os.environ.get("DOC2REPORT_LLM_BASE_URL")
    if base_url:
        return _ask_openai_compatible(texts, base_url, system)
    return _ask_anthropic(texts, system)


def _ask_openai_compatible(texts: list[str], base_url: str, system: str = _SYSTEM) -> list[str]:
    """vLLM/Ollama/TGI 등 OpenAI `/chat/completions` 호환 온프렘 엔드포인트용.

    사내 Qwen 서빙처럼 인터넷이 닫힌 환경을 겨냥한 경로라 anthropic SDK에
    기대지 않고 httpx(코어 의존성)로 직접 호출한다.
    """
    model = os.environ.get("DOC2REPORT_MODEL")
    if not model:
        raise RuntimeError("DOC2REPORT_LLM_BASE_URL 사용 시 DOC2REPORT_MODEL 이 필수입니다")
    api_key = os.environ.get("DOC2REPORT_LLM_API_KEY")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    # Qwen3 계열은 기본이 추론(thinking) 모드라 같은 답에 10배 가까이 걸린다(2026-10-02 실측: 1,500자→300자 10.4초 vs 끄면 1.2초).
    # 교열·줄임은 닫힌 짧은 작업이라 끈다. 켜려면 DOC2REPORT_LLM_THINKING=1.
    extra = {} if os.environ.get("DOC2REPORT_LLM_THINKING") == "1" else {"chat_template_kwargs": {"enable_thinking": False}}

    out: list[str] = []
    with httpx.Client(timeout=120.0) as client:
        for chunk in _chunks(texts, 40):
            response = client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json={
                    "model": model,
                    "temperature": 0,
                    "seed": _seed(),
                    **extra,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": "\n".join(chunk)},
                    ],
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            # 추론(thinking) 모드 모델은 최종 답 앞에 <think>...</think>를 끼워 보낸다.
            content = _THINK_BLOCK.sub("", content)
            lines = content.strip().splitlines()
            if len(lines) != len(chunk):
                raise RuntimeError(f"응답 줄 수가 맞지 않음 ({len(lines)} ≠ {len(chunk)})")
            out.extend(lines)
    return out


def _ask_anthropic(texts: list[str], system: str = _SYSTEM) -> list[str]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY 가 없습니다")
    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise RuntimeError("anthropic 패키지가 없습니다 (uv pip install anthropic)") from exc

    client = Anthropic()
    out: list[str] = []
    for chunk in _chunks(texts, 40):
        message = client.messages.create(
            model=os.environ.get("DOC2REPORT_MODEL", DEFAULT_ANTHROPIC_MODEL),
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": "\n".join(chunk)}],
        )
        lines = message.content[0].text.strip().splitlines()
        if len(lines) != len(chunk):
            raise RuntimeError(f"응답 줄 수가 맞지 않음 ({len(lines)} ≠ {len(chunk)})")
        out.extend(lines)
    return out


LAST_CALL: dict = {}
# 마지막 ask_chat 호출의 진단 정보(끝난 이유·글자 수) — 형식 오류가 날 때 --report에 남긴다(2026-10-05 실측: 첫 응답이
# "JSON을 찾지 못함"으로 5건 중 4건 실패, 원인 미확정).


_JSON_MODE_REJECTED = False   # 서버가 response_format을 거부하면 이후 호출은 묻지 않는다


def ask_json(system: str, user: str) -> str:
    """JSON 답을 기대하는 호출 — 온프렘 서버에 JSON 모드를 요청한다(지원 안 하면 일반 호출)."""
    return ask_chat(system, user, json_mode=True)


def ask_chat(system: str, user: str, *, max_tokens: int = 4096, thinking: bool = False,
             json_mode: bool = False) -> str:
    """한 번의 질문 → 한 덩어리 답(여러 줄 JSON 등). 줄 수를 맞추는 `_ask_llm`과 달리 형식은 호출자가 검증한다.

    온프렘(OpenAI 호환)이면 그쪽, 아니면 Anthropic. thinking=True면 추론 모드를 켠다(기본은 끔 — 같은 답이 약 9배 빠르다)."""
    base_url = os.environ.get("DOC2REPORT_LLM_BASE_URL")
    if base_url:
        model = os.environ.get("DOC2REPORT_MODEL")
        if not model:
            raise RuntimeError("DOC2REPORT_LLM_BASE_URL 사용 시 DOC2REPORT_MODEL 이 필수입니다")
        api_key = os.environ.get("DOC2REPORT_LLM_API_KEY")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        body = {"model": model, "temperature": 0, "seed": _seed(), "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if not thinking:
            body["chat_template_kwargs"] = {"enable_thinking": False}
        global _JSON_MODE_REJECTED
        if json_mode and not _JSON_MODE_REJECTED:
            # 2026-10-07 실측: 긴 지시문에서 LLM이 JSON 대신 보고서 글을 써 형식 오류가 3회 연속 났다 — 서버가 JSON만 내게 강제
            body["response_format"] = {"type": "json_object"}
        with httpx.Client(timeout=600.0) as client:
            url = f"{base_url.rstrip('/')}/chat/completions"
            response = client.post(url, headers=headers, json=body)
            if response.status_code in (400, 422) and "response_format" in body:
                _JSON_MODE_REJECTED = True
                body.pop("response_format")
                response = client.post(url, headers=headers, json=body)
            response.raise_for_status()
            choice = response.json()["choices"][0]
            message = choice.get("message") or {}
            content = _THINK_BLOCK.sub("", message.get("content") or "").strip()
            reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
            LAST_CALL.clear()
            LAST_CALL.update(finish_reason=choice.get("finish_reason"), content_chars=len(content),
                             reasoning_chars=len(reasoning))
            if "{" not in content and "{" in reasoning:
                # 추론을 껐는데도 서버가 답을 추론 칸에 넣는 경우 — 거기 든 JSON을 쓴다(검증은 호출자가 한다)
                LAST_CALL["used_reasoning"] = True
                return reasoning.strip()
            return content
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("LLM 설정이 없습니다 (DOC2REPORT_LLM_BASE_URL 또는 ANTHROPIC_API_KEY)")
    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise RuntimeError("anthropic 패키지가 없습니다 (uv pip install anthropic)") from exc
    message = Anthropic().messages.create(
        model=os.environ.get("DOC2REPORT_MODEL", DEFAULT_ANTHROPIC_MODEL), max_tokens=max_tokens,
        system=system, messages=[{"role": "user", "content": user}])
    return message.content[0].text.strip()


def _chunks(items: list[str], size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _seed() -> int:
    """같은 입력이 실행마다 다르게 나오는 것을 줄이려고 고정 시드를 보낸다(2026-10-09 사용자: 변경이 없어도 결과가 달라짐).
    온도 0만으로는 서버의 배치·병렬 처리 때문에 같아지지 않을 수 있다(추정). 서버가 seed를 무시하면 효과가 없다.
    DOC2REPORT_LLM_SEED로 바꿀 수 있다."""
    import os

    try:
        return int(os.environ.get("DOC2REPORT_LLM_SEED", "20261009"))
    except ValueError:
        return 20261009
