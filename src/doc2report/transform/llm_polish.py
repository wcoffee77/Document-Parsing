"""선택적 LLM 문구 다듬기 (`--polish llm`).

규칙 기반으로 처리한 뒤, 남은 어색한 문장만 LLM에게 맡긴다.
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
    "너는 한국 회사의 보고서 편집자다. 주어진 문장을 개조식 보고서 문체로 다듬어라.\n"
    "규칙:\n"
    "1. 명사형으로 끝낸다(~함, ~임, ~하였음).\n"
    "2. 사실·수치·날짜·고유명사·약어는 절대 바꾸지 않는다.\n"
    "3. 내용을 추가하거나 추측하지 않는다. 문장을 요약하지도 않는다.\n"
    "4. 구어체·존댓말·군더더기만 정리한다.\n"
    "입력은 한 줄에 하나의 문장이며, 같은 개수의 줄로만 답한다. 설명은 쓰지 않는다."
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


def _collect(blocks: list[Block], texts: list[str], targets: list) -> None:
    for block in blocks:
        if isinstance(block, (Paragraph, ListItem)):
            text = plain(block.runs).strip()
            if text and any(ch.isalpha() for ch in text):
                texts.append(text)
                targets.append(block)
        elif isinstance(block, Callout):
            _collect(block.blocks, texts, targets)
        elif isinstance(block, Table):
            continue  # 표는 보내지 않는다


def _ask_llm(texts: list[str]) -> list[str]:
    base_url = os.environ.get("DOC2REPORT_LLM_BASE_URL")
    if base_url:
        return _ask_openai_compatible(texts, base_url)
    return _ask_anthropic(texts)


def _ask_openai_compatible(texts: list[str], base_url: str) -> list[str]:
    """vLLM/Ollama/TGI 등 OpenAI `/chat/completions` 호환 온프렘 엔드포인트용.

    사내 Qwen 서빙처럼 인터넷이 닫힌 환경을 겨냥한 경로라 anthropic SDK에
    기대지 않고 httpx(코어 의존성)로 직접 호출한다.
    """
    model = os.environ.get("DOC2REPORT_MODEL")
    if not model:
        raise RuntimeError("DOC2REPORT_LLM_BASE_URL 사용 시 DOC2REPORT_MODEL 이 필수입니다")
    api_key = os.environ.get("DOC2REPORT_LLM_API_KEY")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    out: list[str] = []
    with httpx.Client(timeout=120.0) as client:
        for chunk in _chunks(texts, 40):
            response = client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json={
                    "model": model,
                    "temperature": 0,
                    "messages": [
                        {"role": "system", "content": _SYSTEM},
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


def _ask_anthropic(texts: list[str]) -> list[str]:
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
            system=_SYSTEM,
            messages=[{"role": "user", "content": "\n".join(chunk)}],
        )
        lines = message.content[0].text.strip().splitlines()
        if len(lines) != len(chunk):
            raise RuntimeError(f"응답 줄 수가 맞지 않음 ({len(lines)} ≠ {len(chunk)})")
        out.extend(lines)
    return out


def _chunks(items: list[str], size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]
