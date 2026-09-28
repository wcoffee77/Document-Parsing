#!/usr/bin/env bash
# 사내 온프렘 LLM(모델명: thinkingcap) 연결용 환경변수.
#
#   source scripts/onprem_env.sh
#
# 로 불러 쓴다 (실행이 아니라 source — 그래야 현재 쉘에 env가 남는다).
# API 인증이 필요하면 DOC2REPORT_LLM_API_KEY 줄의 주석을 풀고 값을 채운다.

export DOC2REPORT_LLM_BASE_URL="http://75.12.15.121:8080/v1"
export DOC2REPORT_MODEL="thinkingcap"
# export DOC2REPORT_LLM_API_KEY="여기에_토큰"
