#!/usr/bin/env bash
# doc2report 웹 화면 켜기 (macOS/Linux). scripts/confluence_env.sh, onprem_env.sh가 있으면 먼저 불러온다.
set -euo pipefail
cd "$(dirname "$0")/.."
for name in confluence_env.sh onprem_env.sh; do
  if [ -f "scripts/$name" ]; then . "scripts/$name"; echo "환경 설정 불러옴: scripts/$name"; fi
done
exec uv run doc2report web "$@"
