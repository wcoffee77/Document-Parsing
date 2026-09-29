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

## 검증 방법

```bash
uv run pytest                           # 200개
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

**아직 판단 안 한 것**: 원문 말머리가 **없는** 제목 아래 일반 문단은 여전히 프로파일
말머리("□"/"-")를 받는다(예전부터의 `headings_as_levels` 동작). Confluence에서 "잘 정리된
문장"을 그대로 두려면 이것도 끄는 게 맞을 수 있다 — 사용자 실측 피드백 대기.

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

## 앞으로 계획: WebApp화 (사용자가 기록만 요청, 아직 시작 안 함 — 2026-09-28)

지금은 PowerShell에서 CLI 명령어로 쓰고 있지만, **성능이 어느 정도 안정화되면
프론트엔드를 입혀 웹앱으로 만들 예정**이다. 이 전환 자체는 아직 시작 전이고,
지금은 다음 세션에서 참고할 설계 메모만 남긴다.

**왜 지금 이게 문제인가**: 지금 CLI 방식은 `CONFLUENCE_URL`/`CONFLUENCE_API_TOKEN`,
`DOC2REPORT_LLM_BASE_URL`, `NO_PROXY` 등을 **PowerShell 프로세스 환경변수**로
들고 있다. `. .\scripts\confluence_env.ps1` / `onprem_env.ps1`로 불러 쓰는데,
이 값은 그 PowerShell 창에만 살아 있어서 **창을 닫았다 새로 열면 다시 불러와야
한다**(사용자가 지난 세션에서 겪은 "매번 다시 설정해야 하는" 불편이 바로 이거다).
CLI를 쓰는 동안은 이게 최선이었다 — 토큰을 코드나 파일에 영구히 박아 두지 않기
위한 의도적 설계다.

**웹앱으로 가면 이 전제 자체가 달라진다**: 웹앱은 서버 프로세스가 계속 떠 있고
브라우저는 그냥 클라이언트다 — "PowerShell 창을 새로 연다"는 개념이 없어진다.
그러니 지금처럼 매번 스크립트를 `. `으로 불러오는 방식이 아니라, **서버 프로세스가
시작될 때 한 번만 인증 정보를 읽어 들이는 구조**가 맞다. 구체적으로 그때 정할 것:

- 인증 정보를 어디서 읽을지: 환경변수는 그대로 쓰되 **서비스 시작 스크립트
  (Windows 서비스든, 작업 스케줄러든, 그냥 시작 프로그램에 등록한 배치 파일이든)가
  `confluence_env.ps1`/`onprem_env.ps1`을 로드한 뒤 그 프로세스에서 서버를 띄우는
  형태**로 하면 지금 스크립트 자산을 거의 그대로 재사용할 수 있다. 다만 토큰을
  매번 사람이 타이핑해 넣는 지금 방식(`notepad`로 파일 열어 채우기)은 웹앱에서는
  안 맞는다 — 최초 1회 설정 화면(또는 Windows 자격 증명 관리자/환경변수 영구
  등록) 같은 게 필요할 것.
- `Set-ExecutionPolicy -Scope Process`도 그 서비스/시작 스크립트를 등록할 때
  한 번만 해결하면 되고, 사용자가 매번 신경 쓸 일이 없어진다.
- 지금 `.gitignore`에 넣어 둔 `scripts/confluence_env.ps1`(실제 토큰 있는 파일)
  전략이 웹앱에서도 "코드/저장소에 시크릿을 넣지 않는다"는 원칙 자체는 유지할
  근거가 된다 — 다만 구현은 그때 웹앱 프레임워크(로컬 설정 파일? OS 자격 증명
  저장소? .env + 서버 프로세스 전용?)에 맞춰 다시 설계해야 한다.

**변환 옵션 화면 (2026-09-29 사용자 계획)**: 웹앱에서는 문서 생성 시 변환 옵션을
고르게 하되 **"자동 판단" 모드와 "사용자가 적용할 규칙을 체크" 모드를 나눈다**.
지금 구조가 이미 그 밑바탕이다 — 규칙 하나하나가 프로파일의 `text.*`/`tables.*` 값
(예: `polish`, `keep_leading_markers`, `merge_short_items`, `table_captions`,
`max_font_spread`)이라, 체크박스는 이 값을 `with_overrides`/`model_copy`로 덮어쓰기만
하면 된다(코드 분기 추가 없이). "자동 판단"은 지금의 `auto_profile()`(소스 종류로
default/confluence 선택)을 확장하는 자리 — 예: 글자 수·표 개수로 "내용 많은 문서"를
판정해 confluence 계열 서식을 고르는 것.

**지금 할 일은 없음** — 이 절은 구현 시작할 때 "왜 지금 이렇게 되어 있는지"와
"그때 뭘 다시 설계해야 하는지"를 빨리 떠올리기 위한 메모다.
