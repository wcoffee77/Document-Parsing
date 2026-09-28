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

# ── 1. Confluence 주소 ──────────────────────────────────────────────────
# Cloud(*.atlassian.net)면 끝에 /wiki 포함, Server/Data Center(사내 자체 호스팅)면
# 보통 /wiki 없이 도메인만.
$env:CONFLUENCE_URL = "https://wiki.회사.com"

# ── 2. 계정 — 둘 중 하나만 ──────────────────────────────────────────────
# Cloud: 계정 이메일 + API 토큰(Basic 인증). 아래 두 줄의 주석을 푼다.
#   Atlassian 계정 설정 → Security → API tokens 에서 발급.
# $env:CONFLUENCE_USERNAME = "me@company.com"
# $env:CONFLUENCE_API_TOKEN = "여기에_API_토큰"

# Server/Data Center: 개인 액세스 토큰(PAT, Bearer 인증)만 채운다.
#   Confluence 오른쪽 위 프로필 아이콘 → Personal Access Tokens 에서 발급.
#   CONFLUENCE_USERNAME은 반드시 비워 둔다 — 값이 있으면 Cloud(Basic)로 오인한다.
$env:CONFLUENCE_API_TOKEN = "여기에_PAT"

# ── 3. 프록시 (필요하면) ────────────────────────────────────────────────
# 온프렘 LLM 연동 때 HTTP_PROXY가 사내 Squid로 요청을 우회시켜 막힌 적이 있었다
# (scripts/onprem_env.ps1 참고). Confluence 접속도 안 되면 그 호스트를 여기 추가.
# $env:NO_PROXY = "wiki.회사.com," + $env:NO_PROXY
