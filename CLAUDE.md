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

- `layout/table_fit.py` — 셀별 min/max 폭을 글꼴 메트릭으로 잰다. **열 폭은 내용이 정한다**:
  머리행은 어절 하나 폭만 요구하고 자연 폭은 요구하지 않는다(값은 짧은데 제목만 긴 열이
  넓어지지 않게). 폭은 **수위 채우기**로 나눈다 — 남으면 좁은 열부터 같은 폭까지 올리고,
  모자라면 넓은 열부터 같은 폭으로 깎는다(열 크기를 비슷하게, 사용자 요청).
  안 들어가면 (크기, 장평) 조합을 **크기×장평이 덜 줄어드는 순**으로 내려간다
  (12pt·100 → 11pt·100 → 12pt·90 → 11pt·90; 12pt·90%가 11pt·100%보다 좁기 때문) →
  셀 여백 → (허용 시) 가로 페이지. 폭을 정한 뒤 머리가 `max_header_lines`를 넘으면
  `transform/abbreviate.py`가 `rules/abbreviations.yaml` 규칙으로 축약 후보를 만들고,
  결과는 `TableLayout.header_text`(사이드 테이블)로 렌더러에 넘어가 --report에 남는다.
  `max_cell_lines`는 "폭은 맞지만 열이 1글자로 좁아져 세로로 길어지는" 결과를 막는 장치다
  (머리는 축약으로 따로 다루므로 내용 셀만 센다).
- `layout/flow.py` — 문서 높이를 어림해 쪽 수와 마지막 쪽 여백을 낸다.
  **넉넉한 값으로 바꿨을 때 늘어나는 양이 남은 공간에 들어갈 때만** 여유 모드를 켠다.
  어림 오차는 실측 기준 8mm 수준(company_format.md: 추정 37mm / 실제 29mm).
- `transform/stylize_ko.py` — `text.noun_ending`이 켜져 있으면 먼저 **명사로 끝내기**를
  시도한다(`rules/endings.yaml`의 `noun_endings`): 끝말을 떼고 남은 마지막 단어가 명사면
  그 바로 앞 부사(`지속적으로`→`지속`)와 조사(`문제가`→`문제`)를 정리한다. 조사는
  **받침이 맞을 때만** 떼고(을·이는 받침 뒤, 를·가는 받침 없는 말 뒤) 떼서 한 글자가
  되면 안 뗀다 — `주가`, `사이`를 망가뜨리지 않기 위해. 명사로 못 끝내면("줄였습니다")
  기존 규칙대로 `~음`. 이 문체에서는 마침표를 붙이지 않는다.
  기존 규칙: 표에 없는 어미는 한글 자모를 합성해 처리한다
  (받침 없음 → ㅁ 추가: 진행하→진행함 / ㄹ 받침 → ㄻ: 만들→만듦 / 그 밖 → 음).
  **제목도 명사로 끝나야 한다**("추진 배경임" → "추진 배경", 2026-09-28 사용자 요청) —
  `Gaechosik.heading_noun_ending()`이 담당한다. 본문용 `convert()`와 달리 명사로 못
  줄이면 원문을 그대로 두고(본문처럼 억지로 "~음/~함"을 새로 붙이지 않는다), 서식이
  섞인 제목(굵게+링크 등)은 통째로 건드리지 않는다. `--polish llm` 프롬프트
  (`llm_polish.py::_SYSTEM`)도 같은 방향으로 맞춰 뒀다 — 예전 프롬프트가 "명사형으로
  끝낸다(~함/~임)"만 말해서, 규칙 기반이 이미 명사로 줄여 둔 문장을 LLM이 다시
  "~함"을 붙여 되돌리는 문제가 있었다(사용자가 "재설계함"으로 관찰, 원인 확정 후 수정).
- `transform/structure.py::merge_short_list_items` — 같은 단계의 짧은 항목이 연달아
  나오면 "및"으로 **둘씩만** 합친다(2026-09-28 사용자 요청, `text.merge_short_items` +
  `max_sentence_chars` 재사용). 셋 이상 잇지 않는다 — "A 및 B 및 C"는 "및"이 반복돼
  어색하고 개조식의 스캔 가독성도 해친다. `fold_headings_into_levels`보다 **먼저**
  돌아야 한다(안 그러면 제목도 ListItem이 되어 소제목이 그 아래 항목과 잘못 합쳐질
  수 있다) — `attach_table_notes`와 같은 이유다.
- `transform/structure.py::attach_table_notes` — 표 바로 뒤 인용문과 `*`/`※`로 시작하는
  문단을 `Table.notes`로 옮긴다. **제목 접기보다 먼저** 해야 한다(안 그러면 □ 항목으로
  접힌다). 렌더러는 표 바로 아래 `* ` + `fonts.table_note`(10pt)로 쓰고, 표 뒤 간격(18pt)은
  주석 다음 블록이 가져간다.
- `transform/structure.py` — 사내 보고서는 제목/본문이 따로 없고 `1.→□→-` 한 체계라
  마크다운 `##`/`###`를 이 체계로 접어 넣는다(`text.headings_as_levels`). Confluence
  제목·항목은 이미 "1. 추진 배경", "ㆍ입사예정"처럼 말머리가 박혀 있는 경우가 흔해, 접을 때
  그 말머리를 `ListItem.marker`로 옮겨 **원문 그대로** 쓰고 프로파일 말머리는 안 붙인다
  (`text.keep_leading_markers`, 2026-09-29 사용자 원칙). keep을 끄면 예전처럼 떼고 프로파일
  말머리로 통일하며 뗀 것은 Change로 남는다. 안 하면 "1.\t1. 추진 배경"처럼 겹친다.
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
- **기본 템플릿을 `.docx` 파일로 두면 `Package not found at '...\\default_template.docx'`로
  죽는다** — 사내 PC에서 두 번 겪음(2026-09-29). 처음엔 python-docx 설치 안의
  `docx/templates/default.docx`가 "없어졌다"고 보고 저장소에 사본(`assets/default_template.docx`)을
  넣었는데, 그 사본도 같은 에러가 났다. 저장소의 파일은 멀쩡했다(38,116바이트, 올바른 zip,
  git도 바이너리 처리) — python-docx의 이 에러는 파일이 **없을 때뿐 아니라 zip으로 못 읽을
  때**도 나므로, 사내 문서보안/백신이 `.docx`를 가로채 손상시킨 것으로 추정한다(확정은 못 함).
  원인이 무엇이든 통하도록 `.docx` 파일을 아예 두지 않는다: 템플릿을 base64 텍스트로
  `render/base_template.py`에 넣고 `docx_writer.py::_base_template()`이 `BytesIO`로 연다
  (`profile.template`이 있으면 그 경로). `assets/`는 없앴고 `.gitattributes`에 `*.docx binary`.
  **출력 .docx는 어쩔 수 없이 파일이라 같은 보안 프로그램이 건드릴 수 있다** — 출력이
  안 열리면 이쪽을 의심할 것.
