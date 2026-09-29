# doc2report

Confluence·Markdown 문서를 사내 규격 보고서(.docx)로 바꿔 주는 도구.

보고서를 만들 때 반복되는 기계적인 손질을 대신한다.

- **표를 A4 폭에 맞춘다** — 글꼴 메트릭으로 열마다 필요한 폭을 재고, 안 들어가면
  글자 크기 → 셀 여백 → (허용 시) 가로 페이지 순으로 줄여 가며 맞춘다.
  확정된 폭은 `tblLayout=fixed`로 못 박아 Word가 다시 흐트러뜨리지 못하게 한다.
- **문구를 개조식으로 다듬는다** — `~합니다` → `~함`, 긴 문장 분리, 날짜·숫자 표기 통일.
- **말머리와 서식을 규격에 맞춘다** — `□ → ○ → -` 같은 체계를 프로파일대로 적용.

## 설치

```bash
uv sync
```

## 사용

```bash
doc2report convert 보고서.md -o 보고서.docx
doc2report convert 보고서.md -o 보고서.docx --date today --report 변경내역.md
doc2report check 보고서.md              # 표가 어떻게 배치될지만 미리 확인
```

### 변환 전에 서식 고르기

```bash
doc2report convert 보고서.md -o out.docx --ask
```

글꼴 → 본문 크기 → 줄 간격 → 표 글자 크기를 차례로 물어본다. Enter만 누르면 기본값,
번호를 누르면 목록에서 선택, 값을 직접 입력해도 된다. 보여 줄 선택지는
프로파일의 `choices` 항목에서 온다.

물어보지 않고 바로 지정할 수도 있다.

```bash
doc2report convert 보고서.md -o out.docx \
  --font "맑은 고딕" --size 12pt --line-spacing 1.5 --table-size 10pt --margin 25mm
```

여기서 고른 값은 이번 변환에만 적용된다. 계속 쓰려면 `--save-profile profiles/내서식.yaml`.

## 기본 서식 (사내 규격)

