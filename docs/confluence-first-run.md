# 사내 PC 첫 실행 가이드 — Confluence 연동 테스트

사내 PC에서 **이 문서 순서만 그대로 따라 하면** Confluence 페이지를 실제로 읽어
`.docx`로 변환하는 것까지 확인할 수 있다. 걸리는 게 있으면 7번으로 가서 클로드에
전달할 내용을 챙긴다.

> [온프렘 LLM 연동 가이드](onprem-first-run.md)와 짝이 되는 문서다. `uv`
> 오프라인 설치, `--offline --no-sync`, PowerShell 인코딩 문제 등 공통되는
> 부분은 그 문서를 그대로 참고하면 된다 — 여기서는 Confluence 쪽만 다룬다.

## 지금 상태 (2026-09-28)

API 토큰 발급에 **사내 승인 절차가 필요해 진행 중**이다. 그 결과만 기다리면
되고, 나머지(주소 확정, 코드 수정)는 이미 끝나 있다.

**승인이 나서 토큰을 받으면, 이 문서 나머지는 안 보고 아래만 하면 된다:**

```powershell
notepad scripts\confluence_env.ps1
```
파일이 없다면(아직 한 번도 안 만들었다면) 먼저
`copy scripts\confluence_env.example.ps1 scripts\confluence_env.ps1`.
파일을 열면 이 줄이 보인다 — 따옴표 안을 받은 토큰으로 바꾸고 저장:
```powershell
$env:CONFLUENCE_API_TOKEN = "여기에_PAT"
```
저장 후 같은 PowerShell 창에서:
```powershell
. .\scripts\confluence_env.ps1
```
여기까지가 **토큰을 입력하는 전부**다. 이어서 검증하려면 3번(REST API 직접
확인)부터 이어서 하면 된다. 아래 0~2번은 이미 끝났으므로 다시 안 해도 된다
(맨 처음 실행이거나 확인차 다시 보고 싶을 때만 참고).

## 0. 사전 준비물

- [ ] 이 브랜치(`claude/confluence-document-conversion-dtygn4`)로 코드가 최신인지
      (`git log -1 --oneline` — 이 문서를 만든 커밋 이후인지 확인)
- [x] **REST API 주소 확정**: `http://api.confluence.samsungds.net/rest/api/`
      (`scripts/confluence_env.example.ps1`/`.sh`에 이미 반영해 둠). 브라우저로
      보는 위키 주소와는 다른 REST 전용 게이트웨이다. `http`(평문)라 사내망
      바깥에서는 안 열릴 수 있다 — 사내 PC/VPN에서 실행 전제.
- [ ] **Cloud/Server-DC 판별**: 이 주소만 봐서는 API 게이트웨이를 자체 구축한
      Server/Data Center로 보이지만(회사 도메인 서브호스트), 확정은 아니다.
      1번에서 Personal Access Token 발급 메뉴가 보이면 Server/DC, 안 보이고
      Atlassian 계정 자체의 API tokens 메뉴만 있으면 Cloud.
- [ ] 테스트로 변환해 볼 **실제 접근 권한이 있는 페이지** 하나(URL 또는 페이지 ID)
- [ ] **API 토큰 — 사내 승인 절차 진행 중.** Server/DC면 개인 액세스 토큰(PAT)만,
      Cloud면 계정 이메일 + API 토큰. (발급 방법은 1번 참고. **받으면 위
      "지금 상태" 박스에 적힌 대로 입력.**)

## 1. 인증 정보 발급

**Cloud**: Atlassian 계정 → 오른쪽 위 프로필 → **계정 설정** → **Security** →
**API tokens** → **Create API token**. 이메일 + 이 토큰을 Basic 인증으로 쓴다.

**Server/Data Center**: Confluence 오른쪽 위 프로필 아이콘 → **Personal Access
Tokens** → **Create token**. 이 토큰 하나만 Bearer 인증으로 쓴다(계정 이메일 불필요).

> 어느 쪽인지 헷갈리면 사내 IT/플랫폼팀에 "Confluence가 Cloud인지 Server/Data
> Center인지"만 물어봐도 된다.

