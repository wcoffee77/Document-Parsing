# 팀원용 설치·사용 안내 (doc2report)

각자 **자기 PC에 설치해서 자기 토큰으로** 쓰는 방식이다(공용 서버 없음).
**파이썬·uv·패키지를 따로 설치하지 않는다.** 받는 방법은 둘이다 — **① git 주소로 받기(권장, 아래 "git으로 받기")**:
`git clone` 한 번 하고 `start_webapp.bat`을 누르면 첫 실행 때 파이썬 실행 환경(runtime)을 자동으로 받는다.
**② 설치 묶음(zip)**: 필요한 것이 모두 들어 있어 풀기만 하면 된다(git이 없는 PC용).
관리자 권한, 인터넷(pypi.org 등), PowerShell 실행 정책 변경 모두 필요 없다.

> 왜 이렇게 했나: 처음 사내 PC에 설치할 때 pypi.org·astral.sh 차단, uv 설치 불가, `uv sync` 실패,
> wheelhouse 수작업, 프록시·인증서 문제로 시간이 많이 들었다. 그 과정을 전부 묶음 안으로 옮겼다.

## 1. 설치 (5분)

1. **설치 묶음 받기**: `doc2report-windows-x64.zip` (약 40MB)
   - 담당자가 사내 공유 폴더·메일로 준 파일, 또는 GitHub 저장소의 **Releases** 페이지
2. **차단 해제**: zip 파일 오른쪽 클릭 → 속성 → 아래쪽 **"차단 해제"** 체크 → 확인
   (인터넷에서 받은 파일은 Windows가 실행할 때마다 경고를 띄운다. 풀기 **전에** 해제해야 안의 파일 전부에 적용된다)
3. **풀기**: 원하는 곳에 푼다(예: `D:\doc2report`). 바탕화면·문서 폴더도 된다.
4. **실행**: 풀린 폴더의 `start_webapp.bat` 을 두 번 누른다.
   검은 창(서버)이 뜨고 브라우저가 자동으로 열린다. 검은 창은 쓰는 동안 닫지 않는다.
5. **사용자 등록**(처음 한 번): 브라우저에 뜬 등록 창을 채운다 → 아래 3번.

결과 문서는 `문서\doc2report` 폴더(`%USERPROFILE%\Documents\doc2report`)에 저장된다 — 새 버전 묶음을
다른 폴더에 풀어도 예전 결과가 그대로 보인다.

## 2. 안 될 때 — 먼저 `doctor.bat`

풀린 폴더의 **`doctor.bat`** 을 두 번 누르면 설치 상태를 한 번에 점검하고, 막힌 곳마다 **해결 방법**을
알려 준다. 결과는 같은 폴더에 `진단결과_날짜.txt`로도 저장된다 — 해결이 안 되면 **이 파일을 담당자에게**
보낸다(토큰 값은 들어가지 않는다).

| 점검 | 무엇을 보나 |
|---|---|
| 파이썬·패키지 | 묶음 안의 파이썬으로 도는지, 필요한 패키지가 다 있는지 |
| 코드 버전 | 묶음 빌드 번호(또는 git 브랜치·커밋 — main이 아니면 경고) |
| Word 문서 | 문서를 만들고 다시 열 수 있는지(사내 문서보안이 파일을 바꾸는 경우 대비) |
| 결과 폴더 | 쓸 수 있는지 |
| 글꼴 | 서식에 쓰는 글꼴(바탕체·맑은 고딕 등)을 찾는지 — 못 찾으면 표 폭이 약간 어긋날 수 있음 |
| PDF | Word가 있어 PDF로 바꿀 수 있는지 |
| 사용자 등록 | 등록됐는지, 토큰 주인 확인이 됐는지, 토큰 암호화(DPAPI)가 되는지 |
| 프록시 | PC의 프록시 설정이 사내 LLM·Confluence 요청을 가로채지 않는지 |
| Confluence·LLM | 실제로 연결되는지(토큰이 맞는지, 모델명이 서버에 있는지) |

흔한 문제:

| 증상 | 원인·해결 |
|---|---|
| `start_webapp.bat`을 눌러도 "Windows에서 PC를 보호했습니다" | 1-2 "차단 해제"를 안 했음 → "추가 정보 → 실행", 또는 zip을 차단 해제 후 다시 풀기 |
| 검은 창이 떴다 바로 닫힘 / 보안 프로그램이 python.exe를 막음 | 사내 보안 정책. `doctor.bat` 결과와 함께 담당자에게 — 보안팀 예외 등록이 필요할 수 있음(확인 필요) |
| 브라우저에 "이 화면은 잠겨 있습니다" | 열쇠 없는 주소로 열었음 → `start_webapp.bat`을 다시 실행하거나 검은 창에 나온 주소(`?k=…`)로 열기 |
| 화면이 반쯤 깨지거나 "서버를 다시 켜세요" 띠 | 예전 버전 서버가 떠 있음 → 검은 창을 모두 닫고 다시 실행 |
| Confluence "토큰 주인을 확인하지 못했습니다" | 주소가 `…/rest/api/`로 끝나는지, 토큰이 만료되지 않았는지 확인 → 다시 저장 |
| LLM 다듬기가 403으로 실패 | 사내 프록시가 가로챔. 등록된 LLM 주소는 자동으로 프록시 예외에 넣지만, 그래도 나면 `doctor.bat` 결과를 담당자에게 |
| 결과 .docx가 안 열림 | 사내 문서보안이 파일을 잠갔을 수 있음 — `doctor.bat`의 "Word 문서" 항목 확인 |

