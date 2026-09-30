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

## 웹 화면 (권장)

Windows에서는 저장소 맨 위의 **`start_webapp.bat`을 더블클릭**한다. `scripts\confluence_env.ps1`
(Confluence 토큰)과 `scripts\onprem_env.ps1`(온프렘 LLM)이 있으면 먼저 불러온 뒤 서버를 띄우고
브라우저가 `http://127.0.0.1:8765/`로 열린다. 창을 닫거나 Ctrl+C로 끈다. 새 패키지가 필요 없다
(파이썬 표준 라이브러리 서버) — wheelhouse를 다시 만들 필요 없음.

```bash
doc2report web                       # macOS/Linux: scripts/start_webapp.sh
doc2report web --port 8800 --output-dir D:\보고서   # 포트·저장 폴더 바꾸기
```

| 구분 | 내용 |
|---|---|
| 입력 | Confluence 주소(여러 개, 한 줄에 하나), Word(.docx) 파일(끌어 놓기·여러 개), 글 붙여넣기(메일·메신저·메모 — 한 줄이 한 문단, 엑셀에서 복사한 표는 표로). **입력 목록의 순서대로 한 문서로 합친다**(↑↓로 순서 변경) |
| 옵션 | **자동 판단**: 제목·말머리가 있는 문단 비율로 원문 유지/새로 정리를 정한다(Confluence는 항상 원문 유지). 내용이 많은데 보고서 서식이면 Confluence 변환 서식을 권한다(바꾸지는 않음). **직접 선택**: 규칙 기본값, 문장 다듬기(안 함 / 파이썬 규칙: 어미를 개조식·명사로 끝내기, 긴 문장 나누기, 짧은 항목 합치기), 말머리(원문 그대로·말머리 만들기), 표(가로 페이지·위치). **LLM 다듬기**(두 모드 공통, 따로 켬): 맞춤법·띄어쓰기, 정식 보고서 어조, 모호한 표현 — 문장 끝 형태·사실·수치·제목·표는 그대로 |
| 서식(출력) | **보고서**(여백 위·아래 2.5cm·좌우 2.0cm, 바탕체, 제목 20pt·본문 14pt, 줄간격 1.45) / **Confluence 변환**(여백 모두 2cm, 맑은 고딕, 제목 18pt 가운데·밑줄, 본문 12pt·장평 95%·줄간격 1.0·단락 앞뒤 0pt, 표 10pt·장평 80% 고정) / **사용자 설정**(고른 서식에서 글꼴·크기·줄간격·본문 장평·표 글자 크기·표 장평·여백을 자유롭게 바꿈). 서식은 글꼴·크기·여백만 정하고, 말머리·문장 규칙은 "변환 옵션"에서 따로 고른다 |
| 공통 | 문서 제목, 날짜(넣지 않음/오늘/직접 지정), 여러 입력 합치기(쪽 구분 없이 이어 붙이기 — 입력 제목은 절 제목 / 입력마다 새 쪽 — 쪽마다 입력 제목을 큰 제목으로, 날짜도 쪽마다) |
| 출력 | Word(.docx) 항상 + PDF(Word로 변환) + Markdown(.md) 선택, 변경 내역(.md). 저장 폴더(기본 `out\webapp`)에 `YYYYMMDD_제목.docx`로 저장하고 이름이 겹치면 `_2`, `_3`… |
| 결과 | "열기"를 누르면 이 PC의 Word/PDF 뷰어로 바로 열림, 브라우저로 보기·내려받기·폴더 열기, 자동 판단 이유·레이아웃 메모·문구 수정 내역 표시, 최근 결과 목록 |
| 상태 표시 | 화면 위에 Confluence 연결 설정·LLM(모델명)·PDF 변환기 유무. LLM은 "연결 시험"으로 문장 하나를 실제로 다듬어 볼 수 있다 |

**git pull로 업데이트한 뒤에는 서버 창을 닫고 `start_webapp.bat`을 다시 실행**한다(화면은 Ctrl+F5로
새로 고침). 예전 서버가 떠 있으면 새로 켤 때 자동으로 끄고 넘겨받으며, 그럴 수 없는 예전 버전이면
창을 닫으라고 안내한다. 화면 위에 빨간·노란 안내 띠가 뜨면 거기 적힌 대로 하면 된다.

서버는 이 PC(127.0.0.1)에서만 접속된다 — Confluence 토큰이 서버 환경변수에 있으므로
`--host 0.0.0.0`으로 다른 PC에 여는 것은 권하지 않는다.

