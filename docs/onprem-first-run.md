# 사내 PC 첫 실행 가이드 — 온프렘 Qwen 연동 테스트

사내 PC로 옮긴 뒤 **이 문서 순서만 그대로 따라 하면** 온프렘 LLM 연동과 실제 문서
변환 테스트를 처음부터 끝까지 할 수 있다. 각 단계에서 걸리는 게 있으면 8번으로 가서
클로드에 전달할 내용을 챙긴다.

## 0. 사전 준비물

- [ ] 사내 PC에 Python 3.11+, `uv`, MS Word 설치 확인
- [x] 온프렘 서버 주소 확정: `http://75.12.15.121:8000/v1`, 모델명 `thinkingcap`
      (`scripts/onprem_env.sh` / `onprem_env.ps1`에 반영해 둠)
- [x] 인증 토큰 불필요 확인됨 — 스크립트의 `DOC2REPORT_LLM_API_KEY` 줄은 그대로 주석 유지
- [ ] 변환 테스트용 실제 사내 문서(.md, Confluence에서 내보낸 것)

> 이 값들은 사내 인트라넷 주소라 클라우드 세션에서는 연결을 확인할 수 없었다
> (`curl` 시도 결과 타임아웃). **2번부터는 반드시 사내 PC에서 직접 실행**한다.
> 모델명이 `thinkingcap`인 걸 보면 추론(thinking) 모드가 켜져 있을 가능성이 있고
> 실제로 켜져 있는지는 아직 확인 안 됨 — 대신 답 앞에 `<think>...</think>`가 섞여
> 와도 코드가 자동으로 잘라내도록 이미 반영해 뒀다(`llm_polish.py`). 다만 추론
> 과정이 길면 응답이 느려질 수 있으니 2번에서 응답 시간도 같이 봐 둔다.
>
> **포트 정정**: 처음엔 `8080`으로 안내했으나 실제 포트는 **`8000`**이다(정정 반영
> 완료). 앞서 `8080`에서 났던 `403` + `authentication required` HTML 페이지는
> Qwen 서버가 아니라 그 포트에 떠 있는 다른 서비스(사내 프록시 등)를 잘못 두드린
> 것이었을 가능성이 높다 — `8000`으로 다시 시도해서 먼저 확인.
>
> 그래도 같은 `403`/인증 페이지가 나오면 그때는 사내 프록시가 요청을 가로챈
> 것이다. 같은 PC의 일반 브라우저로 같은 URL을 열어 똑같이 막히는지 확인하고,
> 막히면 `netsh winhttp show proxy`로 프록시 설정을 보고 이 내부 IP가 예외
> (우회) 목록에 있는지 IT팀에 확인한다 — 코드로 우회할 문제가 아니라 망 정책
> 문제다.

## 1. 코드 받기

```bash
git clone <저장소 URL>
cd Document-Parsing
git checkout claude/next-tasks-zmwk4x
uv sync
```

`llm` extra(`uv sync --extra llm`)는 **필요 없다** — 온프렘 경로는 코어 의존성
`httpx`만 쓴다. `anthropic` 패키지는 Anthropic API로 쓸 때만 필요.

## 2. 서버 자체를 먼저 curl로 확인 (doc2report 실행 전)

```bash
curl -s http://75.12.15.121:8000/v1/models | python -m json.tool
```

`id` 값이 `thinkingcap`과 일치하는지 확인한다(다르면 3단계 `DOC2REPORT_MODEL`을
실제 `id` 값으로 바꾼다).

```bash
curl -s http://75.12.15.121:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"thinkingcap","temperature":0,
       "messages":[{"role":"system","content":"너는 한국 회사의 보고서 편집자다."},
                    {"role":"user","content":"검토했습니다.\n완료하였습니다."}]}' \
  | python -m json.tool
```

