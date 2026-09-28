#!/usr/bin/env bash
# Confluence 연결용 환경변수 템플릿.
#
#   cp scripts/confluence_env.example.sh scripts/confluence_env.sh
#
# 로 복사한 뒤 아래 값을 채우고
#
#   source scripts/confluence_env.sh
#
# 로 불러 쓴다 (실행이 아니라 source — 그래야 현재 쉘에 env가 남는다).
# confluence_env.sh(복사본, 실제 토큰이 든 파일)는 .gitignore에 이미 있어 커밋되지 않는다.

# ── 1. Confluence 주소 (사용자가 준 REST API 게이트웨이 주소, 2026-09-28) ─────
# 브라우저로 보는 위키 주소와 다른, REST 전용 서브도메인이다. 안내받은 주소가
# /rest/api로 끝나도 코드가 알아서 떼고 쓰므로 받은 그대로 넣으면 된다.
export CONFLUENCE_URL="http://api.confluence.samsungds.net/rest/api/"

# ── 2. 계정 — 둘 중 하나만 ──────────────────────────────────────────────
# Cloud: 계정 이메일 + API 토큰(Basic 인증). 아래 두 줄의 주석을 푼다.
#   Atlassian 계정 설정 → Security → API tokens 에서 발급.
# export CONFLUENCE_USERNAME="me@company.com"
# export CONFLUENCE_API_TOKEN="여기에_API_토큰"

# Server/Data Center(사내 자체 호스팅 — 위 주소를 보면 이쪽일 가능성이 높다):
# 개인 액세스 토큰(PAT, Bearer 인증)만 채운다.
#   Confluence 오른쪽 위 프로필 아이콘 → Personal Access Tokens 에서 발급.
#   CONFLUENCE_USERNAME은 반드시 비워 둔다 — 값이 있으면 Cloud(Basic)로 오인한다.
export CONFLUENCE_API_TOKEN="여기에_PAT"

# ── 3. 프록시 (필요하면) ────────────────────────────────────────────────
# 온프렘 LLM 연동 때 HTTP_PROXY가 사내 Squid로 요청을 우회시켜 막힌 적이 있었다
# (scripts/onprem_env.sh 참고). Confluence 접속도 안 되면 이 호스트를 추가해 본다.
# export NO_PROXY="api.confluence.samsungds.net,${NO_PROXY}"