## 명령줄 사용

```bash
doc2report convert 보고서.md -o 보고서.docx
doc2report convert 보고서.md -o 보고서.docx --date today --report 변경내역.md
doc2report check 보고서.md              # 표가 어떻게 배치될지만 미리 확인
doc2report convert 기존보고서.docx      # Word 입력 → 기존보고서_보고서.docx
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
| 표 | 12pt → 11pt → 10pt → 9pt 순으로 필요한 만큼만 줄임(9pt가 하한, 장평은 100% 고정). 표 폭은 **표 바로 윗줄 문장의 왼쪽 끝(말머리 자리)부터 오른쪽 여백까지** 꽉 채움(표 제목도 같은 왼쪽 끝). 열 폭은 머리가 아니라 내용이 정하고 비슷하게 맞춤. 내용이 유난히 많아 3줄을 넘는 셀은 **그 셀만** 더 줄이되, 표 전체와 2pt 넘게 차이나지 않게 표 전체도 같이 낮춤(예: 12pt 표에 9pt 셀 → 표 전체 11pt). 3줄 이상인 셀이 있으면 **그 열의 본문 셀 전부** 왼쪽 맞춤이고 글자 크기도 그 열에서 가장 작은 값으로 통일(머리행 제외). 표 안 굵은 제목·목록도 표 글자 크기로. 머리행 음영은 옅은 회색(`F2F2F2`). 머리가 2줄을 넘으면 축약(`rules/abbreviations.yaml`) |
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
| 서식 | 여백 모두 2cm, 맑은 고딕, 제목 18pt(가운데·밑줄), 본문 12pt·장평 95%·줄간격 1.0·단락 앞뒤 0pt, 표 10pt·장평 80% 고정(글씨가 많아도 더 줄이지 않음) |
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

**연결 페이지 한 번에 불러오기**(기본 켜짐): 본문 페이지 안에서 다른 페이지·첨부를 끌어다 붙인
매크로를 따라가 그 내용까지 한 문서로 변환한다. 끄려면 CLI `--no-linked`, 웹 화면은 Confluence 탭의
"본문에 연결된 페이지도 함께 불러오기" 체크 해제.

| 매크로 | 불러오는 내용 |
|---|---|
| 페이지 포함(`include`) | 그 페이지 본문 전체(펼치기 `expand` 안에 있어도 — 펼치기 제목은 굵은 줄로 남김) |
| 발췌 포함(`excerpt-include`) | 그 페이지의 발췌(`excerpt`) 부분만 |
| 하위 페이지(`children`)·페이지 트리(`pagetree`) | 하위 페이지마다 제목 + 본문(스페이스 전체 `@home` 트리는 제외) |
| 첨부 보기(`view-file` 등) | Word(.docx)는 내용째, 그 밖의 파일은 "※ 첨부: 파일명" 한 줄 |

**본문 링크·책갈피 따라가기**(기본 꺼짐, CLI `--follow-links`에서만):
다른 페이지로 가는 링크를 따라가 링크가 든 문단 바로 뒤에 넣는다. 책갈피(앵커) 링크면 그 책갈피부터 다음 같은 급
제목 전까지만, 책갈피 없는 링크면 페이지 전체. 같은 페이지 안 책갈피 링크는 내용이 이미 있으므로 무시한다.
매크로가 문단·목록 항목 안에 들어 있어도 불러온다.

불러온 문서(페이지 포함·하위 페이지·첨부 Word)는 **새 쪽에서 그 문서 제목**(문서 제목 서식)과 함께 시작한다.
발췌 포함은 조각이라 그 자리에 이어 붙는다.

상한: 연결 페이지 40개, 연결의 연결 4단계. 서로 포함하는 순환은 한 번만 넣는다. 불러온 것·못 불러온 것은
전부 `--report`에 남는다. 표 칸 안의 페이지 포함은 표가 깨지지 않게 "(포함 페이지 '제목')"만 남긴다.

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
입력(.md / Confluence / .docx / 붙여넣은 글) → 파서 → IR(여러 입력은 합침) → 문구 정규화 → 레이아웃 계산 → docx 렌더 (→ PDF / Markdown)
```

`src/doc2report/` 아래에서 `ir.py`가 단계 사이의 유일한 계약이다.
서식 값은 `profile.py`가, 표 맞춤은 `layout/table_fit.py`가, OOXML 조작은
`render/oxml.py`가 전담한다.
