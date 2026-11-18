#!/usr/bin/env bash
# Login-node submitter (Go2 train.sh pattern, adapted to Torch: direct sbatch, --account
# from config, no partition). ONE job, ONE L40S: the requested gates run one after another
# inside that allocation and stop at the first failure (like Go2's train-then-play job).
#   ./run.sh                          # g1_startup -> g3_scene
#   ./run.sh g3_scene                 # a single gate
#   ./run.sh g1_startup                # any ordered subset
# Refused while one of your wildfire jobs (setup or run) is still queued or running.
set -euo pipefail
cd "$(dirname "$0")"
GATES=("$@"); (( ${#GATES[@]} )) || GATES=(g1_startup g3_scene)
for g in "${GATES[@]}"; do
  [[ -f "scripts/gates/$g.sh" ]] || { echo "unknown gate: $g (gates: g1_startup g3_scene)" >&2; exit 2; }
done
source scripts/cluster/wf_env.sh
if [[ -n "$(git status --porcelain --untracked-files=no)" && "${WF_ALLOW_DIRTY:-0}" != 1 ]]; then
  echo "Working tree has uncommitted changes; the job snapshots HEAD. Commit, or set WF_ALLOW_DIRTY=1." >&2
  exit 2
fi
active="$(wf_active_jobs)"
if [[ -n "$active" ]]; then
  echo "A wildfire job is already queued/running (one at a time):" >&2
  echo "$active" >&2
  echo "Wait for it, or cancel it with: scancel <jobid>" >&2
  exit 3
fi

# One allocation sized for the largest gate; wall time is the sum of the gates' limits.
cpus=0; mem=0; minutes=0
for g in "${GATES[@]}"; do
  case "$g" in g1_*) p=gpu_short ;; g[6-9]_*) p=gpu_large ;; *) p=gpu ;; esac
  c="$(wf_cfg "slurm.$p.cpus")"; m="$(wf_cfg "slurm.$p.mem")"; t="$(wf_cfg "slurm.$p.time")"
  m="${m%G}"; IFS=: read -r hh mm _ <<< "$t"
  (( c > cpus )) && cpus=$c
  (( m > mem )) && mem=$m
  minutes=$(( minutes + 10#$hh * 60 + 10#$mm ))
done
time_limit="$(printf '%02d:%02d:00' $((minutes / 60)) $((minutes % 60)))"

mail=(); [[ -n "${MAIL_USER:-}" ]] && mail=(--mail-type=END,FAIL --mail-user="$MAIL_USER")
mkdir -p "$WF_SCRATCH/slurm_logs"
echo "Submitting ONE job on ONE $(wf_cfg slurm.gpu_constraint): ${GATES[*]}  (${cpus} CPUs, ${mem}G RAM, ${time_limit})"
jobid=$(sbatch --parsable --account="$SLURM_ACCOUNT" \
  --job-name="wf_run" \
  --gres="$(wf_cfg slurm.gpu_gres)" --constraint="$(wf_cfg slurm.gpu_constraint)" \
  --cpus-per-task="$cpus" --mem="${mem}G" --time="$time_limit" \
  --output="$WF_SCRATCH/slurm_logs/run_%j.out" \
  "${mail[@]}" \
  --export=ALL,WF_ALLOW_DIRTY="${WF_ALLOW_DIRTY:-0}" \
  run.slurm "${GATES[@]}")
jobid="${jobid%%;*}"
echo "Submitted run job $jobid. Follow it (Ctrl+C stops watching, not the job):"
echo "  tail -F $WF_SCRATCH/slurm_logs/run_${jobid}.out"
