#!/usr/bin/env bash
# Claude Code Stop hook. Claude가 턴을 끝내려 할 때마다 돈다.
# 테스트가 깨졌거나, 소스를 고치고 사이트를 다시 만들지 않았거나, 만들어진 사이트에
# 끊어진 링크 같은 문제가 있으면 2로 끝나서 Claude를 돌려보낸다.
cd "$(dirname "$0")/../.." || exit 0
out=$(python3 -m unittest discover -s tests 2>&1) || { echo "테스트가 실패했습니다." >&2; echo "$out" | tail -40 >&2; exit 2; }
out=$(python3 scripts/check_site.py 2>&1) || { echo "$out" | tail -40 >&2; exit 2; }
exit 0
