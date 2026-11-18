#!/usr/bin/env bash
# Supervise named child commands inside one Slurm allocation: propagate failures and
# shut down the remaining children on failure or termination.
#
#   supervise.sh NAME1 'cmd1' [NAME2 'cmd2' ...]
#
# Each child's stdout/stderr -> $WF_RUN_DIR/logs/NAME.log.
# Exit code: the first non-zero child code; 0 once every child exits 0;
# 143 when the supervisor itself receives TERM/INT (e.g. scancel, time limit).
# On a failure or signal the remaining children get TERM, then KILL after
# WF_GRACE_S seconds (default 15).
set -uo pipefail

if (( $# < 2 || $# % 2 != 0 )); then
  echo "usage: supervise.sh NAME 'command' [NAME 'command' ...]" >&2
  exit 2
fi
: "${WF_RUN_DIR:?WF_RUN_DIR must be set}"
GRACE="${WF_GRACE_S:-15}"
mkdir -p "$WF_RUN_DIR/logs"

declare -a NAMES=() PIDS=()
USE_SETSID=0; command -v setsid >/dev/null 2>&1 && USE_SETSID=1

log() { echo "[supervise $(date -u +%H:%M:%S)] $*" >&2; }

signal_child() {  # $1=signal $2=pid
  if (( USE_SETSID )); then kill "-$1" -- "-$2" 2>/dev/null; fi
  pkill "-$1" -P "$2" 2>/dev/null
  kill "-$1" "$2" 2>/dev/null
}

stop_all() {
  local pid alive
  for pid in "${PIDS[@]}"; do signal_child TERM "$pid"; done
  for ((t = 0; t < GRACE; t++)); do
    alive=0
    for pid in "${PIDS[@]}"; do kill -0 "$pid" 2>/dev/null && alive=1; done
    (( alive )) || return 0
    sleep 1
  done
  for pid in "${PIDS[@]}"; do signal_child KILL "$pid"; done
}

on_signal() {
  log "received termination signal; stopping children"
  stop_all
  exit 143
}
trap on_signal TERM INT

while (( $# )); do
  name="$1" cmd="$2"; shift 2
  if (( USE_SETSID )); then
    setsid -w bash -c "$cmd" >"$WF_RUN_DIR/logs/$name.log" 2>&1 &
  else
    bash -c "$cmd" >"$WF_RUN_DIR/logs/$name.log" 2>&1 &
  fi
  NAMES+=("$name"); PIDS+=("$!")
  log "started $name (pid $!)"
done

declare -A FINISHED=()
remaining=${#PIDS[@]}
while (( remaining > 0 )); do
  for i in "${!PIDS[@]}"; do
    [[ -n "${FINISHED[$i]:-}" ]] && continue
    if ! kill -0 "${PIDS[$i]}" 2>/dev/null; then
      wait "${PIDS[$i]}"; rc=$?
      FINISHED[$i]=1; remaining=$((remaining - 1))
      log "${NAMES[$i]} exited with $rc"
      if (( rc != 0 )); then
        stop_all
        exit "$rc"
      fi
    fi
  done
  sleep 1 & wait $!
done
log "all children exited 0"
exit 0