## 2. 환경변수 설정

템플릿을 복사해서 값을 채운다 (실제 토큰이 든 복사본은 `.gitignore`에 이미
있어 커밋되지 않는다).

```powershell
copy scripts\confluence_env.example.ps1 scripts\confluence_env.ps1
notepad scripts\confluence_env.ps1      # CONFLUENCE_URL, 토큰 채우기
. .\scripts\confluence_env.ps1          # 맨 앞 ". " 필수
```
```bash
cp scripts/confluence_env.example.sh scripts/confluence_env.sh
vi scripts/confluence_env.sh            # CONFLUENCE_URL, 토큰 채우기
source scripts/confluence_env.sh
```

**Cloud**면 템플릿에서 `CONFLUENCE_USERNAME` 줄의 주석도 풀어야 한다.
**Server/DC**면 `CONFLUENCE_USERNAME`을 절대 채우지 않는다 — 값이 있으면
코드가 Cloud로 오인해 잘못된 인증 방식(Basic)을 쓴다.

> **PowerShell 실행 정책으로 `.ps1`이 막히면** (온프렘 LLM 가이드에서 겪은 것과
> 같은 문제): 값을 직접 입력해도 된다.
> ```powershell
> $env:CONFLUENCE_URL = "https://wiki.회사.com"
> $env:CONFLUENCE_API_TOKEN = "여기에_토큰"
> ```
> 이 값은 **현재 창에서만 유지**된다.

**제대로 들어갔는지 확인** (토큰 값 전체를 화면에 띄우지 않고 길이·앞 4자만):
```powershell
"길이=$($env:CONFLUENCE_API_TOKEN.Length), 시작=$($env:CONFLUENCE_API_TOKEN.Substring(0,[Math]::Min(4,$env:CONFLUENCE_API_TOKEN.Length)))"
```
길이가 0이거나 `여기에_PAT`가 그대로 보이면 저장을 안 했거나 `.` 없이
스크립트를 실행한 것이다 — `notepad`로 다시 열어 확인하고, `.` 을 빠뜨리지
않았는지(`. .\scripts\confluence_env.ps1`) 다시 확인.

## 3. REST API 자체를 먼저 확인 (doc2report 실행 전)

doc2report를 거치지 않고 Confluence REST API에 직접 붙어서, 인증과 페이지 ID가
맞는지부터 확인한다. `123456`은 0번에서 정한 테스트 페이지 ID로 바꾼다.

`$base`를 먼저 만든다 — `CONFLUENCE_URL`에 `/rest/api`가 이미 있든(우리 경우처럼)
없든 doc2report 코드와 똑같은 방식으로 맞춰 준다:
```powershell
$base = $env:CONFLUENCE_URL.TrimEnd('/')
if ($base -notmatch '/rest/api$') { $base += '/rest/api' }
```

**Server/DC (PAT, Bearer) — 우리 경우 이쪽일 가능성이 높음:**
```powershell
$headers = @{ Authorization = "Bearer $env:CONFLUENCE_API_TOKEN" }
Invoke-RestMethod -Uri "$base/content/123456?expand=body.storage" -Headers $headers
```

