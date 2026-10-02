"""온프렘 LLM 속도·긴 입력 점검 — 결과 숫자만 출력한다(응답 글은 안 보여 준다).

    uv run python tools/llm_speed.py [--long 30000]

측정(각 1회): ① 짧은 질문 지연 ② 입력 ~1,500자 → 출력 ~300자 ③ 같은 질문, 추론(thinking) 끄기 시도
④ 긴 입력(기본 30,000자)을 넣고 한 줄만 답하게 — 입력 처리(prefill) 속도와 긴 문맥에서 지시를 지키는지.
서버가 usage를 주면 토큰 수·초당 토큰도 계산한다. DOC2REPORT_LLM_BASE_URL·DOC2REPORT_MODEL은 환경변수 또는
웹 화면에 등록한 값을 쓴다.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx  # noqa: E402

from doc2report.account import load_and_apply  # noqa: E402

_THINK = re.compile(r"<think>.*?</think>", re.S)
_PARA = ("상반기 채용 현황을 점검한 결과 경력 채용 계획 40명 중 27명이 입사를 확정했고 6명은 처우를 협의 중입니다. "
         "직무별로는 공정 직군이 계획 대비 80%를 채운 반면 설계 직군은 57%에 그쳐 보강이 필요합니다. ")


def ask(client: httpx.Client, base: str, model: str, headers: dict, prompt: str, *, max_tokens: int,
        no_think: bool = False) -> dict:
    body = {"model": model, "temperature": 0, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}]}
    if no_think:
        body["chat_template_kwargs"] = {"enable_thinking": False}
    start = time.perf_counter()
    try:
        response = client.post(f"{base.rstrip('/')}/chat/completions", headers=headers, json=body)
        response.raise_for_status()
    except Exception as error:  # noqa: BLE001
        return {"error": f"{type(error).__name__}: {str(error)[:120]}"}
    elapsed = time.perf_counter() - start
    data = response.json()
    text = data["choices"][0]["message"].get("content") or ""
    usage = data.get("usage") or {}
    return {"sec": elapsed, "out_chars": len(_THINK.sub("", text).strip()), "had_think": "<think>" in text, "answer": _THINK.sub("", text).strip(),
            "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens")}


def show(label: str, result: dict) -> None:
    if "error" in result:
        print(f"{label}: 실패 — {result['error']}")
        return
    parts = [f"{result['sec']:.1f}초", f"출력 {result['out_chars']}자"]
    if result["prompt_tokens"] is not None:
        parts.append(f"입력 {result['prompt_tokens']}토큰")
    if result["completion_tokens"]:
        parts.append(f"출력 {result['completion_tokens']}토큰(초당 약 {result['completion_tokens'] / result['sec']:.0f})")
    if result["had_think"]:
        parts.append("<think> 포함")
    print(f"{label}: " + ", ".join(parts))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--long", type=int, default=30000, help="긴 입력 시험의 글자 수")
    args = parser.parse_args()
    load_and_apply()
    base, model = os.environ.get("DOC2REPORT_LLM_BASE_URL"), os.environ.get("DOC2REPORT_MODEL")
    if not base or not model:
        sys.exit("DOC2REPORT_LLM_BASE_URL·DOC2REPORT_MODEL이 없습니다(웹 화면 등록 또는 환경변수).")
    key = os.environ.get("DOC2REPORT_LLM_API_KEY")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    print(f"모델 {model}")
    with httpx.Client(timeout=600.0) as client:
        show("① 짧은 질문", ask(client, base, model, headers, "한 문장으로 인사해 주세요.", max_tokens=64))
        prompt = (_PARA * 8) + "\n\n위 글을 300자 안팎의 개조식 항목 3개로 정리해 주세요."
        show("② 1,500자→300자", ask(client, base, model, headers, prompt, max_tokens=1500))
        show("③ 같은 질문, 추론 끄기", ask(client, base, model, headers, prompt, max_tokens=1500, no_think=True))
        # ④ 긴 입력에서 찾기 시험 — 세기는 LLM이 원래 약해서(이전 판은 "몇 번 나오나"였고 불일치가 나와도 길이 탓인지
        #    알 수 없었다) 문서 곳곳에 심은 고유한 사실 3개를 위치별로 묻는다. 문장마다 숫자를 달리해 입력 캐시가 안 걸리게 한다.
        import random

        rng = random.Random(args.long)
        count = max(30, args.long // 70)
        sentences = [f"{rng.randint(1, 99)}번 팀은 {rng.randint(100, 999)}명 중 {rng.randint(10, 99)}명을 {rng.randint(1, 12)}월에 "
                     f"배치했고 예산은 {rng.randint(100, 9999)}만 원이었습니다. " for _ in range(count)]
        needles = {"앞(10%)": 0.10, "중간(50%)": 0.50, "뒤(90%)": 0.90}
        facts = {name: f"{rng.randint(10000, 99999)}" for name in needles}
        for name, at in needles.items():
            sentences.insert(int(len(sentences) * at), f"참고로 {name} 위치의 확인 코드는 {facts[name]}입니다. ")
        document = "".join(sentences)
        print(f"④ 긴 입력 {len(document):,}자 찾기 시험")
        for name in needles:
            question = f"\n\n위 글에서 '{name} 위치의 확인 코드'는 무엇입니까? 숫자만 답하세요."
            result = ask(client, base, model, headers, document + question, max_tokens=64, no_think=True)
            show(f"   {name}", result)
            if "error" not in result:
                found = re.findall(r"\d+", result["answer"])
                print(f"     정답 {facts[name]} → {'일치' if facts[name] in found else '불일치'}")


if __name__ == "__main__":
    main()
