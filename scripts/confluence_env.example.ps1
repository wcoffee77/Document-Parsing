# Confluence 연결용 환경변수 템플릿.
#
#   copy scripts\confluence_env.example.ps1 scripts\confluence_env.ps1
#
# 로 복사한 뒤 아래 값을 채우고
#
#   . .\scripts\confluence_env.ps1
#
# 로 불러 쓴다 (맨 앞 점 + 공백 필수 — 그래야 현재 세션에 env가 남는다).
# confluence_env.ps1(복사본, 실제 토큰이 든 파일)은 .gitignore에 이미 있어 커밋되지 않는다.

# ── 1. Confluence 주소 (사용자가 준 REST API 게이트웨이 주소, 2026-09-28) ─────
# 브라우저로 보는 위키 주소와 다른, REST 전용 서브도메인이다. 안내받은 주소가
# /rest/api로 끝나도 코드가 알아서 떼고 쓰므로 받은 그대로 넣으면 된다.
$env:CONFLUENCE_URL = "http://api.confluence.samsungds.net/rest/api/"

# ── 2. 계정 — 둘 중 하나만 ──────────────────────────────────────────────
# Cloud: 계정 이메일 + API 토큰(Basic 인증). 아래 두 줄의 주석을 푼다.
#   Atlassian 계정 설정 → Security → API tokens 에서 발급.
# $env:CONFLUENCE_USERNAME = "me@company.com"
# $env:CONFLUENCE_API_TOKEN = "여기에_API_토큰"

# Server/Data Center(사내 자체 호스팅 — 위 주소를 보면 이쪽일 가능성이 높다):
# 개인 액세스 토큰(PAT, Bearer 인증)만 채운다.
#   Confluence 오른쪽 위 프로필 아이콘 → Personal Access Tokens 에서 발급.
#   CONFLUENCE_USERNAME은 반드시 비워 둔다 — 값이 있으면 Cloud(Basic)로 오인한다.
$env:CONFLUENCE_API_TOKEN = "여기에_PAT"

# ── 3. 프록시 (필요하면) ────────────────────────────────────────────────
# 온프렘 LLM 연동 때 HTTP_PROXY가 사내 Squid로 요청을 우회시켜 막힌 적이 있었다
# (scripts/onprem_env.ps1 참고). Confluence 접속도 안 되면 이 호스트를 추가해 본다.
# $env:NO_PROXY = "api.confluence.samsungds.net," + $env:NO_PROXY

# ── 4. 사내망 SSL 인증서 문제 (2026-09-29, 사내 LLM 진단) ──────────────────
# 사내 프록시가 자체 발급한 인증서로 HTTPS를 중계하면, 그 루트 인증서가 파이썬
# 기본 CA 번들(certifi)에는 없어서 "SSL 인증서 검증 실패"가 날 수 있다. 사내
# 루트 인증서(.crt/.pem) 파일 경로를 구했으면 여기 넣는다 — httpx는
# REQUESTS_CA_BUNDLE을 자동으로 안 읽어서 doc2report가 이 값을 직접 확인해 쓴다.
# $env:CONFLUENCE_CA_BUNDLE = "C:\certs\samsungsemi-prx.com.crt"

# ── 5. 그래도 안 되면: httpx가 403/SSL 오류로 막힐 때 (2026-09-29 실측) ────
# doc2report는 httpx가 403을 받거나 SSL/연결에 실패하면 Windows에서 자동으로
# PowerShell(Invoke-WebRequest, Windows 인증서 저장소를 그대로 씀)로 한 번 더
# 시도한다 — 보통은 아래를 켤 필요가 없다. 자동 대체도 안 통하면 이 줄의
# 주석을 풀어 처음부터 PowerShell만 쓰게 한다.
# $env:DOC2REPORT_CONFLUENCE_TRANSPORT = "powershell"