**Cloud (이메일 + API 토큰, Basic):**
```powershell
$pair = "$env:CONFLUENCE_USERNAME`:$env:CONFLUENCE_API_TOKEN"
$basic = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($pair))
$headers = @{ Authorization = "Basic $basic" }
Invoke-RestMethod -Uri "$base/content/123456?expand=body.storage" -Headers $headers
```

확인할 것:

- [ ] `title` 필드에 실제 페이지 제목이 나오는가
- [ ] `body.storage.value`에 그 페이지 내용으로 보이는 HTML 태그(`<p>`, `<table>` 등)가 있는가

> **PowerShell 한글 인코딩 주의**: `title`·본문에 한글이 깨져 보이면
> `Invoke-RestMethod`가 응답을 잘못된 인코딩으로 먼저 디코딩한 것이다
> (온프렘 LLM 가이드 2번에서 겪은 것과 같은 원인). 이 단계는 확인용이라
> 태그가 제대로 보이는지만 보면 되고, 한글 내용 자체는 4번(실제 변환) 결과인
> `.docx`로 확인하면 된다 — 그쪽은 이 인코딩 문제와 무관하다.
>
> 401이 나오면 토큰/인증 방식(Cloud vs Server-DC) 다시 확인, 403이면 그
> 페이지에 대한 접근 권한 확인, 404면 페이지 ID나 `CONFLUENCE_URL`(끝에
> `/wiki` 필요 여부) 확인, 아예 응답이 없으면(타임아웃) 프록시 문제일 수
> 있다 — 2번 끝의 `NO_PROXY` 참고.

## 4. 실제 변환

```powershell
.\uv.exe run --offline --no-sync doc2report convert https://wiki.회사.com/pages/viewpage.action?pageId=123456 -o out\보고서.docx --report out\변경내역.md
```

여기 넣는 URL은 **브라우저 주소창의 페이지 링크**다 — `CONFLUENCE_URL`(REST
게이트웨이 주소)과는 다른 도메인이어도 된다. 코드는 이 URL에서 숫자 페이지
ID만 뽑아내고, 실제 요청은 `CONFLUENCE_URL` 쪽으로 보낸다. 지원하는 URL 형태:

| 형태 | 예 |
|---|---|
| Cloud | `.../wiki/spaces/TEAM/pages/123456/제목` |
| Server/DC 고전 URL | `.../pages/viewpage.action?pageId=123456` |
| 페이지 ID 숫자만 | `123456` |

**단축 링크**(`.../x/AbCd`)는 안 된다 — 페이지를 열어서 위 형태 중 하나로 된
실제 URL을 브라우저 주소창에서 복사해 쓴다.

## 5. 결과 확인 (이 순서로)

1. **`out/변경내역.md`를 가장 먼저 연다.** 이 도구가 모르는 매크로(레이아웃,
   특수 패널 등)를 만나면 "지원하지 않는 매크로를 건너뜀: <매크로 이름>" 또는
   "매크로 '...'을(를) 본문만 펼쳐서 처리함" 같은 노트가 남는다 — 그 부분
   내용이 `.docx`에서 빠졌거나 서식이 단순화됐다는 뜻이니 꼭 확인.
2. `out/보고서.docx`를 Word로 열어 육안 확인. 특히:
   - 병합된 셀(가로/세로로 합쳐진 표)이 있는 페이지라면 그 표가 제대로
     합쳐져 나오는지 — 이게 이번 Confluence 연동을 만든 핵심 이유다(마크다운
     경유로는 병합 정보가 사라진다).
   - 이미지가 있었다면 제대로 삽입됐는지.
3. 표 배치만 먼저 보고 싶으면: `.\uv.exe run --offline --no-sync doc2report check <URL>`

## 6. 잘 되면 — 다음 페이지들로 확장

한 페이지가 잘 되면, 표·병합 셀·패널이 각각 다른 방식으로 쓰인 페이지 몇
개를 더 시도해서 `변경내역.md`에 낯선 매크로 노트가 쌓이는지 본다. 자주
나오는 매크로가 있으면 그 이름을 클로드에 알려주면
`parsers/confluence_storage.py`에 지원을 추가할 수 있다.

## 7. 문제가 생기면 클로드에 전달할 것

- 3번(REST API 직접 호출)의 HTTP 상태 코드와 응답 본문(토큰 등 민감정보는
  가려서)
- 4번 실행 시 뜬 에러 메시지 전체
- `out/변경내역.md`에 남은 "지원하지 않는 매크로" 계열 노트 — 어떤 페이지의
  어떤 내용이었는지도 같이 (매크로 이름만으로는 어떻게 펼쳐야 할지 판단하기
  어려운 경우가 많다)

이 정보가 있으면 `src/doc2report/sources/confluence.py`,
`src/doc2report/parsers/confluence_storage.py`를 그 자리에서 고칠 수 있다.