## 3. 사용자 등록

| 칸 | 넣을 값 |
|---|---|
| 사용자 이름 | 내 이름 |
| Confluence REST 주소 | 담당자가 알려 준 REST 게이트웨이 주소(`…/rest/api/`) |
| 개인 액세스 토큰(PAT) | Confluence → 오른쪽 위 프로필 → **개인 액세스 토큰** → 토큰 만들기. 만료일을 짧게(예: 90일) 잡는 것을 권장 |
| 로그인 이메일 | 사내 Confluence(Server/DC)는 **비워 둔다** |
| 온프렘 LLM 주소·모델명 | 담당자가 알려 준 값. LLM을 안 쓰면 비워 둔다 |

**저장하고 토큰 확인**을 누르면 Confluence에 "이 토큰의 주인이 누구냐"를 물어 화면 위에
`Confluence: 홍길동 (hong.gd)의 토큰 …abcd` 처럼 표시한다. 등록한 이름과 토큰 주인이 다르면 노란색으로
경고한다 — 남의 토큰이 들어가 있다는 뜻이니 바로 고친다. 나중에 고칠 때는 화면 오른쪽 위 `사용자: 이름`을 누른다.

## 4. 토큰은 어떻게 보호되나

| 위험 | 막는 방법 |
|---|---|
| 프로그램 폴더를 복사·공유하거나 실수로 git에 올림 | 토큰은 프로그램 폴더가 아니라 **내 Windows 사용자 폴더**(`%APPDATA%\doc2report\account.json`)에만 저장 |
| 그 파일이 다른 PC나 다른 계정으로 새어 나감 | **Windows DPAPI 암호화** — 같은 PC의 같은 Windows 로그인 계정에서만 풀린다 |
| 화면·로그에 토큰이 보임 | 서버는 토큰을 브라우저로 돌려보내지 않는다. 끝 4자리만 표시 |
| 사내망 우회(PowerShell) 때 명령 기록·보안 로그에 토큰이 남음 | 토큰은 명령 문자열이 아니라 그 프로세스 환경변수로만 넘긴다 |
| 다른 PC에서 내 서버에 접속 | 서버는 `127.0.0.1`(내 PC)에서만 열린다 |
| 같은 PC의 다른 사용자·다른 프로그램이 내 서버로 변환 | **접속 열쇠**(`?k=…`)가 있는 브라우저만 API를 쓸 수 있다. 열쇠 파일도 내 사용자 폴더에 있다 |
| 악성 웹사이트가 내 브라우저를 시켜 서버를 호출 | 전용 헤더 확인 + 주소(Host)가 127.0.0.1/localhost가 아니면 거절(DNS 리바인딩 차단) |

남는 위험: 잠기지 않은 내 PC를 다른 사람이 직접 쓰는 경우는 막지 못한다(자리를 비울 때는 Windows 잠금 `Win+L`).
토큰이 샜다고 의심되면 Confluence에서 그 토큰을 **폐기**하고 새로 만들어 등록한다. 등록을 지우려면
등록 창의 **등록 삭제**를 누른다.

## 5. 업데이트

새 묶음 zip을 받아 **새 폴더에 풀고** 그 폴더의 `start_webapp.bat`을 쓴다(예전 폴더는 지워도 된다).
사용자 등록(`%APPDATA%\doc2report`)과 결과 문서(`문서\doc2report`)는 폴더 밖에 있어 그대로 이어진다.
예전 서버 창이 떠 있으면 새로 켤 때 자동으로 넘겨받는다.

## 6. git으로 받기 (권장 — 주소만 공유하면 된다)

필요한 것: **Git for Windows**와, 이 저장소에 `git clone`·`git pull`이 되는 네트워크(그 외 설치 없음).

```powershell
git clone <저장소 주소> doc2report
cd doc2report
```

