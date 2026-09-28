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
> **원인 확정 (사내 LLM에 직접 물어서 확인함)**: 위 403들은 전부 **`HTTP_PROXY`
> 환경변수 때문에 httpx가 요청을 사내 Squid 프록시(`12.26.204.100:8000`)로
> 우회했고, 그 프록시의 접근 차단 정책이 `75.12.15.121`을 거부**해서 난 것이었다.
> `curl.exe`/PowerShell(`Invoke-WebRequest` 등)은 이 프록시를 안 타서 그때는
> 됐던 것 — `netsh winhttp show proxy`가 "direct access"라고 답한 것과도
> 모순 없다(그건 WinHTTP 설정이고, `HTTP_PROXY`는 별개의 프로세스 환경변수).
> **해결**: `scripts/onprem_env.sh`/`.ps1`에 `NO_PROXY=75.12.15.121`을 이미
> 넣어 뒀다 — 이 스크립트를 불러 쓰면 자동으로 우회된다. 다만 이건 임시
> 조치이고, **네트워크 담당자에게 이 목적지에 대한 정식 프록시 예외 등록을
> 요청**하는 게 정석이다.

## 1. 코드 받기

```bash
git clone <저장소 URL>
cd Document-Parsing
git checkout claude/next-tasks-zmwk4x
uv sync
```

`llm` extra(`uv sync --extra llm`)는 **필요 없다** — 온프렘 경로는 코어 의존성
`httpx`만 쓴다. `anthropic` 패키지는 Anthropic API로 쓸 때만 필요.

