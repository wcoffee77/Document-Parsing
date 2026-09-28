"""LLM 다듬기 — 특히 OpenAI 호환 온프렘 엔드포인트(vLLM/Ollama/TGI, Qwen 계열) 경로.

실제 네트워크 호출 없이 httpx.MockTransport로 서버 응답을 흉내 낸다.
Anthropic 경로(ANTHROPIC_API_KEY)는 SDK 설치 여부에 좌우되므로 여기서는 다루지 않는다.
"""

from __future__ import annotations

import httpx
import pytest

from doc2report.ir import Document, Paragraph, Run
from doc2report.profile import load_profile
from doc2report.transform import llm_polish
from doc2report.transform.llm_polish import polish_document


@pytest.fixture
def profile():
    return load_profile("default")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("DOC2REPORT_LLM_BASE_URL", "DOC2REPORT_MODEL", "DOC2REPORT_LLM_API_KEY",
                "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)


def _doc(*texts: str) -> Document:
    return Document(blocks=[Paragraph(runs=[Run(t)]) for t in texts])


def _openai_response(lines: list[str]) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": "\n".join(lines)}}]})


_RealClient = httpx.Client


def _install_mock_server(monkeypatch, handler):
    """`httpx.Client(timeout=...)` 호출을 MockTransport로 가로챈다."""

    def factory(*, timeout=None):
        return _RealClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "Client", factory)


def test_base_url_routes_to_openai_compatible_endpoint(monkeypatch, profile):
    monkeypatch.setenv("DOC2REPORT_LLM_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("DOC2REPORT_MODEL", "qwen2.5-32b-instruct")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return _openai_response(["검토함."])

    _install_mock_server(monkeypatch, handler)

    doc, changes = polish_document(_doc("검토했습니다."), profile)

    assert seen["url"] == "http://localhost:8000/v1/chat/completions"
    assert seen["auth"] is None  # 키를 안 주면 Authorization 헤더도 안 보낸다
    assert doc.blocks[0].runs[0].text == "검토함."
    assert changes == [llm_polish.Change("검토했습니다.", "검토함.", "LLM")]


def test_think_block_is_stripped_before_line_matching(monkeypatch, profile):
    """thinkingcap처럼 추론 모드 모델은 답 앞에 <think>...</think>를 끼워 보낸다."""
    monkeypatch.setenv("DOC2REPORT_LLM_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("DOC2REPORT_MODEL", "thinkingcap")

    def handler(request: httpx.Request) -> httpx.Response:
        raw = "<think>\n내부 추론 과정...\n여러 줄일 수 있음\n</think>\n검토함."
        return httpx.Response(200, json={"choices": [{"message": {"content": raw}}]})

    _install_mock_server(monkeypatch, handler)

    doc, changes = polish_document(_doc("검토했습니다."), profile)

    assert doc.blocks[0].runs[0].text == "검토함."
    assert changes == [llm_polish.Change("검토했습니다.", "검토함.", "LLM")]


def test_api_key_sent_as_bearer_token_when_set(monkeypatch, profile):
    monkeypatch.setenv("DOC2REPORT_LLM_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("DOC2REPORT_MODEL", "qwen2.5-32b-instruct")
    monkeypatch.setenv("DOC2REPORT_LLM_API_KEY", "sk-local-test")
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        return _openai_response(["검토함."])

    _install_mock_server(monkeypatch, handler)

    polish_document(_doc("검토했습니다."), profile)

    assert captured["auth"] == "Bearer sk-local-test"


def test_base_url_without_model_falls_back_to_rules(monkeypatch, profile):
    monkeypatch.setenv("DOC2REPORT_LLM_BASE_URL", "http://localhost:8000/v1")
    # DOC2REPORT_MODEL 미설정

    doc, changes = polish_document(_doc("검토했습니다."), profile)

    assert doc.blocks[0].runs[0].text == "검토했습니다."  # 원문 유지
    assert len(changes) == 1
    assert changes[0].rule == "LLM 건너뜀"
    assert "DOC2REPORT_MODEL" in changes[0].after


def test_response_line_count_mismatch_falls_back_to_rules(monkeypatch, profile):
    monkeypatch.setenv("DOC2REPORT_LLM_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("DOC2REPORT_MODEL", "qwen2.5-32b-instruct")

    def handler(request: httpx.Request) -> httpx.Response:
        return _openai_response(["한 줄만 옴"])  # 원문은 두 줄인데 응답은 한 줄

    _install_mock_server(monkeypatch, handler)

    doc = _doc("검토했습니다.", "완료하였습니다.")
    doc, changes = polish_document(doc, profile)

    assert [p.runs[0].text for p in doc.blocks] == ["검토했습니다.", "완료하였습니다."]
    assert changes[0].rule == "LLM 건너뜀"


def test_server_error_falls_back_to_rules(monkeypatch, profile):
    monkeypatch.setenv("DOC2REPORT_LLM_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("DOC2REPORT_MODEL", "qwen2.5-32b-instruct")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "internal"})

    _install_mock_server(monkeypatch, handler)

    doc, changes = polish_document(_doc("검토했습니다."), profile)

    assert doc.blocks[0].runs[0].text == "검토했습니다."
    assert changes[0].rule == "LLM 건너뜀"


def test_base_url_takes_precedence_over_anthropic(monkeypatch, profile):
    """온프렘 엔드포인트가 설정되면 ANTHROPIC_API_KEY가 있어도 Anthropic 경로는 안 탄다."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unused")
    monkeypatch.setenv("DOC2REPORT_LLM_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("DOC2REPORT_MODEL", "qwen2.5-32b-instruct")

    def fail_if_called(_texts):
        raise AssertionError("Anthropic 경로가 호출되면 안 됨")

    monkeypatch.setattr(llm_polish, "_ask_anthropic", fail_if_called)

    def handler(request: httpx.Request) -> httpx.Response:
        return _openai_response(["검토함."])

    _install_mock_server(monkeypatch, handler)

    doc, changes = polish_document(_doc("검토했습니다."), profile)

    assert doc.blocks[0].runs[0].text == "검토함."


def test_no_backend_configured_falls_back_to_rules(monkeypatch, profile):
    """DOC2REPORT_LLM_BASE_URL도 ANTHROPIC_API_KEY도 없으면 조용히 규칙 결과를 유지한다."""
    doc, changes = polish_document(_doc("검토했습니다."), profile)

    assert doc.blocks[0].runs[0].text == "검토했습니다."
    assert changes[0].rule == "LLM 건너뜀"
    assert "ANTHROPIC_API_KEY" in changes[0].after
