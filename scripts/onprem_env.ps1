# 사내 온프렘 LLM(모델명: thinkingcap) 연결용 환경변수.
#
#   . .\scripts\onprem_env.ps1
#
# 으로 불러 쓴다 (맨 앞 점 + 공백 필수 — 그래야 현재 세션에 env가 남는다).
# API 인증이 필요하면 DOC2REPORT_LLM_API_KEY 줄의 주석을 풀고 값을 채운다.

$env:DOC2REPORT_LLM_BASE_URL = "http://75.12.15.121:8000/v1"
$env:DOC2REPORT_MODEL = "thinkingcap"
# $env:DOC2REPORT_LLM_API_KEY = "여기에_토큰"

# 이 PC의 HTTP_PROXY(사내 Squid, 12.26.204.100:8000)를 거치면 그 프록시의
# ACL이 75.12.15.121을 차단해 403이 난다(실제로 겪음, 원인 확인 완료).
# httpx가 표준 프록시 환경변수를 그대로 따르므로 이 호스트만 프록시 예외로 뺀다.
# 정식 해결책은 네트워크팀에 이 목적지에 대한 프록시 예외 등록을 요청하는 것.
$env:NO_PROXY = "75.12.15.121"