> **`uv` 설치가 막힐 때 (실제로 겪음)**: 이 사내 PC는 `astral.sh`, `pypi.org`
> 등 외부 인터넷 접속 자체가 정책으로 막혀 있어서 `irm ... | iex`나
> `pip install uv`가 안 될 수 있다. 그럴 땐 인터넷 되는 다른 PC에서
> `https://github.com/astral-sh/uv/releases/latest`의
> `uv-x86_64-pc-windows-msvc.zip`을 받아 `uv.exe`만 뽑아서 USB/사내 파일
> 공유로 옮긴다. 프로젝트 폴더에 두고 이렇게 쓰면 된다(PowerShell은 현재
> 폴더 실행파일에 `.\`가 필요):
> ```powershell
> .\uv.exe --version
> .\uv.exe sync
> ```
> 매번 `.\` 붙이기 귀찮으면 그 세션에서 `Set-Alias uv .\uv.exe` 해두고
> 이 문서의 `uv ...` 명령을 그대로 쓴다(창 새로 열면 다시 설정 필요).
> `uv.exe`는 `.gitignore`에 이미 추가돼 있어 실수로 커밋되지 않는다.
>
> **`uv sync`도 막힐 때 (실제로 겪음 — `pypi.org` 접속 자체가 막혀
> `typing-inspection` 등 의존성을 못 받음)**: 처음엔 `uv sync --offline
> --find-links <폴더>`를 안내했으나 **이건 틀렸다** — `uv.lock`이 각 패키지의
> 정확한 PyPI 다운로드 URL을 그대로 박아 두기 때문에, `uv sync`는
> `--find-links`가 있어도 그 URL만 찾다가 캐시가 비어 있으면 실패한다(직접
> 캐시를 비우고 재현해서 확인함). **`uv sync` 대신 `uv pip install`로 직접
> 설치해야 한다** — 이건 `uv.lock`을 참고하지 않고 `--find-links`만 본다.
>
> 클로드가 Windows/Python 3.13용으로 미리 받아 압축해 둔 `wheelhouse` zip을
> 전달받았다면(런타임 24개 + `doc2report`를 빌드하는 데 필요한 hatchling 등
> 7개, 총 31개 wheel 포함), USB/사내 파일공유로 옮기고 압축을 풀어 프로젝트
> 폴더 바로 밑에 `wheelhouse` 폴더가 생기게 한 뒤(`dir`로 확인):
> ```powershell
> .\uv.exe venv
> .\uv.exe pip install --no-index --find-links wheelhouse -r scripts\onprem-requirements.txt -r scripts\onprem-build-requirements.txt
> .\uv.exe pip install --no-index --find-links wheelhouse -e .
> ```
> 이 세 줄로 가상환경 생성 + 의존성 설치 + `doc2report` 자체 설치가 끝난다
> (uv 0.12.19, 완전히 빈 캐시 상태에서 직접 재현해 검증 완료 — 네트워크 요청
> 0회, `doc2report convert`까지 정상 동작 확인함). 이후 실행은 `uv run`에
> `--no-sync`를 붙여서 `uv.lock`을 다시 확인하지 않게 한다:
> ```powershell
> .\uv.exe run --offline --no-sync doc2report convert ...
> ```
> **이 문서의 4번 이후 모든 `uv run ...` 명령 앞에 `--offline --no-sync`를
> 붙여서 실행**하면 된다.
>
> `wheelhouse`가 없다면, 인터넷 되는 아무 PC(Windows 아니어도 됨, pip만 있으면
> 됨)에서 이렇게 받아서 그 폴더를 옮기면 된다:
> ```bash
> pip download -r scripts/onprem-requirements.txt -d wheelhouse \
>   --platform win_amd64 --python-version 3.13 --implementation cp --abi cp313 \
>   --only-binary=:all:
> pip download colorama==0.4.6 -d wheelhouse --only-binary=:all:   # Windows 전용 조건부 의존성, 위 명령엔 안 잡힘
> pip download -r scripts/onprem-build-requirements.txt -d wheelhouse --only-binary=:all:   # doc2report 빌드(-e .)에 필요
> ```

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

> **PowerShell 주의 1**: `curl`은 PowerShell에서 `Invoke-WebRequest`의 별칭이라
> 위 명령을 그대로 치면 옵션을 오해석해 "Uri 값을 제공하십시오"류 오류가 난다.
> `curl` 대신 `curl.exe`를 쓰거나(줄바꿈은 `\` 대신 백틱 `` ` ``), 아래처럼
> PowerShell 네이티브로 실행한다.
>
> ```powershell
> Invoke-RestMethod -Uri "http://75.12.15.121:8000/v1/models" | ConvertTo-Json -Depth 5
> ```
>
> **PowerShell 주의 2 (중요)**: Windows PowerShell 5.1의 `Invoke-RestMethod`는
> 응답 헤더에 `charset=utf-8`이 명시 안 돼 있으면 한글을 잘못된 인코딩으로
> 먼저 디코딩해버려서 콘솔·파일 어디로 출력해도 이미 깨진 상태가 된다(실제로
> 겪음). `Invoke-WebRequest` + 원본 바이트를 직접 UTF-8로 디코딩해야 한다:
>
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
> $resp = Invoke-WebRequest -Uri "http://75.12.15.121:8000/v1/chat/completions" `
>   -Method Post -ContentType "application/json; charset=utf-8" `
>   -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
>
> $text = [System.Text.Encoding]::UTF8.GetString($resp.RawContentStream.ToArray())
> $obj = $text | ConvertFrom-Json
> $obj.choices[0].message.content | Out-File out\llm_test_response.txt -Encoding utf8
> notepad out\llm_test_response.txt
> ```
>
> PowerShell 7(`pwsh`)이 있으면 이 버그가 없어 `Invoke-RestMethod`를 그대로 써도 된다.

응답에서 확인:

- [ ] HTTP 200, `choices[0].finish_reason` == `"stop"` (`"length"`면 잘린 것)
- [x] `choices[0].message.content`가 **문자열**인가 — 문자열 맞음, 확인 완료
- [x] `<think>...</think>` 블록이 섞여 있는가 — **없음**, 추론 모드 관련 걱정 안 해도 됨
- [x] 응답 줄 수가 요청 줄 수(2줄)와 같은가 — **아니오, 12줄 나옴** (아래 참고)

> **확인된 결과**: `<think>` 없고 `content`는 정상 문자열 — 여기까진 문제없다.
> 다만 12줄에 "권장표현", "편집자 팁" 같은 설명이 섞여 나오고 문장도 `~다`로
> 끝났는데, 이건 이 curl 테스트가 접속 확인용으로 시스템 프롬프트를
> `"너는 한국 회사의 보고서 편집자다."` 한 줄로 일부러 간단히 줄였기 때문이다.
> 실제 코드(`llm_polish.py`)가 보내는 프롬프트는 "한 줄에 한 문장, 설명 금지,
> 같은 줄 수로만 답변, 명사형(~함/~임)으로 종결" 을 명시하는 훨씬 엄격한
> 버전이라 다르게 나올 수 있다 — **최종 판단은 4번(실제 문서 변환) 결과로
> 한다.** 4번에서도 여전히 줄 수가 안 맞으면 코드가 자동으로 규칙 기반에
> 폴백하니 안전하게 동작은 하되, LLM 다듬기 기능 자체는 이 모델엔 프롬프트를
> 더 세게 조정해야 살아날 수 있다.

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

> **PowerShell 주의 (실제로 겪음)**: 사내 PC 실행 정책(execution policy)이
> `.ps1` 실행 자체를 막아서 "파일을 로드할 수 없습니다" 오류가 날 수 있다.
> 이럴 땐 스크립트 대신 값을 직접 입력해도 결과는 같다 — 이건 정책 제한과
> 무관하다.
> ```powershell
> $env:DOC2REPORT_LLM_BASE_URL = "http://75.12.15.121:8000/v1"
> $env:DOC2REPORT_MODEL = "thinkingcap"
> $env:NO_PROXY = "75.12.15.121"
> ```
> `NO_PROXY`를 빠뜨리면 안 된다 — 없으면 `HTTP_PROXY`가 걸려 있을 때
> httpx 요청이 사내 프록시로 우회돼 403이 난다(0번 항목 참고, 실제로 겪음).
> 단, 이 값은 **현재 PowerShell 창에서만 유지된다** — 창을 새로 열면 다시
> 입력해야 한다. 매번 `.ps1`을 쓰고 싶으면 창 열 때마다 먼저
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` 실행.

