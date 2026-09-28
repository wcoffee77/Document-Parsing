# 사내 온프렘 LLM(모델명: thinkingcap) 연결용 환경변수.
#
#   . .\scripts\onprem_env.ps1
#
# 으로 불러 쓴다 (맨 앞 점 + 공백 필수 — 그래야 현재 세션에 env가 남는다).
# API 인증이 필요하면 DOC2REPORT_LLM_API_KEY 줄의 주석을 풀고 값을 채운다.

$env:DOC2REPORT_LLM_BASE_URL = "http://75.12.15.121:8000/v1"
$env:DOC2REPORT_MODEL = "thinkingcap"
# $env:DOC2REPORT_LLM_API_KEY = "여기에_토큰"
