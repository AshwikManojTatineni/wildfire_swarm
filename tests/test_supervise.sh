#!/usr/bin/env bash
# Behaviour tests for scripts/cluster/supervise.sh. Run: bash tests/test_supervise.sh
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUP="$HERE/scripts/cluster/supervise.sh"
export NCR_RUN_DIR; NCR_RUN_DIR="$(mktemp -d)"
export NCR_GRACE_S=3
fail=0
pass() { echo "PASS $1"; }
bad()  { echo "FAIL $1: $2"; fail=1; }

# (a) all children exit 0 -> supervisor exits 0, logs written
bash "$SUP" A 'sleep 1; echo hello; exit 0' B 'sleep 1; exit 0'; rc=$?
[[ $rc -eq 0 ]] && grep -q hello "$NCR_RUN_DIR/logs/A.log" && pass a || bad a "rc=$rc"

# (b) first non-zero code propagates, sibling is stopped quickly
start=$SECONDS
bash "$SUP" A 'sleep 1; exit 3' B 'sleep 60; echo SHOULD_NOT_FINISH'; rc=$?
el=$((SECONDS - start))
if [[ $rc -eq 3 && $el -lt 20 ]] && ! grep -q SHOULD_NOT_FINISH "$NCR_RUN_DIR/logs/B.log"; then pass b
else bad b "rc=$rc elapsed=${el}s"; fi

# (c) TERM to the supervisor stops all children, non-zero exit
bash "$SUP" A 'sleep 60; echo A_DONE' B 'sleep 60; echo B_DONE' & sp=$!
sleep 2; kill -TERM "$sp"; wait "$sp"; rc=$?
sleep 1
if [[ $rc -ne 0 ]] && ! grep -q _DONE "$NCR_RUN_DIR"/logs/*.log; then pass c; else bad c "rc=$rc"; fi

# (d) usage error
bash "$SUP" A >/dev/null 2>&1; rc=$?
[[ $rc -eq 2 ]] && pass d || bad d "rc=$rc"

rm -rf "$NCR_RUN_DIR"
exit $fail