> **PowerShell 주의**: `curl`은 PowerShell에서 `Invoke-WebRequest`의 별칭이라
> 위 명령을 그대로 치면 옵션을 오해석해 "Uri 값을 제공하십시오"류 오류가 난다.
> `curl` 대신 `curl.exe`를 쓰거나(줄바꿈은 `\` 대신 백틱 `` ` ``), 아래처럼
> PowerShell 네이티브로 실행한다.
>
> ```powershell
> Invoke-RestMethod -Uri "http://75.12.15.121:8000/v1/models" | ConvertTo-Json -Depth 5
> ```
> ```powershell
> $body = @{
>     model = "thinkingcap"
>     temperature = 0
>     messages = @(
>         @{ role = "system"; content = "너는 한국 회사의 보고서 편집자다." },
>         @{ role = "user"; content = "검토했습니다.`n완료하였습니다." }
>     )
> } | ConvertTo-Json -Depth 5
>
> Invoke-RestMethod -Uri "http://75.12.15.121:8000/v1/chat/completions" `
>   -Method Post -ContentType "application/json; charset=utf-8" `
>   -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
> ```

응답에서 확인:

- [ ] HTTP 200, `choices[0].finish_reason` == `"stop"` (`"length"`면 잘린 것)
- [ ] `choices[0].message.content`가 **문자열**인가 (파츠 배열이면 코드 수정 필요)
- [ ] `<think>...</think>` 블록이 섞여 있는가 — 섞여 있어도 코드가 자동으로
      제거하도록 이미 반영했으니 정상, 응답 속도만 참고로 본다
- [ ] 응답 줄 수가 요청 줄 수(2줄)와 같은가 (`<think>` 제거 후 기준)

이상이 있으면 7번 항목을 보고 대응한다.

## 3. 환경 변수 설정

준비해 둔 스크립트를 불러 쓴다 (값 직접 입력할 필요 없음).

```bash
source scripts/onprem_env.sh          # bash/zsh
```
```powershell
. .\scripts\onprem_env.ps1            # PowerShell (맨 앞 ". " 필수)
```

서버가 인증 토큰을 요구하면 위 스크립트 파일을 열어 `DOC2REPORT_LLM_API_KEY` 줄의
주석을 풀고 값을 채운 뒤 다시 불러온다.

## 4. 실제 사내 문서 변환

```bash
uv run doc2report convert 사내문서.md -o out/보고서.docx --polish llm --report out/변경내역.md --date today
```

## 5. 결과 확인 (이 순서로)

1. `out/변경내역.md`를 **가장 먼저** 연다 — "LLM" 규칙으로 다듬어진 줄이 있는지,
   아니면 `LLM 건너뜀 — <사유>`로 규칙 기반에 폴백했는지 확인.
2. `out/보고서.docx`를 Word로 열어 문구·서식을 육안 확인.
3. 표 배치만 따로 보고 싶으면: `uv run doc2report check 사내문서.md`
4. (선택, 실측까지 하려면) Word COM으로 PDF 추출 → `pdfplumber`로 여백·정렬·표 폭
   측정. 명령은 `CLAUDE.md`의 "검증 방법" 절 참고. Word 프로세스가 남아 파일을
   잠그면 다음 변환이 `PermissionError`로 실패하니 `$word.Quit()` 확인.

## 6. 같은 실행 김에 레이아웃 세밀 조정 값도 확인

`profiles/default.yaml`에서 아래 5개 값을 실측하며 범위 안에서 확정한다.

| 값 | 현재(잠정) | 범위 |
|---|---|---|
| 본문 줄간격 | 1.45 | 1.4 ~ 1.5 |
| 단계 전환 간격 | 6pt (여유 시 12pt) | 6 ~ 12pt |
| 새 절 앞 간격(`- ` 뒤 `2.`) | 14pt | 12pt 이상 또는 한 줄 |
| 표 뒤 간격 | 18pt | 18pt 이상 |
| 행 최소 높이 | 7mm (여유 시 10mm) | "답답하지 않게" |

```bash
uv run doc2report convert 사내문서.md -o out/보고서.docx -p default --watch --open
```

YAML을 고치고 저장 → Word 새로고침을 반복하면 빠르게 맞출 수 있다.

## 7. 2단계에서 이상이 발견됐을 때 대응

| 증상 | 원인 | 대응 |
|---|---|---|
| `content`가 `[{"type":"text",...}]` 형태 | 멀티모달 지원 서버의 파츠 배열 응답 | 파싱 코드 수정 필요 — 응답 원본 들고 8번으로 |
| `<think>...</think>`가 답변에 섞임 | 추론(thinking) 모드 | **이미 처리됨** — `llm_polish.py`가 자동으로 잘라낸다. 그래도 이상하면 8번으로 |
| `finish_reason` == `"length"` | 서버 기본 `max_tokens`가 작음 (thinking 모드면 추론까지 포함해 더 잘 남) | 요청에 `max_tokens` 명시 필요 (현재 코드엔 없음) — 8번으로 |
| 응답 줄 수 불일치 / 500 에러 | 그때그때 다름 | 코드가 자동으로 규칙 기반 폴백 + `--report`에 사유 남김. 정상 동작이니 사유만 확인 |

## 8. 문제가 생기면 클로드에 전달할 것

- `out/변경내역.md`의 `LLM 건너뜀 — <사유>` 문자열 그대로
- 2단계 curl 응답 원본 JSON (민감정보 없는지 확인 후)

이 두 개만 있으면 `src/doc2report/transform/llm_polish.py`의 파싱 로직을 그 자리에서 고칠 수 있다.
