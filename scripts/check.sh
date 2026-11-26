#!/usr/bin/env bash
# 전체 검사: 테스트 → 사이트 생성 → 만들어진 사이트 검사.
# 작업을 끝내기 전에, 그리고 CI에서 돈다. 하나라도 실패하면 0이 아닌 값으로 끝난다.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m unittest discover -s tests
python3 sitegen/build.py
python3 scripts/check_site.py
