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
| 단락 체계 | `1.` → `□`(0.4cm 들여쓰기) → `-`(0.8cm), `1.`·`□` 단계는 굵게 |
| 단계 전환 | `1.`→`□`, `□`→`-` 또는 표 자리에 단락 뒤 6pt |
| 문장 끝 | 가능하면 명사로 끝냄 (`인덱스를 재설계하였습니다` → `인덱스 재설계`), 안 되면 `~음` |
| 표 | 12pt → 11pt, 장평 100% → 90% 순으로 필요한 만큼만 줄임. 열 폭은 머리가 아니라 내용이 정하고 비슷하게 맞춤. 머리가 2줄을 넘으면 축약(`rules/abbreviations.yaml`) |
| 표 주석 | 표 바로 아래 인용문·`*`/`※` 문단 → `* ` 로 시작하는 10pt |

문서 첫 줄이 날짜 한 줄이면 자동으로 날짜 서식이 적용된다. 없으면 `--date today`로 넣는다.
마크다운의 `##`, `###` 제목은 `1.`, `□` 단계로 흡수된다
(`text.headings_as_levels: false`로 끄면 제목 스타일을 따로 쓴다).

Confluence에서 바로 가져오려면 환경변수를 설정한다.

```bash
export CONFLUENCE_URL=https://회사.atlassian.net/wiki
export CONFLUENCE_USERNAME=me@company.com
export CONFLUENCE_API_TOKEN=xxxx
doc2report convert https://회사.atlassian.net/wiki/spaces/TEAM/pages/12345 -o 보고서.docx
```

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
