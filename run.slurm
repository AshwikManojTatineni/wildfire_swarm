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

# 3. Run the gate under the supervisor (it propagates failures, stops children on scancel).
set +e
bash "$WF_RUN_DIR/src/scripts/gates/$GATE.sh" "$@" 2>&1 | tee "$WF_RUN_DIR/logs/gate_driver.log"
rc=${PIPESTATUS[0]}
set -e

# 4. Resource usage + results to the repo (Go2 copied logs/videos back; here the repo is
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
exit "$rc"
