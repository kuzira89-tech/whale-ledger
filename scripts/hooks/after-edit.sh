#!/usr/bin/env bash
# Claude Code PostToolUse hook (Edit|Write 뒤).
# 파이썬·JSON 파일을 고칠 때마다 문법과 테스트를 확인한다. 실패하면 2로 끝나고,
# stderr에 적은 내용이 Claude에게 돌아가 바로 고치게 된다. 1로 끝나면 그냥 지나간다.
cd "$(dirname "$0")/../.." || exit 0
file=$(python3 -c 'import json,sys; print((json.load(sys.stdin).get("tool_input") or {}).get("file_path",""))' 2>/dev/null) || exit 0
case "$file" in
  *.py)   out=$(python3 -m py_compile "$file" 2>&1) || { echo "$out" >&2; exit 2; } ;;
  *.json) out=$(python3 -c 'import json,sys; json.load(open(sys.argv[1], encoding="utf-8"))' "$file" 2>&1) \
            || { echo "JSON이 깨졌습니다: $file" >&2; echo "$out" | tail -3 >&2; exit 2; } ;;
  *)      exit 0 ;;
esac
out=$(python3 -m unittest discover -s tests 2>&1) || { echo "$out" | tail -40 >&2; exit 2; }
exit 0