| 항목 | 값 |
|---|---|
| 용지 | A4 세로, 여백 위·아래 25mm / 좌·우 20mm |
| 제목 | 바탕체 20pt 굵게 밑줄, 가운데 정렬 |
| 날짜 | 바탕체 14pt, 오른쪽 정렬, 단락 뒤 9pt (`2026. 10. 1` 형태) |
| 본문 | 바탕체 14pt, 줄 간격 1.45, 왼쪽 맞춤 |
| 들여쓰기 | 문서에서 가장 바깥 단계는 0cm, 그 아래 0.4cm, 그 아래 0.8cm (###부터 시작하는 문서도 첫 문장이 0cm) |
| 빈 줄 | 글자가 없거나 보이지 않는 글자(제로폭 공백·한글 채움문자)뿐인 줄·제목은 뺌 — 리포트에 코드가 남음 |
| 단락 체계 | `1.` → `□`(0.4cm 들여쓰기) → `-`(0.8cm), `1.`·`□` 단계는 굵게 |
| 단계 전환 | `1.`→`□`, `□`→`-` 또는 표 자리에 단락 뒤 6pt |
| 문장/제목 끝 | 가능하면 명사로 끝냄 (`인덱스를 재설계하였습니다` → `인덱스 재설계`, 제목 `추진 배경임` → `추진 배경`), 안 되면 `~음` |
| 짧은 항목 병합 | 같은 단계의 짧은 항목이 연달아 나오면 "및"으로 둘씩 합침 (`10월 중 2차 성능 시험 실시` + `미흡 사항은 4분기 과제로 이관` → 한 줄) |
| 표 | 12pt → 11pt → 10pt → 9pt 순으로 필요한 만큼만 줄임(9pt가 하한, 장평은 100% 고정). 표 전체는 오른쪽 정렬. 열 폭은 머리가 아니라 내용이 정하고 비슷하게 맞춤. 내용이 유난히 많아 3줄을 넘는 셀은 **그 셀만** 더 줄이되, 표 전체와 2pt 넘게 차이나지 않게 표 전체도 같이 낮춤(예: 12pt 표에 9pt 셀 → 표 전체 11pt). 3줄 이상인 셀이 있으면 **그 열의 본문 셀 전부** 왼쪽 맞춤이고 글자 크기도 그 열에서 가장 작은 값으로 통일(머리행 제외). 표 안 굵은 제목·목록도 표 글자 크기로. 머리행 음영은 옅은 회색(`F2F2F2`). 머리가 2줄을 넘으면 축약(`rules/abbreviations.yaml`) |
| 표 제목 | 표 바로 위 `【사업현황】`처럼 꺾쇠로 감싼 문단 → 꺾쇠·원래 정렬 그대로 표 제목화(앞에 붙던 말머리만 제외) |
| 참고사항(`※`) | 본문보다 2pt 작게, 윗줄 문단보다 0.4cm 더 들여씀 |
| 꺾쇠 표기 | `【…】` `[…]` 등 꺾쇠로 시작하는 줄에는 `□`·`-` 말머리를 붙이지 않음 (모든 문서) |
| 표 주석 | 표 바로 아래 인용문·`*`/`※` 문단 → `* ` 로 시작하는 10pt |
| 원문에 이미 있는 말머리 | 원문에 `1.` `1)` `□` `-` `·` `①` `※` 등이 문자로 이미 있으면 **바꾸지 않고 그대로** 쓰고, 프로파일 말머리는 말머리 없는 항목에만 붙임 |

문서 첫 줄이 날짜 한 줄이면 자동으로 날짜 서식이 적용된다. 없으면 `--date today`로 넣는다.
마크다운의 `##`, `###` 제목은 `1.`, `□` 단계로 흡수된다
(`text.headings_as_levels: false`로 끄면 제목 스타일을 따로 쓴다).

### Confluence·내용 많은 문서 (`confluence` 프로파일)

Confluence URL을 넣으면 `-p` 없이도 `profiles/confluence.yaml`이 쓰인다(`default`를 물려받음).
Confluence 문서는 글이 많고 이미 정리된 문장이라 규칙이 다르다.

| 항목 | 값 |
|---|---|
| 글자 크기 | 제목 16pt, 본문 12pt, 표 11pt → 9pt |
| 문장 | 다듬지 않음(`text.polish: none` — 개조식·명사 종결·"및" 병합·LLM 모두 안 함) |
| 말머리 | 원문 그대로 — 원문에 말머리가 없는 제목·문단에도 새로 만들지 않음(`text.auto_markers: false`). 정리 안 된 글을 새 보고서로 만들 땐 `-p default --polish llm` (말머리 생성 + 문장 다듬기) |
| 굵은 글씨 | 원문에서 굵던 글씨와 제목만(`text.level_bold: false` — 사내 규격의 `1.`·`□` 문장 전체 굵게는 안 씀) |

마크다운이라도 글이 많은 문서면 `-p confluence`로 고른다. `--polish`를 직접 주면 프로파일보다
우선하니, Confluence 변환에는 `--polish llm`을 붙이지 않는다.

Confluence에서 바로 가져오려면 환경변수를 설정한다.

```bash
export CONFLUENCE_URL=https://회사.atlassian.net/wiki
export CONFLUENCE_USERNAME=me@company.com
export CONFLUENCE_API_TOKEN=xxxx
doc2report convert https://회사.atlassian.net/wiki/spaces/TEAM/pages/12345 -o 보고서.docx
```

Server/Data Center(사내 자체 호스팅)면 `CONFLUENCE_USERNAME`은 비우고
개인 액세스 토큰(PAT)만 `CONFLUENCE_API_TOKEN`에 넣는다.

사내 프록시가 자체 CA로 HTTPS를 중계해 "SSL 인증서 검증 실패"가 나면
`CONFLUENCE_CA_BUNDLE`(또는 `REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE`)에 사내 루트
인증서(`.crt`/`.pem`) 경로를 넣는다. 그래도 안 되거나 403으로 막히면 Windows에서
자동으로 PowerShell(`Invoke-WebRequest`)로 재시도한다 — `DOC2REPORT_CONFLUENCE_
TRANSPORT=powershell`로 처음부터 강제할 수도 있다.

사내 PC에서 처음 연결할 때 확인할 체크리스트와 흔한 오류 대응은
[docs/confluence-first-run.md](docs/confluence-first-run.md)에 정리해 뒀다.

## 문구를 LLM으로 다듬기 (선택)

기본값(`--polish rules`)은 규칙 기반이다. 규칙으로 못 잡는 어색한 문장만 LLM에
맡기려면:

```bash
doc2report convert 보고서.md -o out.docx --polish llm --report 변경내역.md
```

백엔드는 둘 중 하나를 쓴다.

- **Anthropic API**: `ANTHROPIC_API_KEY` 설정. 모델은 기본값을 쓰거나 `DOC2REPORT_MODEL`로 지정.
- **OpenAI 호환 온프렘 엔드포인트** (vLLM·Ollama·TGI 등, 사내 Qwen 서빙 포함):

  ```bash
  export DOC2REPORT_LLM_BASE_URL=http://<host>:<port>/v1
  export DOC2REPORT_MODEL=<서버에 등록된 모델 id>
  export DOC2REPORT_LLM_API_KEY=xxxx   # 서버가 인증을 요구할 때만
  ```

  `DOC2REPORT_LLM_BASE_URL`이 설정돼 있으면 `ANTHROPIC_API_KEY`가 있어도 이쪽을 쓴다.

키·엔드포인트가 없거나 호출이 실패하면 조용히 규칙 기반 결과로 돌아가고, 그 사실이
`--report`에 `LLM 건너뜀 — <사유>`로 남는다. 실제로 다듬어졌는지는 항상 `--report`
파일로 확인한다.

## 서식 규격 자체를 바꾸기

여백·글꼴·글자 크기·말머리는 **코드가 아니라 `profiles/*.yaml`에만** 있다.

```bash
doc2report profile init --from 기존보고서.docx -o profiles/사내.yaml  # 기존 문서에서 규격 역추출
doc2report convert 보고서.md -o out.docx -p 사내 --watch --open      # 고치면서 바로 확인
doc2report profile diff default 사내 --sample 보고서.md              # 두 서식의 결과 비교
```

`--watch`는 입력이나 프로파일이 저장될 때마다 다시 변환한다. Word를 열어 둔 채
YAML을 고치고 저장 → 문서 새로고침 순으로 반복하면 서식을 빠르게 맞출 수 있다.

## 검증

```bash
uv run pytest                          # 폭 계산·어미 변환·docx XML 회귀 테스트
uv run python tools/score_corpus.py    # 대표 문서를 모두 변환해 점수로 비교
```

`score_corpus.py`는 표 폭 초과 건수, 글자 크기를 낮춘 표 수, 최대 표 폭, 문구 수정 건수를
표로 찍어 준다. Word가 설치된 Windows에서는 실제 렌더 페이지 수까지 센다.
서식을 고친 뒤 이 숫자가 나빠지지 않았는지 보면 된다.

## 구조

```
입력(.md / Confluence) → 파서 → IR → 문구 정규화 → 레이아웃 계산 → docx 렌더
```

`src/doc2report/` 아래에서 `ir.py`가 단계 사이의 유일한 계약이다.
서식 값은 `profile.py`가, 표 맞춤은 `layout/table_fit.py`가, OOXML 조작은
`render/oxml.py`가 전담한다.