## 4. 실제 사내 문서 변환

> 3번에서 오프라인 설치(wheelhouse)로 했다면 **`uv run`에 반드시
> `--offline --no-sync`를 붙인다** — 빠뜨리면 uv가 `uv.lock` 전체(확장 기능
> 포함)와 다시 동기화하려다 네트워크를 필요로 해서 엉뚱한 패키지(예:
> `pycparser`) 다운로드 실패로 막힌다(실제로 겪음). 아래 명령들은 이미
> 그 플래그를 넣은 상태다 — 온라인 환경이면 `.\uv.exe run` 대신 `uv run`,
> 플래그 없이 써도 된다.

```powershell
.\uv.exe run --offline --no-sync doc2report convert 사내문서.md -o out\보고서.docx --polish llm --report out\변경내역.md --date today
```

## 5. 결과 확인 (이 순서로)

1. `out/변경내역.md`를 **가장 먼저** 연다 — "LLM" 규칙으로 다듬어진 줄이 있는지,
   아니면 `LLM 건너뜀 — <사유>`로 규칙 기반에 폴백했는지 확인.

   > **"LLM" 행이 하나도 없어도 실패가 아닐 수 있다(실제로 겪음)**: 규칙
   > 기반(`stylize_ko`)이 LLM보다 먼저 실행되므로(`pipeline.py`), LLM은 이미
   > 개조식으로 바뀐 문장을 받는다. LLM이 "이미 맞다"고 판단해 입력과 똑같은
   > 문장을 돌려주면 `after == before`라 report에 아예 안 남는다(정상 동작 —
   > "규칙으로 안 되는 것만 LLM에 맡긴다"는 설계 그대로). 실제로 호출되고
   > 있는지 확실히 확인하려면, 규칙 기반이 절대 못 고칠 구어체 문장으로
   > 직접 테스트한다:
   > ```powershell
   > .\uv.exe run --offline --no-sync python -c "
   > from doc2report.ir import Document, Paragraph, Run
   > from doc2report.profile import load_profile
   > from doc2report.transform.llm_polish import polish_document
   >
   > doc = Document(blocks=[Paragraph(runs=[Run('아 그게 좀 애매한데 일단 진행하는 걸로 하죠 확인 부탁드립니다')])])
   > profile = load_profile('default')
   > doc2, changes = polish_document(doc, profile)
   > print('최종 텍스트:', doc2.blocks[0].runs[0].text)
   > print('changes:', changes)
   > "
   > ```
   > `changes`에 `rule='LLM'`이 찍히고 문장이 개조식으로 자연스럽게 바뀌면
   > 온프렘 연동이 실제로 동작하는 것 — thinkingcap 기준 검증 완료됨.
2. `out/보고서.docx`를 Word로 열어 문구·서식을 육안 확인.
3. 표 배치만 따로 보고 싶으면: `.\uv.exe run --offline --no-sync doc2report check 사내문서.md`
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

```powershell
.\uv.exe run --offline --no-sync doc2report convert 사내문서.md -o out\보고서.docx -p default --watch --open
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
