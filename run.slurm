#!/bin/bash
# Runtime job for one gate (Go2 train.slurm pattern on Torch):
#   staged source snapshot -> manifest -> supervised gate -> per-job results.
# Account, GPU, CPU, memory and time come from run.sh.
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --requeue
set -euo pipefail

cd "${SLURM_SUBMIT_DIR:?}"
source scripts/cluster/wf_env.sh
GATE="$1"; shift
export WF_GATE="$GATE" WF_GATE_ARGS="$*"

# 1. Per-attempt run directory with an immutable snapshot of the committed source.
mkdir -p "$WF_RUN_DIR"/{src,logs,tmp,home,config_snapshot} "$APPTAINER_TMPDIR"
git -C "$WF_REPO" archive HEAD | tar -x -C "$WF_RUN_DIR/src"
git -C "$WF_REPO" diff HEAD > "$WF_RUN_DIR/uncommitted.diff" || true
cp -r "$WF_REPO/config/." "$WF_RUN_DIR/config_snapshot/"
rm -f "$WF_RUN_DIR/config_snapshot/torch.env"   # may hold an NGC key
echo "== gate $GATE  job $SLURM_JOB_ID  restart ${SLURM_RESTART_COUNT:-0}  node $(hostname)  run $WF_RUN_DIR"

# 2. Manifest: job, node, GPU/driver, SIF digests, git SHA, Pegasus commit, exact command.
python3 "$WF_RUN_DIR/src/scripts/cluster/manifest.py" --out "$WF_RUN_DIR/manifest.json" \
  --command "./run.sh $GATE $*" || echo "WARN: manifest incomplete"

# 3. GPU utilization / VRAM log every 5 s. Torch cancels low-utilization GPU jobs, and
#    peak VRAM is checked against the 48 GB L40S budget in config/runtime.yaml.
nvidia-smi --query-gpu=timestamp,utilization.gpu,memory.used,memory.total   --format=csv,noheader,nounits -l 5 > "$WF_RUN_DIR/gpu_usage.csv" 2>/dev/null &
GPU_MON=$!
trap 'kill $GPU_MON 2>/dev/null || true' EXIT

# 4. Run the gate under the supervisor (it propagates failures, stops children on scancel).
set +e
bash "$WF_RUN_DIR/src/scripts/gates/$GATE.sh" "$@" 2>&1 | tee "$WF_RUN_DIR/logs/gate_driver.log"
rc=${PIPESTATUS[0]}
set -e
kill "$GPU_MON" 2>/dev/null || true
python3 - "$WF_RUN_DIR/gpu_usage.csv" "$(wf_cfg gpu_budget.warn_fraction)" > "$WF_RUN_DIR/gpu_summary.json" <<'PY' || true
import json, sys
rows = [l.split(",") for l in open(sys.argv[1]) if l.count(",") == 3]
util = [float(r[1]) for r in rows]; used = [float(r[2]) for r in rows]; total = float(rows[0][3]) if rows else 0
peak = max(used, default=0.0)
print(json.dumps({"samples": len(rows), "util_mean_pct": round(sum(util) / len(util), 1) if util else None,
                  "util_max_pct": max(util, default=None), "vram_peak_mib": peak, "vram_total_mib": total,
                  "vram_peak_fraction": round(peak / total, 3) if total else None,
                  "vram_over_budget": bool(total and peak / total > float(sys.argv[2]))}, indent=2))
PY
cat "$WF_RUN_DIR/gpu_summary.json" 2>/dev/null || true

# 5. Resource usage + results to the repo (Go2 copied logs/videos back; here the repo is
#    on the same filesystem, so a plain copy replaces the old ssh/rsync to greene-dtn).
sstat -j "${SLURM_JOB_ID}.batch" --format=MaxRSS,AveCPU -n > "$WF_RUN_DIR/sstat.txt" 2>/dev/null || true
OUT="$WF_REPO/results/${SLURM_JOB_ID}_r${SLURM_RESTART_COUNT:-0}"
mkdir -p "$OUT"
cp "$WF_RUN_DIR"/manifest.json "$OUT/" 2>/dev/null || true
(cd "$WF_RUN_DIR" && find . -maxdepth 2 \
   \( -name '*.json' -o -name '*.mp4' -o -name '*.png' -o -name '*.txt' -o -name '*.csv' \) \
   -not -path './src/*' -not -path './config_snapshot/*' -not -path './tmp/*' \
   -exec cp --parents {} "$OUT" \;)
for f in "$WF_RUN_DIR"/logs/*.log; do tail -n 200 "$f" > "$OUT/$(basename "$f").tail"; done
echo "{\"gate\": \"$GATE\", \"job_id\": \"$SLURM_JOB_ID\", \"exit_code\": $rc, \"run_dir\": \"$WF_RUN_DIR\"}" > "$OUT/job_status.json"
echo "== gate $GATE finished rc=$rc; results in $OUT"
for v in "$OUT"/*/*.mp4; do if [[ -f "$v" ]]; then echo "== video: $v ($(du -h "$v" | cut -f1))"; fi; done
ln -sfn "$OUT" "$WF_REPO/results/latest"
exit "$rc"
