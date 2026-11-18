#!/usr/bin/env bash
# Login-node submitter for one verification gate (Go2 train.sh pattern, adapted to
# Torch: direct sbatch, --gres=gpu:1 --constraint=l40s, no partition).
#   ./run.sh g1_startup | g2_gpu | g3_prep | g3_scene   [extra args passed to the gate]
set -euo pipefail
cd "$(dirname "$0")"
GATE="${1:?usage: ./run.sh <gate> [args]   (gates: g1_startup g2_gpu g3_prep g3_scene)}"
[[ -f "scripts/gates/$GATE.sh" ]] || { echo "unknown gate: $GATE" >&2; exit 2; }
source scripts/cluster/wf_env.sh
if [[ -n "$(git status --porcelain --untracked-files=no)" && "${WF_ALLOW_DIRTY:-0}" != 1 ]]; then
  echo "Working tree has uncommitted changes; the job snapshots HEAD. Commit, or set WF_ALLOW_DIRTY=1." >&2
  exit 2
fi
size=small; case "$GATE" in g[6-9]*) size=large ;; esac
mkdir -p "$WF_SCRATCH/slurm_logs"
sbatch --account="$SLURM_ACCOUNT" \
  --job-name="wf_${GATE}" \
  --gres="$(wf_cfg slurm.gpu_gres)" --constraint="$(wf_cfg slurm.gpu_constraint)" \
  --cpus-per-task="$(wf_cfg "slurm.$size.cpus")" \
  --mem="$(wf_cfg "slurm.$size.mem")" \
  --time="$(wf_cfg "slurm.$size.time")" \
  --output="$WF_SCRATCH/slurm_logs/${GATE}_%j.out" \
  --export=ALL,WF_ALLOW_DIRTY="${WF_ALLOW_DIRTY:-0}" \
  run.slurm "$@"
