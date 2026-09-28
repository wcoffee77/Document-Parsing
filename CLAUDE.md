# doc2report 작업 노트

Confluence·Markdown 문서를 사내 규격 보고서(.docx)로 바꾸는 도구.
사용법은 [README.md](README.md)에 있고, 이 문서는 **코드만 봐서는 알기 어려운 판단 근거**를 적는다.

## 이 도구가 존재하는 이유

회사에서는 Confluence에 자유 형식으로 쓰고, 보고할 때 Word 규격 문서로 다시 만든다.
그 과정의 반복 작업(표를 A4에 맞추기, 개조식 문구 정리, 말머리·여백 정리)이 자동화 대상이다.

조사해 보니 md→docx 변환 자체는 검증된 도구가 많지만(pandoc 등), **표를 페이지 폭에 맞춰
열 너비와 글자 크기를 계산해 넣는 기능은 어디에도 없다.** pandoc은 페이지 폭을 몰라
표 너비를 제대로 쓰지 못한다는 이슈가 10년 넘게 열려 있다(jgm/pandoc#515, #1514, #7864).
그래서 `layout/`이 이 프로젝트의 핵심이고, 나머지는 검증된 라이브러리 조립이다.

## 설계 원칙 (어기면 나중에 아프다)

1. **서식 값은 코드에 없다.** 여백 mm, 글자 크기 pt, 글꼴명, 블릿 문자는 전부
   `profiles/*.yaml`에만 둔다. 사내 규격이 계속 바뀔 예정이라 코드를 고치지 않고
   대응할 수 있어야 한다. `tests/test_no_hardcoded_format.py`가 이를 강제한다
   (예외: `units.py`는 단위 변환이 본업, `profile_init.py`는 초안 생성기).
2. **IR이 단계 사이의 유일한 계약이다.** 입력이 늘면 `parsers/`만, 출력이 늘면
   `render/`만 추가한다. IR에는 치수·서식을 넣지 않는다(표 배치는 사이드 테이블).
3. **OOXML을 아는 코드는 `render/oxml.py`에만.** 자식 요소 순서를 어기면 Word가
   파일 열기를 거부하므로 `_ordered()`로 스키마 순서를 지켜 삽입한다.
4. **판단한 것은 사람에게 알린다.** 글자 크기를 낮췄거나 문구를 고쳤으면
   `--report`에 남긴다. 조용히 바꾸면 검수가 불가능해진다.

## 파이프라인

```
입력(.md / Confluence) → parsers → IR → transform(문구·구조) → layout(표·흐름) → render → .docx
```

- `layout/table_fit.py` — CSS 자동 테이블 레이아웃과 같은 방식. 셀별 min/max 폭을
  글꼴 메트릭으로 재고 비례 배분. 안 들어가면 글자 크기 → 셀 여백 → (허용 시) 가로 페이지
  순으로 사다리를 내려간다. `max_cell_lines`는 "폭은 맞지만 열이 1글자로 좁아져
  세로로 길어지는" 결과를 막는 장치다.
- `layout/flow.py` — 문서 높이를 어림해 쪽 수와 마지막 쪽 여백을 낸다.
  **넉넉한 값으로 바꿨을 때 늘어나는 양이 남은 공간에 들어갈 때만** 여유 모드를 켠다.
  어림 오차는 실측 기준 8mm 수준(company_format.md: 추정 37mm / 실제 29mm).
- `transform/stylize_ko.py` — 표에 없는 어미는 한글 자모를 합성해 처리한다
  (받침 없음 → ㅁ 추가: 진행하→진행함 / ㄹ 받침 → ㄻ: 만들→만듦 / 그 밖 → 음).
- `transform/structure.py` — 사내 보고서는 제목/본문이 따로 없고 `1.→□→-` 한 체계라
  마크다운 `##`/`###`를 이 체계로 접어 넣는다(`text.headings_as_levels`). Confluence
  제목은 이미 "1. 추진 배경"처럼 번호가 박혀 있는 경우가 흔해, 접기 전에 그 번호를
  떼어 낸다(안 그러면 "1.\t1. 추진 배경"처럼 겹친다) — 뗀 것도 Change로 남겨 --report에 보인다.
- `parsers/confluence_storage.py` — Confluence REST API가 주는 storage format(XHTML)을
  마크다운을 거치지 않고 곧장 IR로 읽는다. 마크다운 표 문법에는 병합 셀 표현이 없어서,
  한번이라도 마크다운을 거치면 rowspan/colspan이 사라진다 — Confluence는 표 폭 제약이
  없어 셀 병합을 자유롭게 쓰므로 이 경로가 핵심이다.

## 겪은 함정 (다시 밟지 말 것)

- **pydantic 재검증으로 단위가 두 번 변환된다.** 내부는 EMU인데 `FontSpec(**data)`로
  다시 만들면 "11pt"용 변환이 139700에 또 적용된다. 병합은 `model_construct`,
  덮어쓰기는 `model_copy`를 쓴다. `dump_profile`도 같은 이유로 pt/mm/%로 되돌려 쓴다.
- **바탕과 바탕체는 같은 파일(batang.ttc) 안의 다른 글꼴이고 폭이 다르다.**
  컬렉션에서 이름으로 골라야 표 폭 계산이 맞는다(`measure.py::_pick_face`).
- **서식 상속은 기본이 body다.** `table_header`가 `table`의 줄간격을 물려받게 하려면
  `inherit: table`을 명시해야 한다.
- **날짜의 마침표를 문장 끝으로 오인한다.** "2026. 9. 1."에서 문장이 잘렸다.
  `_SENTENCE_SPLIT`의 `(?<![0-9][.!?])` 가 그 방지책이다.
- docx는 길이를 twips로 저장하므로 되읽으면 **최대 635 EMU 오차**가 난다.
  테스트에서 정확히 같은지 비교하면 실패한다.
- **표 셀은 `<td>텍스트</td>`처럼 `<p>` 없이 바로 텍스트가 들어가기도 한다.**
  자식 요소만 훑으면(`_children_blocks`) 아무 자식이 없어 통째로 빈 문단이 된다 —
  실제로 걸렸던 버그다(`_cell_blocks`/리스트의 같은 패턴 참고). 표/리스트 새 파서를
  쓸 때는 꼭 "블록 자식이 하나도 없는 컨테이너"를 인라인으로도 읽어야 한다.
- **`python-docx`의 세로 병합(`rowspan`)은 아래 칸의 내용을 위 칸으로 옮겨 버린다**
  (`CT_Tc._span_to_width`가 `_move_content_to`로 그렇게 동작). 병합 *먼저*, 내용 채우기는
  *그 다음*이어야 한다 — 순서를 바꾸면 먼저 써 둔 내용이 사라진다.
  (`render/docx_writer.py::_fill_cells`는 이미 그 순서를 지킨다.)

## 검증 방법

```bash
uv run pytest                           # 81개
uv run python tools/score_corpus.py     # 표 폭 초과 0건이어야 함
```

이 PC에는 **MS Word가 설치되어 있어 실제 렌더로 검증할 수 있다.** 이게 가장 확실하다.

```powershell
$word = New-Object -ComObject Word.Application; $word.Visible = $false
$d = $word.Documents.Open("...\out\x.docx", $false, $true)
$d.ExportAsFixedFormat("...\out\x.pdf", 17); $d.ComputeStatistics(2); $d.Close(0); $word.Quit()
```
그 뒤 `pdfplumber`로 글자 좌표를 재면 여백·정렬·표 폭을 실측할 수 있다.
주의: Word 프로세스가 남아 파일을 잠그면 다음 변환이 PermissionError로 실패한다.

## 지금 상태와 다음 할 일

사내 서식(A4 세로, 바탕체 14pt, 1.→□→- 체계)은 `profiles/default.yaml`에 반영되어
있고 Word 실측으로 확인했다. **다음 세션에서 실제 사내 문서로 테스트하며 세밀 조정할 차례다.**

조정 후보(사용자가 범위만 주고 구체값은 잠정으로 정한 것):

| 값 | 현재 | 사용자가 준 범위 |
|---|---|---|
| 본문 줄간격 | 1.45 | 1.4 ~ 1.5 |
| 단계 전환 간격 | 6pt (여유 시 12pt) | 6 ~ 12pt |
| 새 절 앞 간격(`- ` 뒤 `2.`) | 14pt | 12pt 이상 또는 한 줄 |
| 표 뒤 간격 | 18pt | 18pt 이상 |
| 행 최소 높이 | 7mm (여유 시 10mm) | "답답하지 않게" |

## Confluence 연동 (2026-09-28 재작업)

`sources/confluence.py`가 더 이상 외부 `confluence-markdown-exporter` 바이너리에
의존하지 않는다. REST API(`GET /rest/api/content/{id}?expand=body.storage`)를
`httpx`로 직접 불러 storage format(XHTML)을 받고, `parsers/confluence_storage.py`가
그 XHTML을 마크다운을 거치지 않고 곧장 IR로 옮긴다 — 그래서 병합 셀(rowspan/colspan),
info/warning 패널, code 매크로가 살아남는다. 첨부 이미지는
`/rest/api/content/{id}/child/attachment`로 목록을 받아 파일명 그대로 내려받는다.

인증: `CONFLUENCE_USERNAME`이 있으면 Cloud로 보고 Basic(이메일+API 토큰), 없으면
Server/Data Center로 보고 Bearer(PAT)를 쓴다. 필요한 환경변수는 README 참고.

**아직 검증되지 않은 것 — 실제 사내 Confluence로 다음에 확인할 것:**

- 이 코드는 `tests/test_confluence_storage.py`(파서, 고정 XHTML 픽스처),
  `tests/test_confluence_source.py`(REST 클라이언트, `httpx.MockTransport`로 흉내),
  `tests/test_confluence_pipeline.py`(파서→변환→렌더 전 과정)로 검증했지만, 셋 다
  **실제 Confluence 서버를 흉내 낸 것**이다. 진짜 사내 인스턴스의 storage XHTML이
  여기서 다루지 않은 매크로(레이아웃, 특수 패널 등)를 쓰면 `_block()`의 "알 수 없는
  요소" 경로로 빠져 --report에 노트로만 남고 본문에선 빠진다 — 처음 몇 건은 리포트를
  꼭 확인해야 한다.
- 인증 방식 분기(Cloud/Server 판별을 USERNAME 유무로)가 실제 사내 Confluence 배포
  형태와 맞는지 확인 필요.
- **LLM 다듬기**(`--polish llm`)는 구현만 되어 있고 키 없이는 규칙 기반으로 폴백한다.
- 글꼴 선택지는 사용자 요청에 따라 **바탕체·맑은 고딕 둘로 한정**했다.