1. 받은 직후 **한 번만** `exclude_samples.bat`을 실행한다. 시험용 샘플(`samples\`, 약 30개 문서)을 이 PC의 폴더에서 숨긴다
   (저장소에서 지우는 것이 아니라 내 폴더에서만 숨기는 것이라 `git pull`은 그대로 되고 `git status`에도 안 뜬다).
   직접 명령으로 하려면 `git sparse-checkout set --no-cone "/*" "!/samples/"`, 다시 받고 싶으면 `git sparse-checkout disable`.
2. `start_webapp.bat`을 두 번 누른다. **첫 실행에서만** 검은 창에 `Downloading the Python runtime…`이 뜨고 1~2분 걸린다
   (파이썬과 패키지, 수십 MB). 끝나면 브라우저가 자동으로 열린다.
3. **업데이트**: 검은 창을 닫고 → `git pull` → `start_webapp.bat`. 패키지 구성이 바뀐 버전이면 `start_webapp.bat`이 알아서
   새 runtime을 다시 받는다(바뀌지 않았으면 아무것도 안 받는다). 작업 브랜치는 `main` 하나다.

### 어떻게 동작하나
- 파이썬과 패키지(`runtime`)는 같은 저장소의 **`runtime-win64` 브랜치**에 있다(담당자의 CI가 만들어 올린다). `main`에는 없다.
- `scripts\ensure_runtime.bat`이 첫 실행 때 그 브랜치를 `runtime\` 폴더로 **얕게 복제**(`git clone --depth 1`)한다.
  이후에는 `scripts\onprem-requirements.txt`가 바뀌었을 때만 `git fetch`로 갱신한다(두 곳의 패키지 목록을 git이 계산한
  식별자 `REQ_BLOB`으로 비교하므로 줄바꿈 설정과 무관하다).
- `runtime\`은 `.gitignore`에 있어 `git status`에 안 뜨고 `git pull`이 건드리지 않는다.

### 안 될 때
| 증상 | 원인·해결 |
|---|---|
| `git was not found` | Git for Windows를 설치한다. 못 깔면 설치 묶음 zip의 `runtime` 폴더를 이 폴더에 복사(그러면 자동 받기를 건너뛴다) |
| `Could not download the Python runtime` | 이 PC에서 저장소에 접근되는지 확인(`git pull`이 되는가). 사내 프록시가 막으면 담당자에게 `doctor.bat` 결과와 함께 문의 |
| `The runtime folder exists but is incomplete` | 받다 중단된 `runtime` 폴더를 지우고 `start_webapp.bat`을 다시 실행 |
| 받았는데 `runtime이 이 코드보다 오래된 패키지 구성`(doctor) | 담당자의 `runtime-win64` 빌드가 아직 안 끝난 것. 몇 분 뒤 `start_webapp.bat`을 다시 실행 |
| 검은 창이 바로 닫힘 / 보안 프로그램이 `python.exe`를 막음 | 사내 보안 정책. `doctor.bat` 결과와 함께 담당자에게(보안팀 예외 등록이 필요할 수 있음 — 확인 필요) |

(`runtime` 없이 uv로 쓰는 방법은 [onprem-first-run.md](onprem-first-run.md)의 오프라인 설치.)

## 담당자용: runtime 브랜치와 설치 묶음

**git 배포(`runtime-win64` 브랜치)**: `main`에 push하면 GitHub Actions(`windows` 작업)가 ① 전체 테스트 → ② `scripts/onprem-requirements.txt`의
git 식별자(blob id)가 `runtime-win64` 브랜치의 `REQ_BLOB`과 다를 때만 runtime을 새로 만들어 그 브랜치에 올리고(**force push, 이력 1개 —
저장소가 커지지 않게**) → ③ **받는 사람처럼 새로 `git clone`해 첫 실행 자동 받기·두 번째 실행엔 안 받기·진단·변환**까지 확인한다
(`git-install-check`). 즉 **패키지를 바꾸면** `uv lock` → `uv export --no-dev --no-hashes --no-emit-project -o scripts/onprem-requirements.txt`
→ `main`에 push하면 끝이다(`lock-sync` 작업이 두 파일이 같은지 검사한다). 팀원은 다음 실행 때 자동으로 새 runtime을 받는다.
새 runtime이 만들어지는 몇 분 동안은 팀원의 doctor가 "오래된 패키지 구성"으로 알려 줄 수 있다(정상).

**설치 묶음(zip)** (git이 없는 PC용):

`main`에 push하면 GitHub Actions(`windows` 작업)가 Windows 머신에서 ① 전체 테스트 ② 묶음 만들기
③ **받은 사람처럼 다른 폴더에 풀어 시스템 파이썬 없이 진단·변환·웹 서버 실행**까지 해 본다.
통과하면 작업 화면의 Artifacts에서 `doc2report-windows-x64`를 내려받아 사내 공유 폴더에 올린다.
버전 태그를 달면 Releases에도 자동으로 올라간다:

```powershell
git tag v0.2.0
git push origin v0.2.0
```

직접 만들려면 인터넷이 되는 Windows PC(64비트 파이썬 3.11+)에서
`powershell -ExecutionPolicy Bypass -File packaging\build_windows_bundle.ps1` → `dist\doc2report-windows-x64.zip`.