- **git pull 뒤 웹 화면이 반쯤 깨짐(서식 목록이 비고, 직접 선택의 체크박스가 안 그려지고, 빨간 "서버와
  연결하지 못했습니다" 알림이 5초 떴다 사라짐)** — 2026-09-29 사용자 PC. 원인은 **예전 서버 프로세스**:
  서버 창을 닫지 않은 채 pull하면 예전 파이썬 코드가 새 화면 파일(static/은 요청마다 디스크에서 읽음)을
  내보내고, 새 화면이 기대하는 API 필드(`schema.presets` 등)가 없어 초기화가 중간에 멈춘다. 게다가
  **Windows의 SO_REUSEADDR(파이썬 HTTPServer 기본값)는 이미 쓰는 포트를 또 잡게 해** 새 서버가 "정상
  시작"처럼 보여도 요청이 예전 서버로 갈 수 있다. 예전 서버 코드 + 새 화면 파일 조합으로 재현해 증상이
  똑같음을 확인했다. 대응(`web/server.py`): Windows는 `SO_EXCLUSIVEADDRUSE`로 포트를 독점 → 포트가 쓰이면
  확실히 실패 → 그게 doc2report(버전 있음)면 `/api/shutdown`으로 끄고 넘겨받고, 예전 버전이면 창을 닫으라고
  안내하고 종료. 화면은 `API_VERSION`(server.py·app.js 둘 다 — 테스트가 일치를 강제)이 다르면, 서버가 켜진 뒤
  코드가 바뀌었으면(`stale`, 파일 수정 시각 지문) 계속 떠 있는 안내 띠로 알린다. **API 형식을 바꾸면
  `API_VERSION`을 두 곳 모두 올릴 것.** profiles/에 망가진 yaml이 있어도 그 서식만 빼고 보여 준다.

## 검증 방법

```bash
uv run pytest                           # 284개
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
있고 Word 실측으로 확인했다. 온프렘 LLM 연동(`thinkingcap`)도 사내 PC에서 끝까지
검증 완료했다(아래 절 참고, 순서는 [docs/onprem-first-run.md](docs/onprem-first-run.md)).
**다음은 실제 사내 문서·Confluence 페이지로 세밀 조정할 차례다.**

조정 후보(사용자가 범위만 주고 구체값은 잠정으로 정한 것):

| 값 | 현재 | 사용자가 준 범위 |
|---|---|---|
| 본문 줄간격 | 1.45 | 1.4 ~ 1.5 |
| 단계 전환 간격 | 6pt 고정 (2026-09-28 사용자 확정, 여유 시 늘리지 않음) | 6pt |
| 새 절 앞 간격(`- ` 뒤 `2.`) | 14pt | 12pt 이상 또는 한 줄 |
| 표 뒤 간격 | 18pt | 18pt 이상 |
| 행 최소 높이 | 7mm (여유 시 10mm) | "답답하지 않게" |

2026-09-28 사용자 확정값: 문단 왼쪽 맞춤, □ 들여쓰기 0.4cm / - 0.8cm (· 1.2cm는 같은
간격으로 잠정), 표 글자 11~12pt + 장평 90%, 표 주석 `* ` 10pt, 명사 종결(제목 포함),
짧은 항목 "및" 병합(둘씩만).

**브랜치가 두 개로 갈라져 있었다가(서식 수정 vs 온프렘 LLM 연동) 2026-09-28에
`claude/confluence-document-conversion-dtygn4`로 합쳤고, 이후 사용자 요청으로
`main`을 이 브랜치까지 fast-forward해 2026-09-29부터는 `main` 하나로 작업한다.**
**지금부터 모든 작업은 `main`에 직접 커밋·푸시한다** — 더 이상 다른 브랜치를 새로
안 만든다.

같은 종류의 혼란이 한 번 더 있었다: 사내 PC의 로컬 체크아웃이 여전히
`claude/confluence-document-conversion-dtygn4`(그것도 옛 커밋)에 남아 있어서,
`git pull`이 `origin/main`은 갱신해도(그 출력만 보고 최신인 줄 착각) 실제
작업 디렉터리(체크아웃된 브랜치)는 하나도 안 바뀐 채로 계속 옛날 코드를
돌리고 있었다(2026-09-29). `git checkout main && git pull origin main`으로
해결. **다음에 이 PC에서 이상하게 "고친 게 반영 안 됨"이 또 나오면 제일 먼저
`git branch -vv`로 지금 어느 브랜치에 체크아웃돼 있는지부터 확인할 것** —
`git log -1`만 보면 마치 최신인지 옛날인지 헷갈릴 수 있다.

**2026-09-29 사내 PC 실측으로 확인 완료**: `main`을 pull해서 `doc2report convert`
정상 동작, Confluence REST API로 실제 페이지를 불러와 처리하는 것까지 확인됨.
문구 다듬기(`stylize_ko`/`llm_polish`) 결과를 실제 Confluence 문서로 테스트하다가
아래 두 가지 실제 버그를 발견·수정함.

**버그 1 — 원문에 이미 있는 말머리와 프로파일 말머리가 겹침**: 이 조직 Confluence는
제목·항목 앞에 `1.→□→-` 체계를 **문자로 직접 타이핑**해 둔 경우가 흔하다(Word에서
넘어온 습관으로 보임). 접을 때 프로파일이 그 단계의 말머리를 또 매기면 "ㅁㅁ
채용진행현황"(□+□), "- - 입사확정"(-+-)처럼 겹쳐 나왔다. `profiles/default.yaml`의
`text.leading_markers`(당시 이름 `strip_leading_markers`)에 적힌 문자가 (뒤에
공백을 두고) 제목·항목 맨 앞에 있으면 접기 전에 뗀다(`structure.py::
fold_headings_into_levels`). "-5%p 개선"처럼 공백 없이 바로 숫자가 오면 음수로
보고 손대지 않는다 — 말머리는 항상 뒤에 공백이 있다는 전제.
그 김에 딸려 나온 두 번째 버그: `split_long()`(문장 길이 초과 시 항목을 나누는
로직)이 `_SENTENCE_SPLIT`으로 ". 입사예정시기"를 [".", "입사예정시기"]로 쪼개
빈 항목("□\t.")을 따로 만들고 있었다 — 글자 없이 문장부호만 있는 조각은 문장으로
안 보고 옆 조각에 붙이게 고침(`_merge_punct_only_parts`). "." 를 말머리로 쓰는
케이스를 테스트하다가 발견함 — 겪은 함정 절의 "날짜 마침표" 버그와 사촌 격.

**버그 2 — 표 셀 안 여러 줄이 한 줄로 뭉개짐**: Confluence 표 셀은 `<p>` 없이
`텍스트<br/>텍스트<br/>텍스트`처럼 `<br>`만으로 줄을 나누는 경우가 흔한데,
`confluence_storage.py`의 `_inline()`이 `<br>`를 공백 하나로 접어서 세 줄이
"사진1사진2사진3"처럼 한 문단으로 합쳐졌다. `<br>`를 줄 경계로 보는
`_inline_lines()`를 새로 만들어 `<p>`/셀의 bare-text 경로 모두 줄마다 별도
`Paragraph`를 만들게 바꿨다 — 표 셀은 이미 여러 `Paragraph`를 여러 줄로 렌더링하는
경로가 있어서(병합 셀 버그 수정 때 만든 것) 안전하게 재사용됨. (top-level 문단의
`<br>`는 그대로 공백 처리 — 흔치 않고, Markdown 쪽 `softbreak`/`hardbreak`도 아직
공백 처리라 굳이 이번에 같이 안 건드림.)

**2026-09-29 두 번째 라운드 — 같은 방식으로 더 발견된 문제들:**

- **말머리 제거가 `runs[0]`만 보고 있었다.** `_strip_existing_marker`가 첫 번째
  run의 텍스트만 검사해서, 말머리와 그 뒤 공백이 서로 다른 run에 걸치는 경우
  (드물지만 실제로 있었던 듯) 놓칠 수 있었다. `plain(runs)`로 이어 붙인 전체
  텍스트로 판단하고, 매치된 글자 수만큼 여러 run에 걸쳐 정확히 떼어내는
  `_drop_prefix()`로 바꿨다.
- **표 위 꺾쇠 제목("[사업현황]")도 "-" 항목이 되고 있었다.** `attach_table_notes`가
  표 **뒤** 주석을 빼내는 것과 대칭으로, `attach_table_captions`가 표 **앞**
  꺾쇠 문단을 `Table.caption`으로 옮긴다. `text.table_captions`로 켠다(기본 `true`).
- **표 셀 크기·정렬 조정 1차**: `tables.font_ladder`를 `[12pt, 11pt]`→
  `[12pt, 11pt, 10pt, 9pt]`로 늘리고 `max_cell_lines`를 4→3으로 낮춤. 내용이
  `max_cell_lines`줄 이상인 셀은 왼쪽 맞춤으로(`_left_align_long_cells`,
  `TableLayout.cell_align`).

**2026-09-29 세 번째 라운드 — 1·2차 수정이 실제로는 부족했던 부분:**

- **가운뎃점이 여전히 안 떨어짐 (미해결 가능성 있음).** 1차에서 `·`/`ㆍ`/`‧`/`∙`/`•`를
  넣었지만 사용자가 실측한 문자는 **U+318D(ㆍ, 호환용 자모) 또는 U+119E(ᆞ, 옛
  아래아 입력기가 넣는 자모 영역 글자)** — 둘 다 화면엔 거의 똑같이 보이지만
  다른 코드다. U+318D는 이미 있었지만 **U+119E는 빠져 있어서 추가함**
  (`profiles/default.yaml::text.leading_markers`). `fold_headings_into_levels`에
  직접 두 문자를 넣고 확인한 단위 테스트와, 마크다운 전체 파이프라인(`convert()`)
  으로 두 문자 각각 실제로 떨어지는 것까지 확인함(`tests/test_structure.py::
  test_all_middle_dot_lookalikes_are_stripped`). **그래도 여전히 안 떨어지면
  실제 문자가 이 두 개와도 다른 것** — 그땐 `--report`에 남는 원문 텍스트를
  그대로 받아 정확한 코드를 확인해야 한다(추측으로 후보만 계속 늘리는 건
  한계가 있음).
- **표 제목 꺾쇠가 사라지고 있었다 — 원인은 내가 브래킷을 벗겨서 저장한 것.**
  1차 구현이 "[사업현황]" → `Table.caption = "사업현황"`처럼 꺾쇠를 **떼고**
  저장했는데, 사용자는 꺾쇠(예: 【…】, U+3010/U+3011)를 그대로 유지하되
  그 앞에 붙던 "-"만 없애 달라는 것이었다. `attach_table_captions`가 이제
  원문을 그대로(꺾쇠 포함) `Table.caption`에 넣도록 수정 — 렌더러는 그
  앞에 "<표 N> "만 붙이므로 최종적으로 "<표 1> 【사업현황】"처럼 나온다.
- **셀 글자 크기가 여전히 안 줄어듦 — `max_cell_lines` 검사 자체의 허점.**
  표 전체 폭/크기를 정하는 `_max_cell_lines()`는 "셀 안 **가장 긴 한 줄**이
  폭 때문에 몇 줄로 쪼개지는지"만 본다(원래 목적: 열이 1글자로 좁아지는 것
  방지, "겪은 함정" 아님, 설계 의도). 그런데 `<br>`/여러 문단으로 줄이 많은
  셀(2026-09-29 첫 라운드에 고친 그 케이스)은 **각 줄 자체는 짧아서** 이
  검사에 전혀 안 걸린다 — 그래서 1차에서 사다리를 9pt까지 늘려도 실제로는
  한 번도 작동을 안 한 것. 표 전체를 다시 줄이는 대신(다른 멀쩡한 셀까지
  작아짐) **그 셀 하나만** 줄이는 `_shrink_long_cells()`를 새로 만들었다 —
  셀의 총 줄 수(모든 줄의 wrap 합)를 세어 `max_cell_lines`를 넘으면, 표
  전체보다 작은 (크기, 장평) 후보 중 큰 것부터 시도해 맞는 걸 그 셀에만
  적용한다(`TableLayout.cell_font` 사이드 테이블, `header_text`/`cell_align`과
  같은 패턴). 하드 브레이크로 줄 수 자체가 고정된 셀(문단이 6개면 폰트를
  아무리 줄여도 6줄인 건 안 바뀜)은 사다리의 가장 작은 값(9pt·90%)에서 멈춘다.

**폭 배분 비대칭 문제는 여전히 손 안 댐** — 한 줄짜리 짧은 셀과 여러 줄짜리
긴 셀이 있을 때 "글자 수 비례"로 폭을 나누면 짧은 셀이 필요 이상으로 넓어지고
긴 셀은 좁아지는 문제. `column_demands`/`_cap_down`/`_fill_up`(수위 채우기)
자체를 바꿔야 해서 다른 모든 표에 영향을 줄 위험이 커 계속 보류 중이다.
이번에 만든 **셀별 글자 크기 축소**가 긴 셀의 줄 수 부담을 어느 정도 줄여주므로
(같은 폭에 9pt로 더 많은 글자가 들어감), 실측해서 그래도 폭이 이상하면 그때
water-filling 쪽을 구체적 수치와 함께 다시 요청할 것.

**2026-09-29 네 번째 라운드:**

- **가운뎃점 "-" 중복은 사용자가 "더 고치기 어려우면 그냥 둘 것"이라고 해서
  보류.** U+318D/U+119E를 넣었는데도 여전히 재현된다는 뜻은 실제 문자가 이
  둘과도 다르다는 것인데, 후보를 추측만으로 계속 늘리는 건 한계가 있다.
  **재개하려면 `--report`의 정확한 원문(before) 텍스트가 필요.**
- **표 제목 "<표 N>" 접두어 제거 + 원본 정렬 유지.** 3차에서 "꺾쇠는 유지"까지는
  고쳤지만 "<표 1> " 접두어와 강제 가운데 정렬은 그대로였다 — 이번에 "<표 N> "
  자체를 없애 꺾쇠 문단 원문 그대로만 나오게 하고, `Paragraph.align`(IR에 새로
  추가, `Cell.align`과 같은 성격)로 원문의 `style="text-align:..."`(Confluence
  편집기가 정렬 버튼을 누르면 넣는 값)을 읽어 `Table.caption_align`으로 그대로
  가져간다. 명시적 정렬이 없으면(대부분의 경우) 프로파일 `caption` 폰트의
  기본 정렬(가운데)을 그대로 쓴다. **`apply_text_rules`의 `_rebuild()`가
  `Paragraph`를 새로 만들 때 `align`을 안 챙기고 있어서 캡션 기능이 죽을
  뻔했다** — 문구 다듬기가 캡션 판별보다 먼저 도는 순서라(`attach_table_captions`
  이전에 `apply_text_rules`가 옴) 꼭 짚어야 했던 부분.
- **표 하나 안에서 글자 크기 차이가 너무 크면 불균형해 보인다는 지적** (12pt
  표에 바쁜 셀만 9pt로 줄어든 사례) — `tables.max_font_spread`(기본 2pt)를
  넘으면 표 전체 크기를 낮춰 차이를 좁힌다(`_balance_table_font`). 12pt 표에
  9pt 셀이 있으면 표 전체가 11pt로 내려가 12·9가 아니라 11·9가 된다. 이미
  폭에 맞던 값을 더 작게만 바꾸는 것이라 다시 맞춰 볼 필요는 없다.
- **표 머리행 음영을 옅은 회색(R242,G242,B242 = `F2F2F2`)으로 확정** —
  기존 `D9D9D9`보다 밝다. `tables.header_shading`만 바꾸면 되는 순수 프로파일
  값이라 코드 변경 없음.

**2026-09-29 다섯 번째 라운드 — Confluence는 규칙이 다르다 (사용자 규칙 3가지):**

1. **원문 글머리 기호는 바꾸지 않는다**(모든 문서 공통 원칙). 지금까지는 원문 말머리를
   **떼고** 프로파일 말머리로 통일했는데(strip), 이제 기본이 **keep**이다
   (`text.keep_leading_markers: true`). `fold_headings_into_levels`가 원문 말머리를
   `ListItem.marker`(IR 새 필드)로 옮기고, 렌더러는 이 값이 있으면 프로파일 말머리 대신
   그대로 쓴다(`"ㆍ\t입사예정"` — 탭·들여쓰기는 단계 서식 그대로라 줄이 맞는다). 제목
   아래 일반 문단이면 그 말머리가 가리키는 단계(`numbering[].marker` + 새 `aliases`)로
   둔다 — "-"는 - 단계, "ㆍ"는 · 단계. 번호 단계({n})의 카운터는 원문 번호가 있어도 세어
   둬서 뒤의 자동 번호가 어긋나지 않는다.
   **가운뎃점 미해결 건의 유력한 원인도 여기서 나옴**: 예전 패턴은 말머리 **뒤에 공백**을
   요구했는데 한국어 문서는 `ㆍ입사예정`처럼 붙여 쓰는 경우가 흔하다. 이제 ASCII 기호
   ("-", ".")만 공백을 요구하고(음수·소수 오인 방지), 그 밖의 기호는 붙여 써도 잡는다
   ("○○팀" 같은 자리표시자는 같은 기호가 연달아 오면 제외). 번호 패턴도 두 자리로
   제한해 "2026. 9. 1. 기준"을 번호로 오인하지 않게 했고, "가." "나)" "(다)"도 번호로 본다.
2. **Confluence 문장은 다듬지 않는다** — `profiles/confluence.yaml`의 `text.polish: none`
   (`TextRules.polish` 새 필드, CLI `--polish`를 안 주면 이 값을 씀). 개조식·명사 종결·
   문장 분리·"및" 병합·LLM 모두 꺼진다.
3. **내용 많은 문서는 제목 16pt·본문 12pt·표 11~9pt** — `confluence.yaml`.

`confluence.yaml`은 `extends: default`로 **바뀌는 값만** 적는다(프로파일 상속을 새로 만듦 —
`profile.py::_read_profile_data`). **검증 전의 YAML dict끼리** 합쳐야 한다 — 검증된
모델을 합치면 EMU 값이 다시 변환되는 "겪은 함정"을 또 밟는다. dict는 키별로 합치고
목록(numbering, font_ladder)은 통째로 덮어쓴다. Confluence URL이면 `-p` 없이도 이
프로파일이 자동 선택된다(`pipeline.py::auto_profile`).

**(해결됨, 열 번째 라운드)** 원문 말머리가 없는 제목·문단의 프로파일 말머리는 `text.auto_markers`로 끈다.

**2026-09-29 여섯 번째 라운드 — Confluence 실측에서 나온 것들:**

- **빈 "□" 줄** ("1. ㅇㅇㅇ" 다음에 "□"만 덜렁 찍히고 그 아래 "(1) ㅇㅇㅇ"): Confluence는
  들여쓰기를 하려고 **글자 없는 `<li><ol>…</ol></li>` 껍데기**를 만든다. `_list()`가 이 껍데기도
  ListItem으로 만들어 프로파일 말머리 "□"만 출력했다. 이제 글자·이미지 없는 항목은 만들지 않고
  안쪽 목록은 그 깊이 그대로 둔다. (사용자 문서의 실제 XHTML을 못 봐서 재현으로 원인을
  추정한 것 — **그래도 남으면 그 부분 XHTML이 필요**.)
- **표 안 굵은 글씨가 14pt + 위에 빈 줄**: 셀에 `<h3>` 같은 제목 블록이 있으면 렌더러가 본문용
  제목 서식(14pt·앞 간격)으로 그렸고, 첫 블록이 문단이 아니면 python-docx가 만들어 둔 **빈 첫
  문단이 지워지지 않아** 엔터가 한 줄 들어간 것처럼 보였다(원인이 둘). `_fill_cell`이 셀 안 제목은
  표 글자 크기의 굵은 문단으로, 셀 안 목록은 표 글자 + `tables.cell_list_markers`("-", "·") 말머리로
  그리고(예전엔 본문 12pt + "1." 번호 체계였다), 남은 빈 첫 문단은 `_drop_leading_blank`로 지운다.
- **왼쪽 정렬은 열 단위**: 셀마다 따로 정하면 같은 열에서 정렬이 섞여 보인다. 본문 셀 중 하나라도
  `max_cell_lines`줄 이상이면 그 열의 본문 셀 전부 왼쪽(머리행 제외, 병합 셀은 자기만 판단,
  저자가 정한 `cell.align`은 존중).
- **※는 본문보다 2pt 작게**: `text.note_marks: ["※"]` + `text.note_size_delta: 2pt`. 원문 말머리
  (`ListItem.marker`)가 ※이거나 문단이 ※로 시작하면 적용. 표 바로 아래 주석(`fonts.table_note`)과는
  별개. 값이 EMU라 `dump_profile`에서 `_pt()`로 되돌려 쓴다(안 하면 다시 읽을 때 이중 변환).
- **장평 90% → 95%** (`tables.char_scale_ladder`). 사다리 순서가 바뀐다: 11pt·95%(10.45)가
  10pt·100%보다 먼저 온다.

**2026-09-29 일곱 번째 라운드:**

- **빈 "□" 줄이 또 나옴 — 진짜 원인은 "보이지 않는 글자".** 여섯 번째 라운드의 빈 `<li>` 껍데기 수정은
  일부만 맞았다. 재현해 보니 `<p>`에 **제로폭 공백(U+200B)·한글 채움문자(U+3164)** 만 든 "빈 줄"이나
  **빈 제목**이 접힐 때 프로파일 말머리만 덜렁 찍혔다. `str.strip()`은 U+200B(분류 Cf)와 U+3164(Lo)를
  공백으로 안 봐서 "글자 있음"으로 통과했던 것 — 한국어 문서(Confluence·메신저 복사)는 빈 줄을 이런
  글자로 채우는 일이 흔하다. `ir.py::is_blank()`(공백 + Cf/Cc/Zs/Zl/Zp + 채움문자)와
  `structure.py::drop_blank_blocks()`가 접기 전에 제목·문단·항목 중 글자가 없는 것을 뺀다.
  **원인을 알 수 있게, 보이지 않는 글자가 든 경우엔 `--report`에 코드(`U+200B`)를 남긴다**
  (`빈 항목 제거`). 앞으로 이 줄이 리포트에 보이면 그 문서에 그런 글자가 있었다는 뜻.
- **들여쓰기 기준: 맨 처음 단계는 0cm**(`text.normalize_levels: true`). 문서가 `###`(h3)부터
  시작하면 첫 문장 "1. ㅇㅇㅇ"이 □ 단계(0.4cm)로 나왔다. 접은 뒤 가장 얕은 단계를 0으로 당긴다 →
  첫 문장 0cm, 그 아래 0.4cm, 그 아래 0.8cm. (`-`·`ㆍ` 같은 원문 말머리로 단계를 정하는
  `marker_depths`는 절대 단계 기준이라, 당기기 전에 계산된 뒤 같이 당겨진다 — 말머리 단계와
  제목 단계가 엇갈리는 문서에서 어색하면 이 부분을 다시 볼 것.)
- **표 전체는 오른쪽 정렬**(`tables.align: right`). 셀 안 글자 정렬(`fonts.table`)과는 별개.
- **장평은 100% 고정, 글자 크기만 줄인다**(`tables.char_scale_ladder: [100%]`). 90%도 95%도 보기
  안 좋다는 사용자 판단. 장평 기능은 남겨 뒀다(프로파일에 `[100%, 95%]`를 넣으면 다시 쓴다).

**2026-09-29 여덟 번째 라운드:**

- **원문에 없던 굵은 글씨가 생김 — 원인은 `numbering[].bold`.** 프로파일의 `1.`·`□` 단계는
  `bold: true`이고 렌더러(`_list_item`)는 이를 말머리가 아니라 **그 항목 문장 전체**에 적용한다.
  Confluence는 제목 아래 일반 문단도 `headings_as_levels` 때문에 □ 단계 항목이 되고, 원문 말머리가
  `1.`이면 0 단계가 되어, 굵지 않던 문장이 통째로 굵게 나왔다. `text.level_bold`(기본 true =
  사내 규격 그대로)를 새로 두고 `confluence.yaml`에서 false로 끈다. 끄면 굵은 글씨는 **원문에서
  굵던 run**과 **제목에서 접힌 항목**(`ListItem.from_heading`, IR 새 필드)뿐이다. `_rebuild`·
  `_merge_items`가 `from_heading`을 챙기지 않으면 조용히 사라지니 ListItem을 새로 만들 때 주의.
- **표 글자 크기도 열 단위**(`table_fit.py::_unify_column_fonts`): 정렬과 같은 원칙. 열에 줄인 셀이
  하나라도 있으면 그 열의 본문 셀 전부가 그 열의 가장 작은 크기를 쓴다(머리행·병합 셀·다른 열 제외).
  `_balance_table_font`(표 전체 ↔ 가장 작은 셀 2pt 차이) 보다 **먼저** 돌고, 표 크기가 내려가
  표 크기와 같아진 셀 값은 `_drop_redundant_cell_fonts`가 뺀다. `--report`에 "열 N: 글자 크기를
  Xpt로 열 전체 통일"이 남는다.

**2026-09-29 아홉 번째 라운드:**

- **꺾쇠로 시작하는 줄에는 프로파일 말머리를 안 붙인다**(모든 문서 공통). "【사업현황】"이 표 위
  제목이 아니라 일반 줄이면 접기에서 □ 항목이 되어 "□【사업현황】"이 됐다. `text.no_marker_openers`
  (`[ ［ 【 〔 〈 《 「 『`)로 시작하면 `fold_headings_into_levels`가 `ListItem.marker = ""`(빈 문자열)을
  준다 — **`None`(=프로파일 말머리)과 `""`(=말머리 없음)는 다른 뜻**이다. 렌더러는 `""`이면 말머리·탭을
  안 쓰고 내어쓰기도 0으로 둬 첫 줄과 다음 줄이 맞는다. 번호 단계의 자동 번호도 세지 않는다(`_marker`).
  keep 여부와 무관하게 적용. (표 바로 위 꺾쇠 제목은 이전 그대로 `Table.caption`.)
- **※ 문단은 윗줄 문단보다 +0.4cm 더 들여쓴다**(`text.note_indent: 4mm`). 렌더러가 마지막 ※가 아닌
  문단의 들여쓰기를 `_base_indent`로 기억하고, ※ 문단(`ListItem`이든 `Paragraph`든)은 그 값 + 0.4cm.
  ※가 연달아 나오면 계단식이 되지 않고 같은 들여쓰기를 쓴다(기준은 ※ 바로 위의 "일반" 문단).
  제목이 나오거나 들여쓰기 없는 일반 `Paragraph`가 나오면 기준은 0으로 돌아간다. 표 셀 안은 해당 없음.

**2026-09-29 열 번째 라운드:**

- **말머리 자동 부여를 옵션으로**: `text.auto_markers`(default true, confluence false). false면 원문에
  말머리가 없는 **제목·일반 문단**은 `ListItem.marker = ""`(말머리 없음, 단계별 들여쓰기만 유지)로 접힌다.
  진짜 목록(`<ul>/<ol>`)의 항목은 대상이 아니다(구조가 이미 있는 것). 사용자 판단: 대부분의 문서는
  말머리를 이미 구분해 써 뒀으니 새로 만들 필요가 없고, **정리 안 된 글을 정형 보고서로 새로 만들 때만**
  말머리 생성(`auto_markers: true`, `-p default`) + LLM 다듬기(`--polish llm`)가 필요하다. 웹앱 변환
  옵션의 on/off 항목으로 넣을 예정 — 이미 프로파일 값이라 체크박스가 이 값을 덮어쓰기만 하면 된다.
  (두 값이 별개라는 점 주의: 말머리 생성 = `text.auto_markers`, 문장 다듬기 = `text.polish`.)
- **가운뎃점 앞 `-` 중복은 사라진 것으로 확인**(사용자, 다섯 번째 라운드의 keep 방식 이후). 다시 나오면
  `--report` 원문이 필요.
- **`--report`에 "httpx 요청이 SSL/연결 오류로…" 안내가 이미지 개수만큼 반복됨**: 페이지·첨부 목록·
  첨부파일마다 httpx 실패 → PowerShell 재시도를 했기 때문. 한 번 막히면 `client`에 표식을 달아 나머지
  요청은 httpx를 건너뛰고 PowerShell로 곧장 가며 안내는 한 번만 남긴다(변환도 그만큼 빨라짐).
  이미지가 든 Confluence 페이지의 첨부 다운로드 경로는 사용자 실측으로 검증됨.

## Confluence 연동 (2026-09-28 재작업)

`sources/confluence.py`가 더 이상 외부 `confluence-markdown-exporter` 바이너리에
의존하지 않는다. REST API(`GET /rest/api/content/{id}?expand=body.storage`)를
`httpx`로 직접 불러 storage format(XHTML)을 받고, `parsers/confluence_storage.py`가
그 XHTML을 마크다운을 거치지 않고 곧장 IR로 옮긴다 — 그래서 병합 셀(rowspan/colspan),
info/warning 패널, code 매크로가 살아남는다. 첨부 이미지는
`/rest/api/content/{id}/child/attachment`로 목록을 받아 파일명 그대로 내려받는다.

인증: `CONFLUENCE_USERNAME`이 있으면 Cloud로 보고 Basic(이메일+API 토큰), 없으면
Server/Data Center로 보고 Bearer(PAT)를 쓴다. 필요한 환경변수는 README 참고.

사내 PC에서 처음 연결할 때 그대로 따라 하는 절차는
[docs/confluence-first-run.md](docs/confluence-first-run.md)에 정리해 뒀다
(`scripts/confluence_env.example.ps1`/`.sh` 템플릿 포함, 실제 토큰이 든 복사본은
`.gitignore`에 있어 커밋 안 됨).

**겪은 버그**: `page_id_from_url`이 Server/DC의 고전 URL 형식
(`/pages/viewpage.action?pageId=123456`)을 못 잡고 있었다 — 정규식이 `/pages/`
뒤에 숫자가 바로 오는 형태(`/pages/123456`, Cloud 형식)만 잡았기 때문이다.
Server/DC 사용자가 이 형식으로 URL을 넣으면 페이지 ID 대신 URL 전체가
REST 경로에 들어가 404가 났을 것 — 실제 사내 인스턴스로 시도하기 전에
가이드 문서를 쓰다가 코드를 다시 보고 발견해 고쳤다(2026-09-28). 이제
못 알아보는 URL(단축 링크 등)은 조용히 엉뚱한 요청을 보내는 대신 바로
명확한 에러를 낸다.

**API 토큰 승인 완료, REST 연결 확인됨(2026-09-29).** `CONFLUENCE_URL`은 실제로
`http://api.confluence.samsungds.net/rest/api/`(REST 전용 게이트웨이, 브라우저
위키 주소와 다른 서브도메인)로 확인됐다.

**사내망에서 httpx가 403으로 막히는 문제 발견·대응**: 같은 사내 PC에서 다른
에이전트(CodeMate/Roo)가 Confluence 페이지를 읽다가, httpx 요청은 403으로
거부되고 PowerShell의 `Invoke-WebRequest`(원시 바이트 스트림을 UTF-8로 디코딩)는
통과하는 걸 확인했다. **원인은 확정하지 못했다** — 그 에이전트는 "사내 커스텀
인증서 문제"라고 진단했지만, httpx가 SSL 에러가 아니라 정상적인 HTTP 403 *응답*을
받았다는 점에서(TLS 신뢰 실패라면 애초에 응답까지 못 갔을 것) 사내 보안
게이트웨이가 요청 형태(User-Agent 등)로 판별해 차단했을 가능성도 있다. 원인을
추측해 httpx 쪽을 계속 고치는 대신 **검증된 경로를 그대로 재현**했다:
`sources/confluence.py`가 httpx로 403을 받으면 Windows에서만 자동으로
PowerShell(`subprocess` + `Invoke-WebRequest -UseBasicParsing`, 바이너리 안전을
위해 Base64로 주고받음)로 한 번 더 시도하고, 성공하면 --report에 남긴다.
`DOC2REPORT_CONFLUENCE_TRANSPORT=powershell`로 처음부터 강제할 수도 있다.
PowerShell 스크립트 자체는 **이 세션(Linux 샌드박스)에서 실행해 볼 수 없어서
Windows에서 실제로 검증된 적은 아직 없다** — Python 쪽 분기·재시도·오류 처리
로직만 `tests/test_confluence_source.py`에서 `subprocess.run`을 흉내 내 검증했다.

**두 번째 문제, SSL 인증서 검증 실패 발견·대응 (2026-09-29)**: 위 403 우회를 넣은
뒤 실제로 돌려 보니 이번엔 httpx가 **응답조차 못 받고 SSL 인증서 검증 실패로
바로 죽었다** — 위에서 "403은 정상 HTTP 응답이라 TLS 신뢰 실패는 아닐 것"이라고
썼던 추측이 이 두 번째 증상에는 안 맞고, 사내 LLM 진단(사내 프록시가 자체 CA로
HTTPS를 중계하는데 그 루트 인증서가 파이썬 기본 CA 번들 certifi엔 없음)이 이
증상과는 정확히 들어맞는다. 즉 **두 문제가 서로 다른 요청/시점에 겹쳐 있었을
가능성이 크다** — 하나의 원인으로 둘 다 설명하려던 게 성급했다. 대응:
1. `_ssl_verify()`가 `CONFLUENCE_CA_BUNDLE`/`REQUESTS_CA_BUNDLE`/`SSL_CERT_FILE`
   환경변수(이 순서로 확인)에 있는 인증서 파일을 `httpx.Client(verify=...)`에
   직접 넘긴다 — **httpx는 requests와 달리 `REQUESTS_CA_BUNDLE`을 자동으로 안
   읽으므로** 이 확인이 없으면 방법 A(사내 LLM이 추천한 방법)가 애초에 안 먹힌다.
2. `_get()`이 이제 `httpx.TransportError`(SSL 실패 포함)도 403과 나란히 잡아서
   Windows에서 PowerShell로 재시도한다 — SSL 실패는 응답이 아니라 예외로 오므로
   403과는 별도 분기가 필요했다(`_fetch_via_powershell`의 `httpx_error` 인자).

**아직 검증되지 않은 것 — 실제 사내 Confluence로 다음에 확인할 것:**

- ~~PowerShell 대체 경로 자체가 실제 Windows에서 동작하는지~~ →
  **2026-09-29 실측으로 검증 완료.** `--report`에 "httpx 요청이 SSL/연결 오류로
  실패해 PowerShell(Invoke-WebRequest)로 재시도해 성공함"이 그대로 찍혔다 —
  즉 이 사내망에서는 실제로 SSL 실패가 나고, `_fetch_via_powershell`의
  `httpx_error` 분기(403이 아니라 예외로 잡는 경로)가 타서 PowerShell 대체가
  정상 동작해 페이지를 받아 왔다. 헤더 해시테이블 리터럴 문법, 토큰 이스케이프는
  이걸로 검증됨. (처음에 "바로 성공했음"으로 잘못 전달돼 이 절에 반대로 적었다가
  `--report` 원문 확인 후 정정.) **여전히 미확인**: 이 실측 문서에는 첨부 이미지가
  없어서, 첨부파일 다운로드 경로(PowerShell로 바이너리 응답을 Base64로 왕복하는
  부분)는 이번에도 확인 못 함 — 이미지가 있는 페이지로 다시 확인 필요.
  **추가 확인(2026-09-29, 사용자 재확인)**: 이 SSL 실패 → PowerShell 재시도가
  **매번(변환할 때마다) 일어난다** — 가끔 겹치는 우연이 아니라, 이 사내망
  프록시가 발급하는 인증서가 httpx(Python 기본 CA 번들)에 구조적으로 안 맞는
  것으로 확정. 결과물은 정확히 같이 나오지만 매번 httpx가 실패할 때까지 기다린
  뒤 PowerShell 프로세스를 새로 띄우는 시간이 더 든다. 사용자에게 두 가지
  줄이는 방법을 안내함: (1) `DOC2REPORT_CONFLUENCE_TRANSPORT=powershell`로
  처음부터 강제(httpx 시도 자체를 건너뜀), (2) IT/보안팀에서 사내 루트 인증서
  파일을 받아 `CONFLUENCE_CA_BUNDLE`로 지정(httpx가 아예 바로 성공, PowerShell
  우회 자체가 필요 없어짐) — 아직 어느 쪽을 택할지는 미정.
- 이 코드는 `tests/test_confluence_storage.py`(파서, 고정 XHTML 픽스처),
  `tests/test_confluence_source.py`(REST 클라이언트, `httpx.MockTransport`로 흉내),
  `tests/test_confluence_pipeline.py`(파서→변환→렌더 전 과정)로 검증했지만, 셋 다
  **실제 Confluence 서버를 흉내 낸 것**이다. 진짜 사내 인스턴스의 storage XHTML이
  여기서 다루지 않은 매크로(레이아웃, 특수 패널 등)를 쓰면 `_block()`의 "알 수 없는
  요소" 경로로 빠져 --report에 노트로만 남고 본문에선 빠진다 — 처음 몇 건은 리포트를
  꼭 확인해야 한다.
- 인증 방식 분기(Cloud/Server 판별을 USERNAME 유무로)가 실제 사내 Confluence 배포
  형태와 맞는지 확인 필요.
- 첨부 이미지 다운로드 경로(`_links.download`)가 REST 게이트웨이 호스트와 다를 수
  있어 응답의 `_links.base`를 우선 쓰도록 방금 고쳤는데, 실제 응답에 그 필드가
  있는지·값이 맞는지 확인 필요.
- 글꼴 선택지는 사용자 요청에 따라 **바탕체·맑은 고딕 둘로 한정**했다.

**확인 완료(2026-09-29)**: 실제 Confluence 페이지 URL로 `doc2report convert`를 돌려
`.docx`까지 나오는 것까지 사내 PC에서 검증됨. **다음에 할 일**: 실제 문서로 문구
다듬기(개조식 변환·LLM polish) 결과가 괜찮은지 세밀 확인 — 사용자가 진행 중이며
아직 구체적 문제는 보고되지 않음. 위 "아직 검증되지 않은 것" 목록(레이아웃 매크로,
인증 방식 분기, 첨부 이미지 경로)은 여전히 미확인 상태.

**연결 페이지 한 번에 불러오기 (2026-09-29 사용자 요청)** — "본문 하나만 넣으면 매크로로 붙여 +로
펼쳐 보게 해 둔 페이지까지 한 번에 변환". 파서와 네트워크를 떼어 두려고 두 단계로 나눴다.
- `parsers/confluence_storage.py`는 네트워크를 모른다: `include`/`excerpt-include`/`children`/`pagetree`/
  `view-file` 계열을 만나면 **자리표시 블록 `PageRef`**(IR 밖, 파서 모듈 안의 dataclass)를 남긴다
  (`keep_refs=True`일 때만). 기본값(False)이면 `drop_page_refs`가 "…을(를) 불러오지 않음" 노트로 바꿔
  빼므로 **PageRef가 렌더러까지 새는 일은 없다** — 다른 호출자(테스트·예전 경로)는 그대로.
  `excerpt_only=True`는 `excerpt` 매크로 몸통만 읽는다(발췌 포함용). `expand`는 이제 제목 파라미터를
  굵은 문단으로 앞에 넣는다(펼치기 제목이 사라지면 어떤 내용이 붙었는지 알 수 없어서).
- `sources/confluence.py::LinkedPages`가 PageRef를 REST로 풀어 블록으로 바꾼다: 제목 검색
  `/rest/api/content?title=&spaceKey=`(스페이스 지정 없으면 **그 매크로가 있던 페이지의 스페이스**),
  하위 페이지 `/child/page?expand=body.storage,space`, 첨부는 기존 첨부 목록 경로. 불러온 페이지도
  같은 방식으로 다시 풀고(재귀), 이미지는 `out_dir/<page id>/`에 받아 경로를 절대 경로로 고정한다.
  **상한 `MAX_LINKED_PAGES=40`, `MAX_LINK_DEPTH=4`, 방문한 id 집합으로 순환 차단.** 표 칸 안의 PageRef는
  "(포함 페이지 '제목')" 문단으로만 바꾼다 — 표 안에 페이지 전체를 넣으면 표 폭 계산이 무의미해진다.
- `pipeline.load_document(linked=True, progress=)`, CLI `--no-linked`, 웹 `#cf-linked`(옵션 `linked`).
- **실제 사내 Confluence로 확인 못 한 것**: 제목 검색 API가 사내 게이트웨이에서 되는지, `space` expand가
  오는지, 하위 페이지 순서가 화면의 순서(수동 정렬)와 같은지(REST 기본은 position 순으로 알려져 있으나
  **확인 필요**), 사용자의 "+" 구성이 실제로 `expand`+`include`인지 `children`인지. 사용자가 말한
  "책갈피"가 **앵커 링크나 일반 페이지 링크(`<ac:link>`)라면 지금은 따라가지 않는다** — 링크는 본문
  일부가 아니라 참조라서 일부러 뺐다. 필요하면 그 페이지 storage XHTML을 받아 판단할 것.

- **(같은 날, 사용자 질문 "책갈피 매크로도 반영되나")** — 책갈피 = `anchor` 매크로는 **위치 표시일 뿐 내용이
  없다**(다른 페이지를 붙이지 않음). 그래서 불러올 것은 없는데, 확인하다 **진짜 버그 세 개**가 나왔다:
  ① 인라인으로 읽을 때 매크로의 **매개변수 글자가 본문에 새어 나옴** — 제목 안 책갈피 이름("sec11. 제목"),
  상태 표시 색("Green완료"). 이제 인라인 매크로는 매개변수를 건너뛰고 `status`는 제목만(`_inline_macro_label`).
  ② **문단(`<p>`)·목록 항목 안에 든 페이지 포함 등 블록 매크로가 통째로 사라짐** — 편집기가 매크로를 문단 안에
  넣는 일이 흔하다. `_is_block_macro`로 골라 `_split_paragraph`가 앞뒤 글과 매크로를 나누고, `_list`도 항목
  뒤에 붙인다. ③ **표 칸에 `글 + 상태 표시`가 있으면 칸이 비어 버림** — `_cell_blocks`가 모든 매크로를 블록으로
  봐서 앞 글을 버렸다. 이제 블록 매크로만 블록으로 본다. 덤으로 보이는 글자 없는 `<ac:link>`는 대상 페이지
  제목을 쓰고(Confluence 화면과 같게), 책갈피는 "지원하지 않는 매크로" 노트를 더 남기지 않는다.

- **본문 링크·책갈피 따라가기 (`follow_links`, 사용자 확인 "책갈피 = 앵커")** — 이 조직은 다른 페이지의
  **책갈피(앵커)로 가는 링크**로 문서를 이어 둔다. 파서가 블록마다 그 안의 `<ac:link><ri:page/></ac:link>`를
  `PageRef("link", anchor=…)`로 **그 블록 바로 뒤에** 남기고(`_children_blocks`의 `_link_refs` — 매크로 안은 안
  본다: 페이지 포함의 매개변수도 같은 모양이고, 본문 있는 매크로는 제 본문을 읽을 때 센다. 표 칸은 `links=False`,
  칸의 링크는 표 뒤에 한꺼번에), `LinkedPages`가 `follow_links`일 때만 푼다. 책갈피가 있으면
  `parse_confluence_storage(anchor=)`→`_anchor_section`이 **그 책갈피가 든 블록부터 다음 같은 급 이상 제목
  전까지**만 읽는다(책갈피가 제목 안이면 그 제목 급, 아니면 다음 제목 전까지; 앵커 매크로 이름이 없으면 같은
  글자의 제목 — Confluence 제목 앵커; 둘 다 없으면 페이지 전체 + 노트). 같은 페이지의 다른 책갈피는 따로
  넣을 수 있게 방문 기록을 (페이지, 책갈피)로 따로 둔다(`sections`). 같은 페이지 안 책갈피 링크(ri:page 없음)는
  내용이 이미 본문에 있어 무시. **기본은 끔**(CLI `--follow-links`, 웹 "본문 링크·책갈피가 가리키는 내용도
  불러오기") — 참고용 링크(규정·타 팀 문서)까지 끌려 오기 때문. 끄면 link PageRef는 **노트 없이** 뺀다(링크마다
  노트를 남기면 리포트가 넘침). 사내 문서로 확인 못 한 것: 실제 링크의 `ac:anchor` 값이 앵커 매크로 이름과
  같은 형태인지(Confluence가 "페이지제목-앵커"로 저장하는 판이 있다는 말이 있음 — **확인 필요**, 안 맞으면
  `--report`의 "책갈피 '…'를 찾지 못해" 노트로 드러난다).
  **(2026-09-30) 사용자 실측: 링크 옵션 없이도 붙은 문서가 다 불러와짐 → 사용자의 "+" 구성은 매크로(페이지
  포함 등)였다. 화면 체크박스는 뺐고 코드·CLI `--follow-links`만 남겼다**(쓸 일이 생기면 화면에 한 줄로 되살림).

- **불러온 문서는 새 쪽 + 문서 제목 (2026-09-30 사용자)** — `LinkedPages._page_blocks(new_page=)`가
  `[PageBreak, Heading(page_title=True, 페이지 제목), …내용]`을 돌려준다(`_new_page`). 대상: 페이지 포함·하위 페이지·
  책갈피 없는 링크·첨부 Word(제목 = 문서 제목 또는 파일 이름). **조각은 그 자리**: 발췌 포함·책갈피 구간·패널(Callout)
  안(`inline=True`). 펼치기(+) 안이 연결 문서뿐이면 파서가 펼치기 제목을 `PageRef.label`로 넘기고 굵은 줄을 안
  만든다 — 새 쪽에 페이지 제목이 붙으니 겹치고, 안 그러면 제목 한 줄이 앞 쪽 끝에 홀로 남는다. 조각이거나
  못 불러오거나 불러오기를 끄면(`drop_page_refs`) label을 굵은 줄로 되살린다. 본문이 곧바로 연결 문서로 시작하면
  첫 쪽이 문서 제목만 남지 않게 맨 앞 PageBreak를 뺀다. `page_title`은 원래 "입력마다 새 쪽" 합치기용이라
  `_insert_dateline`이 쪽 제목마다 날짜를 달았는데, **문서 제목이 있으면(=연결 문서의 쪽 제목) 날짜는 맨 앞에만**.
  알려진 한계: 불러온 문서 뒤에 본문이 이어지면 그 본문은 불러온 문서의 마지막 쪽에 이어 붙는다(새 쪽 아님).

- **표 폭 = 윗줄 문장의 왼쪽 끝 ~ 오른쪽 여백 (2026-09-30 사용자)** — `table_fit.table_indents`가 표마다 바로
  윗줄의 첫 줄 시작점을 잰다: 말머리 항목은 `numbering_level(depth).indent`(렌더러 `set_list_indent`가 첫 줄을
  거기서 시작 — 말머리 자리), 제목·일반 문단은 0, ※ 참고 줄은 기준에서 뺀다(윗줄보다 더 들여 쓴 부속 줄).
  `plan_tables`가 `usable − indent` 폭으로 맞추고(`TableLayout.indent`), 오른쪽 정렬(`tables.align: right`)이라
  왼쪽 끝이 그 시작점에 온다. **표 제목(caption)도 같은 left_indent** — 가운데 정렬 제목은 표 폭의 가운데에 온다.
  또 `_stretch_to`가 안전 여유(safety_margin 3%)로 남던 폭을 열에 비율대로 돌려줘 표가 폭을 끝까지 쓴다(열이
  넓어질 뿐이라 줄바꿈은 안 는다; 가로 쪽·강제 축소 표 제외). LibreOffice PDF 실측: □ 뒤 표 24.0~190.0mm(□ 24.0),
  - 뒤 표 28.0~190.0mm(- 28.0), 제목 뒤 표 20.0~190.0mm. **Word 실측은 아직** — jc=right 표의 오른쪽 테두리가
  여백선에 정확히 붙는지 사내 PC에서 볼 것.

- **(2026-09-30) 본문이 전부 굵게 나옴** — 재현: 웹 "직접 선택"에서 규칙 기본값을 '보고서'로 두면
  `level_bold`(1.·□ 문장 전체 굵게, 보고서 규격)가 Confluence 원문 줄에도 걸렸다. 두 겹으로 막음: ① 렌더러는
  **도구가 말머리를 붙인 항목(`marker is None`)에만** level_bold를 적용 — 원문 말머리 줄·말머리 없음("")은 원문
  굵기 ② `web/options._original_bold`: 입력에 Confluence·Word가 있으면 규칙과 상관없이 level_bold를 끈다
  (도구가 붙인 □ 줄까지 원문 굵기 — 사용자 원칙 "원문에서 굵은 글씨만 굵게"). 제목에서 접힌 항목은 계속 굵다.
- **쪽 제목의 "(첨부 1)" 제거** — `text.page_title_strip`(정규식 목록, default.yaml) + `structure.clean_page_titles`
  (drop_blank_blocks 직후). 쪽 제목(`page_title`)만 대상, 떼고 빈 제목이면 그대로. 리포트에 "쪽 제목 번호표 제거".

## 온프렘 LLM 연동 (검증 완료 — thinkingcap)

**LLM 다듬기 온프렘 연동**(`--polish llm` + `DOC2REPORT_LLM_BASE_URL`)은 사내 PC에서
실제 온프렘 모델(`thinkingcap`, OpenAI 호환)로 끝까지 검증 완료됐다. 응답 문자열 정상,
`<think>` 블록 없음, `rule='LLM'`로 실제 다듬어짐 확인함(`docs/onprem-first-run.md` 참고).
다만 이 PC의 `HTTP_PROXY`가 사내 Squid로 요청을 우회시켜 목적지를 차단하는 문제가 있어
`NO_PROXY` 환경변수로 우회 중 — 네트워크팀에 정식 프록시 예외 등록 요청 필요(임시 조치임).
또한 규칙 기반이 LLM보다 먼저 실행되므로, 문장이 이미 완벽하면 `--report`에 "LLM" 행이
하나도 안 남을 수 있다(정상 동작, 오작동 아님).

**오프라인 설치**(인터넷이 막힌 사내망): `uv sync` 대신 `wheelhouse` zip을 받아
`uv pip install`로 설치하는 절차를 `docs/onprem-first-run.md`에 정리해 뒀다.
`uv run` 뒤에 붙이는 플래그는 **반드시 하이픈 두 개**(`--offline --no-sync`)여야 한다 —
하이픈 하나(`-offline`)로 쓰면 uv가 그걸 `-o -f -f -l -i -n -e`처럼 한 글자씩 쪼개
해석하다 "unexpected argument" 에러를 낸다(2026-09-28 실제로 겪음). `--report`,
`--polish`, `--date` 등 doc2report 자체 옵션도 마찬가지로 하이픈 두 개.

## 웹 화면 (2026-09-29 구현 — `doc2report web`, `start_webapp.bat`)

사용자 요청: 입력 3종(Confluence 여러 페이지·Word 첨부·글 붙여넣기)을 **한 문서로 합쳐** 변환,
출력은 docx 기본 + pdf/md, 화면에서 눌러 열기, 저장 폴더에 이름 안 겹치게, 지금까지의 규칙을
옵션으로(특히 LLM on/off·날짜·말머리 만들기), 자동 판단/직접 선택 두 모드.

**설계 판단**
- **웹 프레임워크 없이 표준 라이브러리(`http.server`)** — 사내 PC는 wheelhouse로 오프라인 설치라
  패키지가 늘면 wheelhouse를 다시 만들어 옮겨야 한다. 화면도 CDN 없이 `web/static/`의 HTML/CSS/JS만
  (사내망에서 CDN 차단). Python 3.13에서 `cgi`가 없어져 multipart 대신 **업로드는 파일 바이트를 그대로
  POST**(`X-Filename` 헤더, URL 인코딩).
- **정적 파일 Content-Type은 직접 지정**(`_STATIC_TYPES`) — Windows는 레지스트리에 따라 `.css`/`.js`를
  `text/plain`으로 추측해 브라우저가 스타일을 버릴 수 있다.
- **보안**: 127.0.0.1에만 연다(토큰이 서버 환경변수에 있음). POST는 `X-Doc2Report: 1` 헤더 필수 —
  다른 사이트가 브라우저로 몰래 보내는 단순 요청을 막는다(사용자 정의 헤더는 CORS 사전 요청이 필요).
  파일 열기·내려받기는 저장 폴더 **바로 아래** 파일만(`App.output_file`).
- **옵션 = 프로파일 값**: 체크박스는 `web/options.py`의 목록(`MARKER_TOGGLES` 등)이 원본이고 화면은
  `/api/profiles`로 받아 그린다. 값은 `model_copy`로 덮어쓸 뿐이라 옵션을 늘릴 때 변환 코드 분기가 없다.
  글꼴·크기는 **프로파일 기본값과 다른 것만** `with_overrides`에 넘긴다(같은 값을 넘겨도 `font`가 모든
  글꼴을 덮어쓰는 부작용이 있어서).
- **자동 판단**(`auto_decide`): 두 축을 따로. 정리 정도(제목·말머리가 있는 문단 비율 ≥ 30%, 또는
  Confluence 포함 → confluence의 text 규칙 = 원문 유지, 아니면 default 규칙 = 말머리 생성 + 다듬기,
  LLM은 "허용" + 설정돼 있을 때만) × 분량(3,000자·표 3개·입력 2개 이상 → confluence 글자 크기).
  두 프로파일을 `fonts 쪽.model_copy(text=text 쪽.text)`로 조합 — 서식 값을 코드에 안 쓰려고.
- **작업은 백그라운드 스레드**(`web/jobs.py`) — Confluence(PowerShell 우회)·LLM·PDF가 수십 초. 화면이
  0.6초마다 진행 메시지를 물어 간다. PDF 실패는 작업 실패가 아니다(docx는 남기고 메모).
- **파일 이름**: `YYYYMMDD_제목`, docx·pdf·md·`_변경내역.md`·`_files/` 중 하나라도 있으면 `_2`…
  (한 작업의 파일이 같은 줄기를 쓰게). 동시에 두 작업이 같은 이름을 고르지 않도록 잠금 + 예약.
  "최근 결과"는 메타데이터 없이 폴더를 줄기별로 묶어 보여 준다.
- **열기**: Windows는 `os.startfile`(docx→Word), 폴더는 `explorer /select,`.

**입력 확장 (웹 화면용으로 파이프라인에 추가 — CLI도 같이 쓴다)**
- `pipeline.load_document` / `merge_documents` / `convert_document`로 나눔. `convert()`는 그대로 둔
  얇은 래퍼. 여러 입력은 **절 제목**(`Heading.section_title`, IR 새 필드)으로 이어 붙이고, 제목 접기가
  그 아래 모든 단계를 한 칸 민다(`fold_headings_into_levels`의 `base`). 합칠 때 제목 수준을 직접
  바꾸면(h2→h3) 원문 말머리(□ -)로 정하는 단계와 어긋나서 이렇게 했다. 부작용: 합친 문서에서는
  프로파일 말머리도 한 단계 밀린다(□ 자리에 -). "절 제목 넣기"를 끄면 원래 단계.
- **Word 입력**(`parsers/docx_reader.py`): 고수준 API 대신 XML을 본문 순서대로(문단·표·내용 컨트롤).
  Word "제목(Title)" = 문서 제목, Heading N = IR N+1(Markdown ##와 맞춤). 자동 번호는 numbering.xml로
  **화면에 보이던 말머리를 다시 만들어** `ListItem.marker`에(원문 말머리 유지). Symbol/Wingdings 글머리
  (PUA 문자)는 버리고 프로파일 말머리. 병합 셀은 gridSpan/vMerge로. 머리행은 `tblHeader` 또는 첫 행
  전체 음영. 제목 스타일이 없으면 가운데 정렬·굵은 첫 줄을 제목으로(우리 출력도 이 모양이라 되읽기 가능).
  **DRM이 걸린 .docx는 zip이 아니라서 못 읽는다** — 업로드 때 `PK` 시그니처로 걸러 "Word에서 열어
  붙여넣기"를 안내한다.
- **붙여넣은 글**(`parsers/plaintext.py`): 한 줄 = 한 문단(Markdown은 빈 줄 없는 줄을 합쳐 버림).
  줄 앞 `- ` `1. `은 **글쓴이가 친 말머리**라 Markdown 목록으로 안 읽히게 이스케이프(목록으로 읽히면
  프로파일 말머리로 바뀜). `2026. 9. 29`도 Markdown에선 번호 목록(최대 9자리)이라 같이 이스케이프.
  탭으로 나뉜 줄 2줄 이상 = 엑셀 표 → Markdown 표. `#`·`|---|`·``` 가 있으면 Markdown으로 보고 그대로.
- **제목 없이 말머리만 있는 문단도 단계로**: 예전엔 제목 아래 문단만 접었다. 이제 제목 전이라도
  원문 말머리(`1.`→0, `□`→1, `-`→2)가 있으면 그 단계 항목이 된다(붙여넣은 글·Confluence 모두).
- **완전히 정리 안 된 메모**: 제목도 말머리도 전혀 없고 `auto_markers`가 켜져 있으면 문단마다
  `text.plain_paragraph_level`(default 1 = □) 항목으로. 날짜 줄(`ir.DATE_LINE`, 렌더러에서 옮김)·꺾쇠·※는 제외.
- **출력**: `render/markdown_writer.py`(말머리는 글자로, 단계는 전각 공백 — 보통 공백 4칸은 코드 블록이 됨),
  `render/pdf.py`(docx를 Word COM(PowerShell)으로, 없으면 LibreOffice). PDF를 따로 그리지 않는 이유는
  Word 결과와 똑같아야 해서. **Word COM 경로는 이 샌드박스에서 못 돌려 봤다**(LibreOffice 경로만 실측).

**아직 확인 못 한 것(사내 PC에서 볼 것)**: Word COM PDF 변환, `os.startfile` 열기, `start_webapp.bat`
(UTF-8 BOM ps1 + `-ExecutionPolicy Bypass`), 사내 DRM이 출력 docx를 잠근 뒤 Word COM이 열 수 있는지.

**서식 preset (2026-09-29 두 번째 요청)** — 출력 설정에서 1) 보고서(최초 사내 규격 = default.yaml)
2) Confluence 변환(위·아래 2.0cm, 좌·우 1.5cm, 제목 16pt, 본문 12pt, 맑은 고딕, 줄간격 1.25배 =
confluence.yaml을 이 값으로 바꿈 — CLI의 Confluence 변환도 같이 바뀐다) 3) 사용자 설정(자유).
- preset = `preset_order`가 있는 프로파일(`label`이 화면 이름). **새 서식은 yaml 한 장 추가로 목록에 뜬다.**
- **서식과 규칙을 분리**: preset은 글꼴·크기·여백·줄간격·표 사다리만, 말머리·다듬기(`text.*`)는 자동 판단 또는
  직접 선택. 최종 프로파일 = preset 프로파일에 규칙 text를 끼운 것(`options.build_profile`). 그래서
  자동 판단은 더 이상 글자 크기를 바꾸지 않고, 내용이 많은데 보고서 서식이면 Confluence 변환을
  **권하기만** 한다(사용자가 고른 서식을 조용히 바꾸지 않음). 직접 선택의 "규칙 기본값 불러오기"는
  체크박스를 그 프로파일의 text 값으로 채우는 버튼일 뿐이다.
- 사용자 설정: 출발 서식 + 바꾼 값만 `with_overrides`(여백은 cm 네 칸 → "위,아래,좌,우"). 값을 못 읽으면
  작업 오류로 안내. 화면은 datalist로 선택지를 보여 주되 자유 입력 허용.
- confluence.yaml은 body에 글꼴을 주면 제목·표·날짜가 물려받는다(각 서식에 eastAsia가 없으므로).

**옵션 정리 (2026-09-29 세 번째 요청 — "체크박스가 불필요하게 많다")**
- 화면에서 뺀 규칙(값은 "규칙 기본값" 프로파일을 그대로 씀): 제목을 1.→□→- 단계로 접기(`headings_as_levels`),
  맨 바깥 단계 0cm(`normalize_levels`), 1.·□ 문장 전체 굵게(`level_bold` — 보고서 true, Confluence false),
  표 위 【…】를 표 제목으로(`table_captions`). 사용자가 "원문 말머리 그대로 쓰기와 제목 접기가 충돌하지
  않느냐"고 물었다 — 충돌 아님: 제목 접기는 제목 줄을 **어느 단계(들여쓰기)에 둘지**, 원문 말머리 유지는
  그 줄 앞에 **어떤 기호를 찍을지**다. 그래도 사용자가 고를 일이 아니라 뺐다.
- 직접 선택의 규칙은 서식(preset)이 아니라 **"규칙 기본값" 프로파일의 text**에 체크박스를 덮어쓴다
  (`manual_rules` — 화면에 없는 규칙도 그 프로파일을 따르게).
- "개조식 어미"와 "명사로 끝내기"는 한 체크박스(`endings` → `gaechosik`+`noun_ending`). 토글은
  (화면 키, 이름, 설명, 바꾸는 text 필드들)로 정의해 한 체크박스가 여러 값을 바꿀 수 있다.
- **LLM과 파이썬 규칙 분리**: 문장 다듬기 = 파이썬 규칙(안 함/적용), LLM = 따로 켜는 "맞춤법·표현·어조
  다듬기"(자동·직접 두 모드 공통). `convert_document(llm=...)`로 규칙 없이 LLM만도 된다(CLI `--polish llm`은
  예전처럼 규칙 + LLM). **LLM 프롬프트를 교열 역할로 바꿈**(`llm_polish._SYSTEM`): 맞춤법·띄어쓰기·정식
  어조·모호한 표현 — **문장 끝 형태는 그대로**(명사형에 "~함"을 붙이던 예전 문제를 프롬프트에서 막음),
  없는 사실·수치는 만들지 않음. 제목에서 접힌 항목은 보내지 않는다.
- **여러 입력 합치기**: 이어 붙이기(입력 제목 = 절 제목) / 입력마다 새 쪽. 새 쪽이면 쪽마다 입력 제목을
  `Heading.page_title`(IR 새 필드)로 넣고 렌더러가 **문서 제목 서식**(큰 글씨·가운데·밑줄)으로 쓴다. 이때 문서
  전체 제목은 안 쓰고(쪽마다 독립 보고서처럼), "문서 제목" 칸은 파일 이름·제목 없는 첫 입력의 쪽 제목에만
  쓴다. 날짜 줄도 쪽 제목마다 그 아래에(`_insert_dateline`). 제목 접기는 쪽 제목에서 단계를 처음부터.
- **쪽 나눔을 "다음 문단의 쪽 나눔 앞"으로 바꿈**(`_break_before`): 나눔 문자를 넣은 빈 문단을 쓰면 새 쪽
  맨 위에 빈 줄이 생겨 쪽 제목이 맨 위에 붙지 않는다. 다음 블록이 표면 예전 방식.
- 사용자 설정의 값 칸: datalist는 **값이 들어 있으면 그 값으로 목록을 걸러서** 화살표를 눌러도 안 펼쳐졌다
  (사용자 보고) → select + 맨 끝 "직접 입력…"(고르면 입력칸이 나옴)으로 바꿈.

**Confluence 변환 서식 재확정 (2026-09-29 네 번째 요청)** — 여백 위·아래·좌·우 모두 2cm, 맑은 고딕,
제목 18pt 가운데·밑줄, 본문 12pt·**장평 95%**·줄간격 1.0·단락 앞뒤 0pt, 표 10pt·**장평 80% 고정**(글씨가
많아도 9pt로 줄이지 않음 — `font_ladder: [10pt]`, `char_scale_ladder: [80%]`라 셀별 축소·표 전체 축소
후보가 하나도 없다). 앞선 "16pt·1.5cm·1.25배"는 이 값으로 대체됐다.
- **본문 장평을 제목·날짜·캡션이 물려받지 않게** 그 서식들에 `char_scale: 100%`를 명시했다 — 서식 상속은
  body 기준이라 안 적으면 제목도 95%가 된다(겪은 함정 "서식 상속은 기본이 body다"의 변형).
- **단락 앞뒤 0pt는 말머리 단계에도** — numbering 목록은 상속 시 통째로 덮어써져서 간격만 바꾸려고 목록을
  복사하면 기호·들여쓰기가 두 벌이 된다. 그래서 `numbering_all:`(모든 단계에 덮어쓸 값)을 새로 만들었다
  (`profile._apply_numbering_all`, 합친 뒤·검증 전 dict 단계). 표 뒤 간격(`tables.space_after` 18pt)과
  제목·날짜 뒤 간격은 "단락"이 아니라 그대로 뒀다 — 사용자가 원하면 confluence.yaml에서 0으로.
- 사용자 설정에 **본문 장평·표 장평** 칸 추가(`with_overrides(body_scale=, table_scale=)`; 표 장평은 사다리를
  한 값으로 고정). "95"처럼 %를 빼고 적어도 95%로 읽는다. `with_overrides(table_size=)`가 같은 크기를 사다리에
  두 번 넣던 것(`[10pt, 10pt]`)도 고쳤다.

**앞으로 (사용자 계획, 2026-09-29)**: 최종적으로 **팀원 여러 명이 쓰도록 공개**할 예정 — 한 번에 하지 않고
하나씩. 그때 바꿔야 할 것(아직 안 함): ① 지금은 127.0.0.1 전용·한 사람의 Confluence 토큰을 서버
환경변수로 씀 → 사용자별 토큰(각자 입력·세션 보관) 또는 서비스 계정, 로그인 ② 저장 폴더·최근 결과를
사용자별로 분리, 작업 목록(`JobRunner.jobs`)도 사용자별·오래된 것 정리 ③ 동시 변환 수 제한(LLM·Word COM은
동시 실행에 약함 — 특히 Word COM은 한 번에 하나), ④ 설치형(각자 PC) vs 공용 서버 중 선택 — 설치형이면
지금 구조 그대로 배포 절차만 만들면 된다. **변환 규칙은 완벽하지 않고 사용하면서 계속 고칠 예정**
(사용자) — 규칙은 계속 프로파일 값 + 작은 transform 함수로 추가하고, 화면 옵션은 `options.py` 목록에
한 줄 넣는 방식을 유지할 것.

**사용자 등록·토큰 보호 (2026-09-30, 팀 공유 1단계 — 설치형)** — 사용자: "git 주소를 공유해 각자 쓰게 하려 한다.
개인 Confluence 토큰·온프렘 LLM은 각자 넣고, 화면 위에 누구의 토큰·어떤 API인지 보여야 한다(도용 방지)."
**공용 서버가 아니라 각자 PC 설치형**을 택했다 — 토큰이 남의 PC·서버에 모이지 않고, 지금 구조(127.0.0.1 단일 사용자)를
그대로 쓴다.
- `account.py`: 등록 정보는 **사용자 폴더**(`%APPDATA%\doc2report\account.json`, `DOC2REPORT_HOME`으로 바꿈)에,
  토큰·API 키는 **DPAPI**(ctypes, CurrentUser + 엔트로피)로 봉인. Windows 밖(개발용)은 "plain:" base64 + chmod 600,
  화면에 "파일 권한만(암호화 없음)"으로 표시. 변환 코드는 그대로 환경변수를 읽고 `apply()`가 등록 값을 서버 프로세스
  환경변수에 넣는다(스크립트 값보다 우선, 등록 삭제 시 켤 때 값으로 복원 — `_ORIGINAL_ENV`). CLI `convert`도
  시작할 때 `load_and_apply()`. 비밀 칸을 비우고 저장하면 예전 값 유지, 토큰이 바뀌면 주인 확인을 다시 한다.
- **토큰 주인 확인**: 저장 때 `confluence_whoami()`(`/rest/api/user/current`)로 Confluence가 아는 표시 이름을 받아
  화면 위에 "홍길동 (hong.gd)의 토큰 …abcd"로 보인다. 등록 이름이 그 안에 없으면 노란 경고. Server/DC는 틀린 토큰에
  401 대신 **익명 사용자**로 답하기도 해서 그 경우도 실패로 본다. (사내 게이트웨이에서 이 API가 열려 있는지 **미확인**.)
- **서버 잠금**(web/server.py): ① **접속 열쇠** — `access.key`(사용자 폴더, 재시작해도 같은 값)를 `/?k=`로 받은
  브라우저에만 쿠키(`d2r_key_<port>`, HttpOnly·SameSite=Strict·30일)를 주고, 쿠키 없으면 화면만 보이고 API는 401
  (`/api/status`는 `{version, locked}`만 — 예전 서버 인계 확인용, `/api/shutdown`은 인계 때문에 열쇠 없이 허용).
  같은 PC의 다른 Windows 사용자·다른 프로그램이 내 서버로 내 토큰을 쓰는 것을 막는다. ② **Host 확인** —
  루프백으로 열었으면 Host가 127.0.0.1/localhost/::1이 아닌 요청은 403(DNS 리바인딩: 기존 X-Doc2Report 헤더 검사는
  같은 출처가 된 리바인딩을 못 막는다). `create_server(access_key=None)`은 열쇠 검사를 안 한다 — 테스트용,
  `serve()`는 항상 켠다. **API_VERSION 7.** 테스트는 `tests/conftest.py`가 `DOC2REPORT_HOME`을 임시 폴더로 돌린다
  (개발자 PC의 실제 등록을 건드리지 않게).
- **저장소가 public이다(2026-09-30 확인)** — 토큰 값은 이력에 없지만 사내 주소(게이트웨이 호스트·LLM IP·프록시 IP)가
  CLAUDE.md·docs·scripts에 있다. 사용자에게 private 전환(또는 사내 git)을 권고함. 이력 정리(rewrite)는 사용자 결정 전 안 함.
  **앞으로 사내 주소·IP를 새 파일에 적지 말 것.**
- **PowerShell 대체 경로가 토큰을 `-Command` 문자열에 넣고 있었다** — 스크립트 블록 로깅(이벤트 4104)·보안 솔루션·
  프로세스 목록에 토큰이 남을 수 있다. 이제 헤더 값은 자식 프로세스 환경변수(`D2R_HEADER_n`)로만 넘기고 스크립트는
  `$env:D2R_HEADER_n`을 참조한다. 이 경로는 사내 PC에서 검증된 경로라 **바뀐 뒤 첫 실측 필요**.
- 팀원 안내: [docs/team-setup.md](docs/team-setup.md).

**설치 묶음·진단 (2026-09-30, 팀 공유 2단계)** — 사용자: "외부에서 코딩한 결과를 사내 PC에 설치할 때 파이썬 환경
자체를 맞추느라 고생했다. 팀원도 똑같이 고생할 것." 겪은 것: pypi.org·astral.sh 차단, uv 설치 불가(다른 PC에서
uv.exe를 USB로), `uv sync`가 lock의 URL만 찾다 실패, wheelhouse 수작업, `-offline` 하이픈 실수, HTTP_PROXY→Squid 403.
**그 과정을 받는 사람에게서 없앴다** — 설치 = zip 풀기.
- `packaging/build_windows_bundle.ps1`: git이 추적하는 파일 + `runtime\`(python.org **공식 embeddable** — 서명된
  python.exe, 사내 보안이 서명 없는 실행 파일을 막는 경우 대비) + `scripts/onprem-requirements.txt`(uv.lock에서 뽑은
  같은 버전)를 `--only-binary --no-deps --target runtime\Lib\site-packages`로. `python3XX._pth`에
  `Lib\site-packages`·`..\src`·`import site` — 앱을 설치하지 않고 소스 폴더를 그대로 쓴다(그래서 git 사용자는
  clone에 `runtime`만 복사하면 된다). ._pth가 있으면 사용자 site-packages·PYTHONPATH가 끼어들지 않는다.
  **빌드 PC의 파이썬 버전과 같은 embeddable을 받는다**(wheel ABI 일치).
- 실행 파일: `start_webapp.bat`·`doctor.bat`은 `runtime\python.exe`가 있으면 **PowerShell을 거치지 않고** 바로
  `python -m doc2report …`(GPO가 실행 정책을 잠그면 `-ExecutionPolicy Bypass`가 무시된다). 묶음(=.git 없음)은 결과를
  `%USERPROFILE%\Documents\doc2report`에 — 새 버전을 다른 폴더에 풀어도 결과가 이어진다. `runtime`이 없으면 예전처럼
  PowerShell + uv(없으면 설치 안내 후 종료). bat 파일은 **ASCII만**(cmd의 코드 페이지 문제).
- `src/doc2report/__main__.py`(`python -m doc2report`), `doctor.py`/`doc2report doctor [--save] [--no-network]`: 파이썬·
  패키지·코드 버전(.git/HEAD 직접 읽기 — git이 없는 PC도; main 아니면 경고)·Word 템플릿 왕복·결과 폴더 쓰기·글꼴
  (**이름은 프로파일에서** — 설계 원칙 1, 테스트가 잡았다)·PDF·사용자 등록·DPAPI 왕복·프록시·Confluence(whoami)·
  LLM(`/models`, 모델명 존재)·포트. 점검 하나가 죽어도 "실패" 한 줄로 바뀐다(`_safe`). 결과 파일은 UTF-8 BOM(메모장).
  토큰은 절대 안 쓴다. 실패가 있으면 종료 코드 1.
- `account._bypass_proxy_for_llm`: 등록된 **LLM 주소를 NO_PROXY에 자동 추가**(예전 onprem_env 스크립트의 역할 —
  묶음 사용자는 스크립트를 안 쓴다). Confluence 주소는 넣지 않았다 — 사용자 PC에서 지금 경로(SSL 실패→PowerShell)가
  검증돼 있어 바꾸지 않음.
- CI(`.github/workflows/windows.yml`): `lock-sync`(requirements가 uv.lock과 같은지), `test`(Windows에서 전체 테스트 —
  DPAPI 등 Windows 전용 경로), `bundle`(묶음 → **다른 폴더에 풀고 PATH에서 파이썬을 빼고** doctor·convert·web(잠김
  확인) 실행 → Artifacts, 태그면 Releases). **실제 사내 PC 제약(보안 프로그램·AppLocker가 서명 없는 .pyd를 막는지)은
  CI로 확인 못 한다 — 첫 배포 때 확인 필요.**
- 팀원 안내 [docs/team-setup.md](docs/team-setup.md) 재작성(설치 5분·doctor·흔한 문제표·업데이트·git 사용자·담당자용 빌드).

**다음 후보(제안만 함)**: 옵션 조합을 이름 붙여 저장(사용자 설정을 preset yaml로 저장), 결과 미리보기(HTML),
변환 전 표 배치 미리보기(`check`).

## 정식보고서 가이드라인 채굴 (2026-09-30 시작 — `guide_mining/`, 설계 근거)

목적: 사내 정식보고서(.docx) 말뭉치에서 서식·문장 형태·어투의 특징을 뽑아 가이드라인·규칙 후보로 삼는다.
온프렘 LLM만 쓸 수 있으므로 원문은 저장소 **밖**에 두고, 결과물에도 원문 글자를 안 넣는다(저장소가 public).
사용법은 [docs/guide-mining.md](docs/guide-mining.md).

- **`docx_reader`를 안 쓰고 `guide_mining/probe.py`를 따로 둔 이유**: 변환용 파서라 빈 문단·서식 값·머리말·
  텍스트 상자를 IR 계약상 버린다. 분석에는 그것들이 재료다. 서식은 스타일 체인을 풀어 실효값으로 읽는다.
- **역할 분담**: 세는 일(종결 형태, 길이, 표기, 서식)은 파이썬 — LLM은 세기에 약하다. LLM은 정성 판단(문장 역할,
  완곡/단정, 규칙 후보·사전 발굴)에만, 그것도 **폐쇄된 라벨 + JSON 출력**으로 받아 파이썬이 집계·검증한다.
  LLM이 낸 규칙 후보는 말뭉치 준수율·반례 수를 파이썬이 세어 기준을 넘는 것만 채택한다(환각 방지).
- **kordoc(chrisryugj/kordoc, 공문서 HWP 파서·생성기) 검토 결과 — 참고할 것만 취함(사용자: "필요 없는 것은 과감히")**.
  사내 보고서는 정부 공문서와 스타일이 다르고 docx라서 대부분 버린다.
  - 취함: ① 줄 종류(층)별로 종결·길이 분포를 따로 잰다 — 같은 문장도 층에 따라 허용 여부가 다르다.
    단 층 이름(□ ❍ ⇒)은 코드에 두지 않고 말뭉치의 말머리·들여쓰기 순서에서 얻는다.
    ② 실측 → 임계값 → 검수 순서, 검수는 경고만 하고 막지 않으며 인용·괄호 안은 판정에서 뺀다.
    ③ 근거 등급(confirmed/measured/medium)을 가이드라인에 표기한다.
  - 버림: 정부 부호 체계와 실측 임계값(항목 31자 등 — 지자체 15건 기준이라 우리 것이 아니다), HWP/HWPX 파서·
    생성기, 서식 상수, 두문/결문, 공문서 표기법 19룰, 렌더러. 문체 **변환**은 kordoc도 범위 밖이라 참고 없음.
  - 지금 읽은 범위: docs 3종과 munche-lint.ts 앞부분. 실행해 보지 않았고 원 출처 수치는 확인 못 함.
- **첫 실측(2026-09-30, 사내 정식보고서 8건)**: 여백 25/25/20/20 75%(6건), 바탕체 14pt 68%, 장평 100% 96%,
  줄간격 1.429배 63%, 명사 종결 70%·`~음/함/임` 2%, 마침표 1.5% — `default.yaml`과 거의 일치. 표는 12pt 69%,
  머리행 표시(`tblHeader`) 0건·음영 91% 없음, 표 정렬 왼쪽 91%(우리 `tables.align: right`는 사용자 확정값이라 별개).
  **계층은 들여쓰기가 아니라 글쓴이가 친 앞 공백**으로 나뉜다(모든 말머리 `left_mm`=0, 앞 공백 `-` 3·`□` 1·`※` 4) →
  층 정렬을 `(left_mm, 앞 공백)`으로 바꿈. `□` 굵기 0.419(문장 일부만 굵음 추정 — `level_bold` 전체 굵게와 다를 수
  있음, **문서 확인 필요**). 표본이 작다(본문 항목 131개).
- **텍스트 상자 = 주석 층 (사용자 설명)**: 본문 문구 아래·옆 여백에 붙이는 설명(바탕체 10pt, 파란 글씨, 예: "핵심인력"
  옆에 조건 설명). 8건 모두에 있었는데 첫 요약엔 집계되지 않았다(stats가 body·table만 봄). 이제 `TextBoxProbe`(DrawingML·VML
  모두: 위치·크기·줄바꿈·테두리·바탕색·붙은 문단의 말머리)와 글자 색(`Fmt.color`)을 기록하고 `annotations` 절로 집계한다.
  **변환기는 아직 이 주석을 모른다** — Confluence에 대응물이 없어(인포 패널·각주 후보) 실측 요약을 본 뒤 결정.
- **한 번에 보내기 (2026-09-30, 사용자: 사내에서 결과를 외부로 자주 못 보냄)**: 1차 실측에서 "확인 필요"로 남은 것을 한
  번의 실행으로 다 답하도록 요약을 넓혔다. 말머리 층별 굵기 모양(`bold_pattern`: 전부·앞부분·뒷부분·섞임)·밑줄·간격·
  글자 색, 말머리 없는 줄의 정체, 문서 첫머리·말미 6+3줄의 모양(제목·날짜 위치), 날짜 표기 모양(숫자를 9로 가림),
  표(스타일의 첫 행 음영·첫 행/열 직접 음영·너비/본문 폭·테두리·바로 위/아래 줄 종류·머리행/첫 열/나머지 칸 서식),
  여러 문서에 반복되는 1.·Ⅰ. 제목과 표 머리 용어. **원문 글자는 안 나오는 것이 원칙인데 예외가 `phrases` 절 하나**(2건
  이상 문서에 반복된 짧은 말만; 한 문서에만 있는 말은 제외) — 민감하면 `--no-phrases`. 새 정보가 필요해질 때마다 왕복하지
  않도록, 요약에 없는 것을 묻게 되면 먼저 probe에 넣을 수 있는지 볼 것.
- **2차 실측(2026-10-01, 같은 8건)에서 나온 것과 probe 보완**: ① 표 머리 음영이 전부 "없음"인데 `tblLook` 첫 행 강조는 100%
  켜져 있었다 — 직접 색만 보고 **테마색(`themeFill`)·패턴 음영을 놓쳤을 가능성**이 커서 `_shd_spec`으로 모두 읽게 고쳤다
  (재실측 필요). ② 텍스트 상자 줄바꿈 라벨 "None"은 `wrapNone`(글 앞 배치)의 표기 오류였다. ③ □의 굵기가 전부 39%·앞부분
  36%·없음 26%로 갈려 하위 항목 유무와 대조하는 항목을 넣었다. ④ 한자 약어(無·要·日)·↑·▲·영문 약어가 보여 글자 구성·기호
  절을 넣었다. ⑤ 칸 테두리(표 수준 테두리는 91%가 미지정 — 스타일·칸 테두리에 있을 것), 상자 x·세로 어긋남, 문서별
  대표 크기·줄간격·여백도 추가.
- **정식보고서 서식 분리 (2026-10-01 사용자 결정)** — 목적이 다른 두 서식이다: **정식보고서 = 상급 조직 보고용**(이 도구가
  `profiles/formal.yaml`로 따로 구현), **Confluence 변환 = A4로 인쇄해 편하게 읽기용**(`confluence.yaml`, 그대로 유지). `formal`은
  `extends: default`지만 `default`·`confluence`는 한 글자도 안 바꿨다(테스트 `test_other_profiles_are_unchanged`가 지킴).
  실측 8건 + 사용자 설명으로 정한 값: ① **단계는 들여쓰기 기능이 아니라 앞 공백**(1.은 0칸, □ 1칸, - 3칸, · 6칸; 말머리 뒤도 공백
  한 칸) — `NumberingLevel.lead_spaces`·`marker_sep` 새 필드, indent·hanging은 0이라 **둘째 줄은 왼쪽 여백에서 시작**한다
  (probe가 left=0·first_line=0으로 이미 보여 줬던 것). ② 표 왼쪽 정렬·음영 없음(`header_shading: null`). ③ **주석 = B안**:
  `*`로 시작하는 문단은 `fonts.annotation`(바탕체 10pt, 0000FF)으로 쓰고 □ 항목으로 접지 않는다(`text.annotation_markers`,
  `fold_headings_into_levels(annotation_markers=)`). 실제 문서는 텍스트 상자지만 여기서는 윗줄에 딸린 일반 문단(편집하기 쉬움).
  주석 줄이 끼어도 단계 바뀌는 간격은 **윗줄 기준**(`_annotation_gap`, `_item_spacing`, `_space_before`). ④ ※는 본문과 같은 크기
  (`note_size_delta: 0pt`)이고 공백 4칸(`note_lead_spaces`). ⑤ 본문 줄간격 143%(실측 1.429배 63%).
  **웹 화면 주의**: preset 서식에 규칙(text)을 끼울 때 ※·주석 표시 방식은 서식이 정한다 — `profile.with_format_text`가
  `FORMAT_TEXT_FIELDS`를 preset 쪽으로 지킨다(안 그러면 formal을 골라도 규칙 프로파일의 text로 덮여 주석이 사라진다).
  **아직 안 정해진 것**: 주석 줄의 앞 공백 4칸은 임시값(상자 x 위치 실측 전), □·- 공백 수(2026-10-01 사용자가 probe 중앙값 1·3칸으로 확정 —
  다음 실측에서 공백 수 분포를 보고 확정), 제목 밑줄(default는 있음, 실측 38%), □ 굵기(default 문장 전체 굵게, 실측 전부 39%).
  Markdown의 `* 문장`은 목록으로 읽혀 주석 표시가 사라진다 — 주석은 Confluence·Word·붙여넣은 글에서 문단으로 들어올 때만 인식한다.
  이 샌드박스의 LibreOffice는 변경 전 코드의 docx도 못 열어(환경 문제) 렌더 실측은 못 했다 — **Word 실측 필요**.
- **정식보고서 실사용 1차(2026-10-01, 서식을 없앤 txt로 변환) 후속**: 사용자가 txt에 "(주석)"이라고 표시했는데 주석이 안 나왔고, □가 전부
  보통체였다. ① `text.annotation_markers`에 "(주석)"도 넣고 `structure.normalize_annotations`가 "* 설명"으로 통일한다(문구 다듬기는
  주석을 건드리지 않음 — `_Engine`이 건너뜀; 순서: 다듬기 → 표 주석 → **주석 통일** → 제목 접기). ② 1.·□ 굵게는 원래 "도구가 붙인
  말머리"에만 적용했는데 서식 없는 글은 원문 굵기 정보가 없다 → `text.level_bold_original: true`(formal)이면 원문 말머리 줄에도
  적용(`marker == ""`인 꺾쇠 줄은 제외). ③ txt 맨 위 짧은 줄 + 바로 다음 줄이 날짜면 `# 제목`으로 읽는다(`plaintext._mark_title`).
  이 값들(`annotation_mark`, `level_bold_original`, `fit_*`)도 서식이 정하므로 `FORMAT_TEXT_FIELDS`에 있다.
- **`*`만 써도 주석 (2026-10-01 사용자: "(주석)"을 안 넣어도 되게)** — formal은 원래 `*` 시작 문단이 주석이다("(주석)"은 같은 뜻의 별칭).
  예외였던 **표 바로 아래 `*` 줄**은 `attach_table_notes`가 표 주석(검은 10pt)으로 먼저 빼 갔다 → `formal.yaml`의
  `tables.note_markers`에서 `*`를 빼(`["주)", "주:"]`) 본문 주석(파란 10pt)으로 남기고, ※는 본문 ※ 줄로 둔다.
  사용자가 "글상자"라 불렀지만 실제 텍스트 상자가 아니라 윗줄에 딸린 문단이다(B안, 편집이 쉬움).
- **줄 맞춤 (2026-10-01 사용자: 정식보고서는 줄이 길면 엔터로 나누고 왼쪽 끝을 윗줄에 맞추며, 아슬아슬하면 글자 간격 0.1~0.5pt 좁힘)** —
  `layout/lines.py::fit_text`(글자별 폭 목록 → 줄 범위·좁힐 단계; 어절 경계에서만 나눔, 넘침/글자수 ≤ `condense_max`면 나누지 않고
  `condense_step` 단위로 올림해 좁힘, `fit_margin`만큼 덜 씀)와 렌더러 `_fit`/`_emit_fitted`. **줄마다 문단 하나**(엔터), 둘째 줄부터는
  접두(공백+말머리+구분) 폭을 `TextMeasurer`로 재서 **그만큼 공백**을 친다(바탕체는 전각 □=반각 2칸). 내어쓰기가 있는 프로파일은
  내어쓰기로 맞춘다. 좁히기는 본문 run에만 걸고(`oxml.set_char_spacing`, w:spacing −2~−10) 접두 공백·말머리는 안 좁혀 윗줄과 정렬이
  어긋나지 않는다. 한 문장의 줄들은 `keep_with_next`. 글꼴 파일이 없으면(`font_available` False) 건너뛰고 --report에 남긴다.
  `text.fit_lines`가 켜진 formal만 해당. **글꼴 폭 계산이 Word와 다르면 Word가 줄을 또 바꿔 들쭉날쭉해진다 — 이 샌드박스엔 바탕체가
  없어 합성 폭(`_FakeMeasurer`)으로만 검증했다. 사내 PC의 Word 실측 필요**(어긋나면 `fit_margin`을 올림).
- **정식보고서 실사용 2차(2026-10-01) — 내려쓴 줄·좁히기·텍스트 상자 주석**: ① 사용자 설명: 원문의 내려쓴 줄은 한 문장이 길어서 엔터로 나눈 것이라
  **말머리가 아니라 윗줄 글자 시작에 정렬**되고 □는 둘째 줄도 굵게. 서식을 없앤 txt에서는 그 줄이 **독립된 줄**이라 새 항목(말머리가 붙고
  굵기·정렬이 틀어짐)이 됐다. `plaintext._join_wrapped`가 말머리 줄 바로 아래의 말머리·날짜·꺾쇠·괄호 없는 줄을 윗줄에 이어 붙인다 —
  윗줄이 `_WRAPPED_MIN`(24)자 이상이거나 이 줄이 공백 2칸 이상 들여써졌을 때만(짧은 소제목 뒤 설명 문단과 구분). 합친 문장은 줄 맞춤이 다시
  나눈다. 말머리·꺾쇠 문자는 default 프로파일 값을 읽는다(코드에 안 굳힘). ② "조금 넘으면 글자 간격을 좁히기"는 알고리즘상 동작했지만(한 글자
  넘침 → 0.1~0.2pt), 원본은 이미 **좁혀서 꽉 채운 줄**이라 우리 계산에 여유가 크면 나뉘어 버린다 → `fit_margin` 1% → 0.5%. 굵은 글자 폭 보정
  (`TextMeasurer.bold_factor` 1.04)이 맞는지는 모른다 — probe `fitting` 절이 **원본 줄의 폭 사용률(굵은/보통 × 좁힘/그대로)**과 글자 간격
  분포, 내려쓴 줄의 앞 공백 수를 실측한다(다음 실행에서 `fit_margin`·굵기 보정을 숫자로 정할 것). ③ **주석 텍스트 상자**:
  `text.annotation_box: true`(formal)면 `*` 주석을 윗줄 아래의 VML 텍스트 상자(글자 앞, 테두리·배경 없음, `oxml.add_text_box`)로 띄운다.
  상자 위치 = 윗줄 글자 시작 x, 윗줄 문단 위에서 한 줄 높이(글꼴 OS/2 win 메트릭 × 크기 × 줄간격) 아래. **상자는 글자 앞 개체라 아래 공간을
  윗줄의 단락 뒤 간격으로 비운다**(여러 주석은 아래로 쌓음). 글꼴 못 찾음·윗줄이 문단이 아님(표·제목 뒤, 문서 첫머리)이면 일반 문단 주석으로
  쓴다. **Word에서 열어 본 적이 없다**(이 샌드박스는 LibreOffice도 못 열고 VML 구조는 우리 probe로 되읽어 확인) — 안 열리거나 위치가
  어긋나면 `annotation_box: false`로 끄면 문단 주석으로 돌아간다.
- **정식보고서 실사용 3차(2026-10-01) — 엔터 위치를 보존하고 문구를 안 고친다**: 사용자가 pull 후 변환해 본 결과 ① `*` 문장 둘 중 하나가 본문으로
  나옴 ② 줄바꿈이 뒤죽박죽(원문에서 엔터 안 친 문장을 우리가 나누고, 엔터 친 문장은 한 줄로 합침) ③ 일부 내려쓴 줄만 정렬·굵기 적용
  ④ 일부 문장의 ","가 "."로 바뀌고 종결. **원인**: ④ 줄을 합친 문장이 60자를 넘으면 문구 다듬기의 `split_long_sentences`가 쉼표에서 쪼개
  "."로 끝내고 뒷부분을 새 항목(말머리·굵기·정렬 없음)으로 만든다. ③ 합치는 조건에 윗줄 24자 이상이 있어 짧은 줄은 독립 항목이 됐다.
  ② 합친 줄을 다시 나누니 글쓴이의 엔터 위치와 어긋남. ① 공백 없는 `*설명`·전각 `＊`는 말머리로 안 읽혀 윗줄에 이어 붙음.
  **수정(방향 전환)**: `plaintext._join_wrapped`는 말머리 줄 바로 아래 말머리·날짜·꺾쇠·괄호·주석 표시 없는 줄을 **합치지 않고** Markdown 강제
  줄바꿈(줄 끝 공백 2칸)으로 같은 문단에 묶는다(마침표·물음표로 끝난 줄 뒤, 번호 제목 뒤, 날짜 줄 뒤는 안 묶음; 길이 조건은 뺌). 파서가
  `hardbreak`를 `"\n"`으로 읽고, 렌더러 `_fit`은 `"\n"` 자리를 **글쓴이의 엔터로 지키며** 그 줄마다 따로 맞춘다(둘째 줄부터 윗줄 글자
  위치에 공백 정렬, 굵기는 항목 전체). 우리가 더 나누는 건 한 줄이 좁히기 한도(`condense_max`)를 넘을 때뿐이다. 줄 맞춤이 꺼졌거나
  문구 다듬기를 켠 서식은 `soften_hard_breaks`가 `"\n"`을 공백으로 바꿔 예전처럼 한 문장으로 쓴다(문장 분리가 줄바꿈 낀 문장을 쪼개므로).
  `formal.yaml`: `polish: none`(정식보고서는 문구를 안 고침; 초안을 개조식으로 바꿀 때만 `--polish rules`), `condense_max: 1pt`(사용자),
  주석 표시 `* ＊ ∗ (주석)`. `--report`에 "더 나눈 줄이 한 줄에 들어가려면 글자마다 좁혀야 했던 양(pt)" 최소·중앙·최대를 남긴다 — 1.0 근처에
  몰려 있으면 폭 계산이 실제보다 넓다는 뜻(굵은 글자 보정 1.04 의심)이라 probe `fitting` 절의 줄 폭 사용률과 같이 보고 `fit_margin`·굵기 보정을 정한다.
- **정식보고서 실사용 4차(2026-10-01) — "1pt까지 좁힌다고 했는데 두세 글자 남기고 내려씀"**: text box 주석·내려쓴 줄 왼쪽 정렬은 사용자 확인으로 잘 됨.
  원인 후보 둘: ① 굵은 글자를 4% 넓게 재는 보정(`TextMeasurer.bold_factor` 1.04) — □ 줄은 전부 굵어 31자 줄에서 17pt를 더 넓게 봐 좁히기 한도(1pt×글자수)를
  일찍 넘긴다 ② `fit_margin` 0.5%(2.4pt)가 1pt 한도의 8%를 먹는다. 수정: `text.fit_bold_factor`(formal 100%, **잠정** — 실제 굵은 줄이 더 넓으면 Word가
  줄을 또 바꾼다; probe `fitting`의 굵은/보통 줄 폭 사용률로 확정), `fit_margin` 0.2%. **3-글자 남김은 정당한 경우도 있다**: 31자 줄에 세 글자(42pt)는 1pt로
  못 구한다(필요 ≈1.35pt) — 그건 원본도 못 한다. **안전장치**: 줄 맞춤으로 나눈 문단은 접두(공백+말머리) 폭만큼 **내어쓰기**(left=접두 폭, first=−접두 폭)를
  같이 줘서, 글꼴 폭 계산이 Word와 달라 Word가 줄을 한 번 더 바꿔도 이어지는 줄이 윗줄 글자에 맞는다(줄이 맞게 들어가면 안 보임; `_FitPlan.first_hang/cont_hang`).
- **`default` 서식을 웹 목록에서 숨김 (2026-10-01 사용자: 정식보고서·Confluence 변환 둘만)** — `default.yaml`에서 `label`·`preset_order`만 뺐다(formal·confluence가 `extends: default`이고 자동 판단의 규칙 기본값도 여기서 오므로 파일은 남긴다). 목록은 정식보고서(1)·Confluence 변환(2). 서버는 옵션 없는 호출·"규칙 기본값"에서 숨은 `default`를 여전히 받는다(`options._HIDDEN_BASE`). 화면 기본 선택은 목록 첫째(정식보고서). 직접 선택의 "규칙 기본값" 선택지도 이 둘이라, 예전 '보고서' 규칙(말머리 만들기·개조식)은 체크박스로 켠다.
- **샘플 입력 `samples/`**: 정식보고서 변환 확인용 가상 문서 2건(txt 메모 — `*`·※·탭 표·주), md — 표 2개). 실제 내용 아님.
- **정식보고서 실사용 5차(2026-10-01, 샘플 2건 변환)** — 사용자 지적 → 처리:
  ① 계산상 0.9pt로 좁혀 둔 줄을 Word는 1.0pt여야 한 줄에 넣음 → `text.condense_pad: 0.1pt`(계산값 + 0.1pt, `condense_max` 이하). `fit_text(pad=)`.
  ② 주석·※ 뒤가 붙어 보임, 새 절 앞 간격 → **단락 앞 대신 윗줄의 단락 뒤**: `gap_after_annotation`·`gap_after_note`·`gap_after_section` 모두 18pt,
  `numbering[0].space_before: 0`. 주석 상자는 윗줄의 단락 뒤 = 상자 높이 + 18pt. ※는 `note_size_delta: 2pt`(14→12pt, 주 문장이 아님). `_is_note`가
  `note_indent`만 보던 것을 `note_lead_spaces`도 보게 고침(formal은 note_indent 0이라 ※가 노트로 안 잡혔다).
  ③ 표 왼쪽 끝 = 윗줄 □ 말머리의 왼쪽 끝: `table_indents`가 `lead_spaces` 폭(공백 × 본문 글꼴)을 더하고(주석·※ 줄은 기준에서 제외), 왼쪽 정렬 표는
  `oxml.set_fixed_layout(indent=)`가 `w:tblInd`로 시작점을 준다(예전엔 오른쪽 정렬 표만 폭으로 위치가 정해졌다). **Word에서 tblInd가 테두리 기준인지
  글자 기준인지(호환 모드) 실측 필요.**
  ④ 마크다운 입력의 `2026. 10. 1`이 번호 목록으로 읽혀 날짜가 사라짐 → `parse_markdown`이 날짜 줄만 이스케이프(`_DATE_AS_LIST`).
  ⑤ 표 열 폭: `tables.equal_columns`(formal) — 같은 성격(값) 열은 폭 동일, 머리가 `note_columns`(비고·이슈·참고·특이사항·의견·코멘트)인 열은 참고 열로
  표 폭의 `note_column_max`(30%) 이내, 글자 `note_column_size`(10pt), 폭 상한을 넘으면 장평 `note_column_scales`([100%, 90%]) 순서로 줄임(`cell_font`
  사이드 테이블 재사용). 같게 하면 값 칸이 줄바꿈되거나 병합 열이 있으면 원래 폭 배분으로 돌아간다(`_equalize_columns`가 None). 참고 열 판정은 머리
  글자가 목록과 같을 때만 — 그 밖의 긴 글 열은 자동 판단하지 않는다(필요하면 `note_columns`에 머리 이름을 추가).
  ⑥ 좁히기 한도(1pt)로도 두세 글자가 다음 줄로 넘어가는 문장: `text.shorten_to_fit`(formal true) + LLM이 켜져 있으면 LLM이 "최대 N자"로 줄이고(`llm_polish.
  shorten_sentence`, 한 번에 안 맞으면 2·4자 더 짧게 재시도, 서식이 섞인 문장은 건드리지 않음) 줄인 결과가 한 줄이면 채택 — `--report`에 "표현 줄임: 전 → 후".
  LLM이 없거나 실패하면 원문 그대로 두고 "두세 글자가 다음 줄로 넘어간 문장 N개(넘친 글자 수)"만 남긴다(`orphan_max` 4자). 이 샌드박스는 LLM이 없어 가짜
  줄임 함수로만 검증 — **온프렘 LLM 실측 필요**(문장 끝 형태·사실 유지 여부).
- **표 아래 ※ (2026-10-01 사용자)**: 표를 부연하는 ※ 줄은 12pt(`note_size_delta: 2pt`)이고 앞 간격은 표 뒤 18pt(`tables.space_after`)가 아니라 6pt — `tables.note_space_before: 6pt`(formal), 렌더러 `_table_gap(is_note)`. ※ 뒤 간격 18pt(`gap_after_note`)는 그대로.
- **표 머리 구분선 (2026-10-01 사용자)**: 정식보고서 표는 머리에 음영이 없고 **머리행 아래 테두리 1.5pt**로 내용과 구분한다 — `tables.header_rule_width: 1.5pt`(formal), `oxml.set_header_rule`이 머리행 칸의 아래 테두리와 다음 행 칸의 위 테두리를 같이 지정(Word가 어느 쪽을 골라도 같은 굵기). 원본 probe의 칸 테두리 절에서 실제 굵기를 확인해 값을 맞출 것.
- **LLM 켜는 법 (2026-10-01)**: `--polish llm`은 파이썬 규칙 + LLM이라 정식보고서에서는 쓰지 말 것(규칙이 문장을 쪼갠다). 정식보고서용은 `--shorten`(문구는 안 고치고 넘치는 문장만 줄임)·`--llm`(교열 + 줄임, 규칙은 formal 그대로 = 안 함). 엔터로 나눈 줄(`\n`)이 든 문장은 교열 LLM에 안 보낸다(`llm_polish._collect`) — 줄 위치를 지키고, 한 줄 답 형식에 안 맞아서. 그래서 줄 맞춤이 켜진 서식은 LLM이 켜져도 `soften_hard_breaks`를 건너뛴다.
- **추가 샘플 테스트에서 나온 것 (2026-10-01, `samples/sample_3~6`)**: ① formal이 `polish: none`인데도 짧은 항목 두 개가 "및"으로 합쳐짐 — `merge_short_items`는 polish와 따로 돌기 때문(pipeline) → formal에서 `merge_short_items: false`(confluence와 같은 이유). ② 탭 표에서 끝 칸이 빈 줄(엑셀 복사 시 끝 탭이 잘려 칸이 모자람)이 표에서 떨어져 나와 `A\t30%\t120%` 문단이 됨 → `plaintext._tab_block`이 머리보다 칸이 적은 줄도 표 줄로 보고 `_tab_table`이 빈 칸을 채움. 이 세션은 가짜 글꼴 폭이라 줄 나눔 위치 자체는 사내 PC Word에서 봐야 한다.
- **정식보고서 실사용 6차 (2026-10-01, 샘플 3~6 변환)**: ① 계산상 0.6~0.7pt로 좁힌 줄을 Word는 1.0pt여야 한 줄에 넣음(두 번째 실측) → `condense_pad` 0.1 → **0.4pt**(계산값 + 0.4, 최대 1pt). 폭 계산이 글자당 0.3pt쯤 모자란 듯 — probe `fitting`의 줄 폭 사용률로 근본 보정을 정할 것. ② S4 둘째 표 글자가 10pt로 내려감 — 비고가 길어 `max_cell_lines`(3줄)에 걸려 **표 전체**가 내려간 것. 참고 열은 줄 수 검사·`_shrink_long_cells`에서 빼고 그 열 글자(10pt, 장평 90%)만 줄인다 — 표는 12pt 유지, 비고는 줄바꿈으로 받는다. ③ 표 정렬을 formal에서 다시 **오른쪽**으로(`tables.align: right`) — left + `tblInd`는 Word에서 윗줄과 안 맞았다(사용자). 오른쪽 끝이 여백선에 닿고 폭 = 윗줄 글자 시작 ~ 오른쪽 여백이라 왼쪽 끝이 맞는다(`oxml.set_fixed_layout`의 indent는 left 정렬일 때만 씀). ④ 주석 텍스트 상자가 한 줄 높이에 딱 맞아 겹침 → `text.annotation_box_height: 5mm`(한 줄당 최소, 윗줄 단락 뒤 간격에도 반영).
- **정식보고서 실사용 7차 (2026-10-01, 마지막 지적)**: ① ※ 뒤 간격이 **계통**에 따라 다르다(사용자): "- 문장1 / ※ / - 문장2"처럼 같은 단계가 이어지면 6pt(`gap_after_note_same_level`), "- 문장1 / ※ / □ 문장2"처럼 단계가 바뀌면 18pt(`gap_after_note`) — 기준은 ※가 아닌 마지막 항목의 단계(`_plain_depth`)와 다음 항목의 단계. ② 단계 체계: 1. → **(1)·원문자(①)** → - → · . `(1)`·`①`을 □와 같은 1단계로(`text.pattern_depths` 정규식 목록; `①`은 `str.isdigit()`가 True라 예전엔 0단계, `(1)`은 단계 없는 일반 문단이었다) — 그래서 그 아래 `-`가 한 칸만 들여써졌다. `·`는 `-`보다 2칸 더(5칸, `lead_spaces: 5`). ③ "표가 계속 왼쪽 정렬" — 샌드박스에서는 `jc=right`로 나오고 재현 못 함. 사용자가 최신(0c51304 이후)을 받았는지 확인이 필요하고, 그래서 `--report`에 표마다 "위치: right 정렬, 왼쪽 끝 Xmm, 폭 Ymm"을 남긴다. ④ LLM 줄임이 잘 안 됨 — 진단용으로 `--report`에 "표현 줄임 시도 결과(진단)"(응답 없음/안 짧아짐/줄였지만 두 줄, 글자 수)를 남긴다. 다음엔 이 줄을 보고 프롬프트·목표 글자 수(전각/반각 폭 차이)를 조정할 것.
- **정식보고서 실사용 8차 (2026-10-01, 마지막 설명)**: ① **단계는 말머리 종류가 문서에 나온 순서로 정한다**(`text.levels_by_order`, `structure.fold_headings_into_levels`의 `stack`): "1. □ -", "1. □ (1)·① -", "1. (1)·① □ -", "□ -", "□ (1)·① -", "(1)·① □ -" 모두 나온 순서대로 한 단계씩 내려가고, 이미 나온 종류가 다시 나오면 그 단계로 올라간다(제목 `##`을 만나면 쌓은 것을 비운다). 종류 = `numbering` 별칭(□·-·· 등) / `pattern_depths`의 정규식(`(1)`과 `①`은 같은 종류) / 숫자 시작("1."). 앞 공백은 **단계 번호**를 따른다(0·1·3·5·7칸 — `numbering`을 다섯 단계로 늘림). 그래서 □가 맨 위인 두 단계 문서는 □ 0칸, - 1칸이 된다(원본이 □ 1칸·- 3칸이던 건 `1.`이 있는 문서였음 — 틀리면 알려 줄 것). ② **간격**(※·주석에도 똑같이): 같은 단계가 이어지면 6pt(`space_after`), 더 얕은 단계로 올라가면 12pt·지면에 여유가 있으면 18pt(`space_after_level_up`·`_max`, `NumberingLevel.level_up_space`), 내려갈 때(□ 다음 -)는 6pt(`space_after_level_change`, 이전에 사용자가 확정한 값 — "다른 단계는 12·18pt"를 내려가는 쪽에도 적용할지는 확인 필요). `gap_after_annotation`·`gap_after_note`는 formal에서 비웠다(일반 규칙 `_transition_gap` 사용; 값을 주면 예전처럼 고정), `gap_after_section` 18pt(새 `1.` 앞)는 유지. `flow.py`의 여유 판단도 같은 규칙으로 맞췄다.
- **단계 시작 위치 보정 (2026-10-01 사용자)**: `□ -` 두 단계 문서는 □ 1칸·- 3칸, `1. □ -`는 0·1·3칸 — 맨 위 종류가 "1."이 아니면 `1.` 단계를 비워 둔 채 시작한다(`fold_headings_into_levels`의 `stack`에 가상 `("n",)`를 먼저 쌓음). 제목(`##`)은 스택의 맨 위 단계(`("h",)`)다. `levels_by_order`일 때는 `normalize_levels`(맨 위를 0으로 당기기)를 건너뛴다 — 단계 번호가 곧 앞 공백이라서.
- **서식 값은 사용자 지시가 probe보다 우선 (2026-10-01)**: 표 머리 음영 없음, 머리행 아래 테두리 1.5pt, 주석 상자 한 줄 0.5cm(위치는 규칙이 없고 사용자가 Word에서 수동 조정), 말머리 앞 공백은 사용자가 말한 규칙(1.=0·□=1·-=3··=5, 문서에 나온 순서)을 따른다. 위 값들은 probe로 다시 검증하지 않는다. 줄 폭 사용률(좁히기 보정)도 사용자 실측으로 정한 `condense_pad: 0.4pt`를 쓴다.
- **줄 폭 원인 확정 (2026-10-02, 사내 PC Word 실측)** — 사용자 새 Word 문서에서는 14pt 바탕체 한글이 간격 0에 34자, 0.4pt 36자, 0.7pt 38자, 1.0pt **40자**(계산상 37자)였는데 도구 docx는 1.0pt에서 37자였다. 같은 문자열을 붙여도 문서에 따라 달랐다. `tools/docx_diff.py`(두 docx의 설정 차이만 출력, 본문 안 읽음)로 사용자 문서와 대조 → 변형 docx(`tools/make_calibration.py`)로 이분 탐색: 호환 모드 15·문장부호 압축·언어 ko-KR·양쪽 맞춤·커닝 모두 **무관**, `w:compat/balanceSingleByteDoubleByteWidth`("한글·영문 폭 균형", 한글 판 Word 새 문서 기본값)를 켜면 40자. 그래서 `text.balance_sbcs_dbcs`(formal true, Confluence 변환은 기존대로 꺼짐)로 렌더러가 이 옵션을 켠다(`oxml.set_compat_flag`). **줄 폭 모델 보정 (같은 날 후속, 사용자 실측 `make_calibration` [1]~[12], 옵션을 켠 docx)**: 한글 보통 34/35/36/38/40자 @ 간격 0/0.2/0.4/0.7/1.0pt, 굵게 34/36/40자(@0/0.4/1.0 — 굵기 차이 없음 → `fit_bold_factor` 100% 맞음). 한글 폭 14pt − **2c**로 정확히 맞는다(`tests/test_formal_round5.py::test_condense_model_matches_word_measurements`). 영문·숫자: 한글 24 + 영문숫자 16자 @0, 한글 27 + 20자 @1.0pt가 한 줄 → 반각 폭 ≈ 8.2~9.1pt(0.6em, 글꼴 0.5em보다 넓음), 간격 효과는 1×c(한글만 2×). 그래서 `text.condense_wide_weight: 2`(`fit_text(weights=)`: 줄에서 줄어드는 폭 = c × Σ글자 배수)와 `text.latin_min_width: 60%`(영문·숫자 폭의 하한, 공백 제외)를 formal에 넣었고 `condense_pad`를 0.4→0.1pt로 낮췄다(예전 0.4는 옵션 없던 시절의 오차 보정). **공백 폭·공백의 간격 효과는 미측정**(한글+공백 시험이 줄바꿈 위치를 못 가렸다: 30자+5칸·35자+6칸 모두 다음 어절이 어떻게 해도 안 들어가는 구조) — 다음에 잴 때는 공백이 많은 줄을 어절 경계 직전에 걸리게 설계할 것. **샘플 3·5 재변환(2026-10-02 사용자): 모든 줄이 한 줄에 딱 맞음 → 모델 보정이 맞다. 다만 필요보다 0.1~0.2pt 더 좁혀져 `condense_pad`를 0.1→0pt로 낮췄다(남는 여유는 0.1pt 단위 올림뿐). **재실측(2026-10-02 사용자): 샘플 3·5 모든 줄이 내려가지 않고 깔끔하게 한 줄로 반영됨 — 줄 맞춤 모델(한글 2배·영문 0.6em·pad 0) 확정.** 한도(1pt, 사용자 규칙)를 넘어 도구가 나눈 줄이 리포트에 소수 남을 수 있다(pull 전 리포트에서 s3 2개·s5 3개, 필요 1.02~1.61pt) — **결정 사항 아님: 1pt 유지가 사용자 규칙이고 줄 맞춤은 완료**(사용자 2026-10-02: "이미 피드백 다 주고 반영한 것").
- **줄글 → 정식보고서 1차 구현 (2026-10-02, `drafting.py`, CLI `doc2report draft 줄글.txt`)** — 온프렘 LLM 사양 실측: Qwen3.6-27B-NVFP4, 컨텍스트 262k, 생성 115~145토큰/초, 입력 처리 약 4,700~12,000토큰/초(길수록 느림: 1.4만 토큰 1.1초·6.9만 8.2초·18.3만 39초, 같은 입력을 되풀이하면 서버가 앞부분을 캐시해 0.3~1.3초), **기본이 추론 모드라 같은 답이 약 9배 느림**(1,500자→300자 10.4초 vs 끄면 1.2초 — `chat_template_kwargs.enable_thinking=false`를 서버가 받음; `llm_polish`가 이제 기본으로 끈다, 켜려면 `DOC2REPORT_LLM_THINKING=1`). 긴 입력 찾기 시험(문서 곳곳에 심은 5자리 코드, 앞·중간·뒤): 2만·9.9만·26.3만 자(1.4만·6.9만·18.3만 토큰) **9/9 일치** — 단 고유 사실 찾기라 낙관적이다, 문서 간 종합·비교는 따로 시험할 것. 세기("몇 번 나오나")는 LLM이 약해 틀렸으니 시험·기능에 쓰지 말 것. 설계: LLM은 **배치만** 한다 — 문장에 번호를 붙여 보내고 `{sections:[{heading, groups:[{summary, ids, notes}]}]}` JSON을 받는다. 세부 `-`는 **원문 문장 그대로**, 절 제목·□ 요지만 새로 쓰되 **요지의 숫자가 묶음 원문에 없으면 요지를 버린다**(`sanitize`), 모든 문장이 정확히 한 번·원래 순서로 나와야 하며 어긋나면 한 번 재시도 후 규칙 기본 구조(한 절, 문장마다 □)로 돌아간다. 요지 없는 묶음은 첫 문장이 □. 참고·단서 문장은 `*` 주석. 문구는 안 고친다(formal `polish: none`; 개조식 변환은 `--polish rules`를 변환 단계에 따로). 결과 글(`_구조.txt`)을 formal 변환기에 넣는다. 이 샌드박스는 LLM이 없어 가짜 응답으로만 검증했다 — **온프렘 LLM 실측 필요**(요지 품질, 절 나눔이 정답 쌍과 얼마나 같은지). 가상 시험지 `samples/drafting/`(줄글 5건), 사람이 정제한 정답은 `정답_N_*.txt`로 받아 비교한다.
- **줄 폭 모델 2차 보정 (2026-10-02, `make_calibration` [13]~[22] 실측)** — S5에서 필요보다 0.2~0.3pt 더 좁힌 줄(영문·공백이 든 줄)의 원인을 낱글자 시험으로 확정: ① 숫자·대문자·소문자·`%` 100자가 간격 0에 **68자**, 1.0pt에 **80자** → 폭 **0.5em(7pt) 그대로**, 효과 1배(앞서 `latin_min_width: 60%`로 추정한 0.6em은 틀렸다 — 혼합 시험의 여분 폭은 아래 ③) ② "한글 한 글자 + 공백" 번갈아가 0에 23자, 1.0pt에 28자 → 공백 폭 0.5em, **효과 2배**(`text.condense_space_weight: 2`; 한글도 2배) ③ 한글↔영문·숫자 경계마다 글자 크기의 **1/4(3.5pt)가 더해진다**(Word "한글과 영문 사이 간격 자동 조절", `text.autospace: 25%`, `layout/lines.py::apply_autospace` — 좁히기와 무관): 한글 24 + 영문숫자 16자 @0, 27 + 20자 @1.0이 한 줄인 [11][12]를 경계 8·10곳으로 정확히 설명. `latin_min_width`는 지웠다. 테스트 `test_width_model_matches_word_measurements_for_ascii_space_and_mixed`가 68/80·23/28·40/47을 재현한다. **기호 경계 확정(2026-10-03 사용자 실측)**: 한글 5자 + `%`·`,`·`.`·`(` 되풀이가 모두 첫 줄 37자 → 한글↔기호 경계에는 1/4em이 **안 붙는다**(영문·숫자에만; 현재 코드 `is_latin = ascii and isalnum`이 맞다). **미확인**: 모호폭 문자(`·`·`※`·따옴표)의 간격 효과 배수. **버그도 같이 고침**: LLM이 줄인 문장이 좁히지 않고도 한 줄에 들어가면 `_fit`이 None을 돌려 줄인 글이 버려지고 원문이 그대로 나왔다(줄바꿈·왼쪽 끝 맞춤 모두 빠짐) — `shortened_text` 플래그.
- **다음 큰 일**: 줄글 → 정식보고서 편집, 다문서 → 요약·생성 — 계획은 [docs/roadmap-drafting.md](docs/roadmap-drafting.md).
- **진행 상태**: 1단계 probe(서식·형식·문장 통계, 층별 종결·길이, 주석 상자 포함)를 합성 docx로 검증하고 사내 문서 8건으로
  1차 실측했다. 다음: 샘플 리포트로 변환 결과와의 차이 확인 →
  `rules/*.yaml` 검수기(임계값은 실측으로 채움) → 변환 결과 채점기 → 파일럿 후 LLM 단계.
