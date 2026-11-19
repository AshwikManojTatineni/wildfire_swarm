#!/bin/bash
# Runtime job (Go2 train.slurm pattern on Torch): ONE allocation, ONE L40S.
#   staged source snapshot -> manifest -> gates run one after another -> per-job results.
# Stops at the first failing gate so the GPU is released as early as possible.
# Account, GPU, CPU, memory and time come from run.sh.
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --requeue
#SBATCH --account=torch_pr_742
#SBATCH --mail-type=END,FAIL
set -euo pipefail

cd "${SLURM_SUBMIT_DIR:?}"
source scripts/cluster/ncr_env.sh
GATES=("$@")
export NCR_GATE="${GATES[*]}"

# 1. Per-attempt run directory with an immutable snapshot of the committed source.
mkdir -p "$NCR_RUN_DIR"/{src,logs,tmp,home} "$APPTAINER_TMPDIR"
git -C "$NCR_REPO" archive HEAD | tar -x -C "$NCR_RUN_DIR/src"     # includes config/ as committed
git -C "$NCR_REPO" diff HEAD > "$NCR_RUN_DIR/uncommitted.diff" || true
echo "== gates ${GATES[*]}  job $SLURM_JOB_ID  restart ${SLURM_RESTART_COUNT:-0}  node $(hostname)  run $NCR_RUN_DIR"

# 2. Manifest: job, node, GPU/driver, SIF digests, git SHA, Pegasus commit, exact command.
python3 "$NCR_RUN_DIR/src/scripts/cluster/manifest.py" --out "$NCR_RUN_DIR/manifest.json" \
  --command "./run.sh ${GATES[*]}" || echo "WARN: manifest incomplete"

# 3. GPU utilization / VRAM log every 5 s. Torch cancels low-utilization GPU jobs, and
#    peak VRAM is checked against the 48 GB L40S budget in config/runtime.yaml.
#    Only the allocated GPU is logged: if the node does not hide the other three, an unfiltered
#    query would average in other users' GPUs.
gpu_sel=(); [[ -n "${CUDA_VISIBLE_DEVICES:-}" ]] && gpu_sel=(-i "${CUDA_VISIBLE_DEVICES%%,*}")
nvidia-smi "${gpu_sel[@]}" --query-gpu=timestamp,utilization.gpu,memory.used,memory.total \
  --format=csv,noheader,nounits -l 5 > "$NCR_RUN_DIR/gpu_usage.csv" 2>/dev/null &
GPU_MON=$!
trap 'kill $GPU_MON 2>/dev/null || true; rm -rf "$APPTAINER_TMPDIR"' EXIT

# 4. Run the gates in order on the same GPU (each uses the supervisor, which propagates
#    failures and stops children on scancel). Stop at the first failure.
rc=0; declare -A GATE_RC=()
set +e
for g in "${GATES[@]}"; do
  echo "== [$(date -u +%H:%M:%S)] gate $g start"
  bash "$NCR_RUN_DIR/src/scripts/gates/$g.sh" 2>&1 | tee "$NCR_RUN_DIR/logs/gate_$g.log"
  GATE_RC[$g]=${PIPESTATUS[0]}
  echo "== [$(date -u +%H:%M:%S)] gate $g exit ${GATE_RC[$g]}"
  if (( GATE_RC[$g] != 0 )); then rc=${GATE_RC[$g]}; break; fi
done
set -e
kill "$GPU_MON" 2>/dev/null || true
python3 - "$NCR_RUN_DIR/gpu_usage.csv" "$(ncr_cfg gpu_budget.warn_fraction)" > "$NCR_RUN_DIR/gpu_summary.json" <<'PY' || true
import json, sys
rows = [l.split(",") for l in open(sys.argv[1]) if l.count(",") == 3]
util = [float(r[1]) for r in rows]; used = [float(r[2]) for r in rows]; total = float(rows[0][3]) if rows else 0
peak = max(used, default=0.0)
print(json.dumps({"samples": len(rows), "util_mean_pct": round(sum(util) / len(util), 1) if util else None,
                  "util_max_pct": max(util, default=None), "vram_peak_mib": peak, "vram_total_mib": total,
                  "vram_peak_fraction": round(peak / total, 3) if total else None,
                  "vram_over_budget": bool(total and peak / total > float(sys.argv[2]))}, indent=2))
PY
cat "$NCR_RUN_DIR/gpu_summary.json" 2>/dev/null || true

# 5. Resource usage + results to the repo (Go2 copied logs/videos back; here the repo is
#    on the same filesystem, so a plain copy replaces the old ssh/rsync to greene-dtn).
sstat -j "${SLURM_JOB_ID}.batch" --format=MaxRSS,AveCPU -n > "$NCR_RUN_DIR/sstat.txt" 2>/dev/null || true
OUT="$NCR_REPO/results/${SLURM_JOB_ID}_r${SLURM_RESTART_COUNT:-0}"
mkdir -p "$OUT"
cp "$NCR_RUN_DIR"/manifest.json "$OUT/" 2>/dev/null || true
(cd "$NCR_RUN_DIR" && find . -maxdepth 2 \
   \( -name '*.json' -o -name '*.mp4' -o -name '*.png' -o -name '*.txt' -o -name '*.csv' \) \
   -not -path './src/*' -not -path './tmp/*' \
   -exec cp --parents {} "$OUT" \;)
for f in "$NCR_RUN_DIR"/logs/*.log; do tail -n 200 "$f" > "$OUT/$(basename "$f").tail"; done
{
  printf '{"job_id": "%s", "exit_code": %s, "run_dir": "%s", "gates": {' "$SLURM_JOB_ID" "$rc" "$NCR_RUN_DIR"
  sep=""; for g in "${GATES[@]}"; do printf '%s"%s": %s' "$sep" "$g" "${GATE_RC[$g]:-null}"; sep=", "; done
  printf '}}
'
} > "$OUT/job_status.json"
cat "$OUT/job_status.json"
echo "== job finished rc=$rc; results in $OUT"
for v in "$OUT"/*/*.mp4; do if [[ -f "$v" ]]; then echo "== video: $v ($(du -h "$v" | cut -f1))"; fi; done
ln -sfn "$OUT" "$NCR_REPO/results/latest"
exit "$rc"
