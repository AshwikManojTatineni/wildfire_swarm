#!/bin/bash
# Setup job: CPU-only compute allocation (Torch: image pulls/builds on compute
# nodes, never login). Resources and account are passed by install.sh.
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --requeue
set -euo pipefail

cd "${SLURM_SUBMIT_DIR:?}"
source scripts/cluster/wf_env.sh
FORCE=0; ASSETS_ONLY=0
for a in "$@"; do
  case "$a" in --force) FORCE=1 ;; --assets-only) ASSETS_ONLY=1 ;; *) echo "unknown option $a" >&2; exit 2 ;; esac
done

mkdir -p "$WF_SIF_DIR" "$APPTAINER_CACHEDIR" "$APPTAINER_TMPDIR" "$WF_SRC_CACHE" "$WF_ASSETS"
LOG="$WF_SIF_DIR/install_${SLURM_JOB_ID}.log"
exec > >(tee -a "$LOG") 2>&1
trap 'rm -rf "$APPTAINER_TMPDIR"' EXIT

echo "== wildfire install job $SLURM_JOB_ID on $(hostname) at $(date -u +%FT%TZ)"
apptainer --version
echo "-- network check (needed for pulls/clones on compute nodes):"
curl -sS -o /dev/null -w "nvcr.io %{http_code}\n" https://nvcr.io/v2/ || true
curl -sS -o /dev/null -w "github %{http_code}\n" https://github.com || true

if [[ $ASSETS_ONLY == 0 ]]; then
BASE_REF="$(wf_cfg image.base)"
BASE_SIF="$WF_SIF_DIR/isaac-sim_5.1.0.sif"
PEG_COMMIT="$(wf_cfg pegasus.commit)"
PEG_TAG="$(wf_cfg pegasus.tag)"

# 1. Pull the NVIDIA 5.1.0 base image (anonymous first, NGC key only if denied).
if [[ ! -f "$BASE_SIF" || $FORCE == 1 ]]; then
  rm -f "$BASE_SIF"
  if ! apptainer pull "$BASE_SIF" "docker://$BASE_REF"; then
    if [[ -n "${NGC_API_KEY:-}" ]]; then
      echo "-- anonymous pull denied, retrying with NGC credentials"
      APPTAINER_DOCKER_USERNAME='$oauthtoken' APPTAINER_DOCKER_PASSWORD="$NGC_API_KEY" \
        apptainer pull "$BASE_SIF" "docker://$BASE_REF"
    else
      echo "ERROR: pull of $BASE_REF failed and NGC_API_KEY is empty in config/torch.env" >&2; exit 1
    fi
  fi
fi
# Registry digest of what was pulled (for the run manifest).
apptainer inspect --json "$BASE_SIF" > "$WF_SIF_DIR/isaac-sim_5.1.0.inspect.json" || true

# 2. Fakeroot probe: both project images need it (apt / pip in %post).
if ! apptainer build --fakeroot --help >/dev/null 2>&1 || \
   ! apptainer exec --fakeroot "$BASE_SIF" true 2>/dev/null; then
  echo "ERROR: apptainer --fakeroot is unavailable on $(hostname)." >&2
  echo "Ask hpc@nyu.edu about fakeroot; the fallback is a bind-mounted Pegasus checkout" >&2
  echo "plus a pip --target dependency directory." >&2
  exit 3
fi

# 3. Build isaac_pegasus.sif (immutable) from the definition file.
if [[ ! -f "$WF_ISAAC_SIF" || $FORCE == 1 ]]; then
  apptainer build --force --fakeroot \
    --build-arg "BASE_SIF=$BASE_SIF" \
    --build-arg "PEGASUS_COMMIT=$PEG_COMMIT" \
    --build-arg "PEGASUS_TAG=$PEG_TAG" \
    "$WF_ISAAC_SIF.tmp" containers/isaac_pegasus.def
  mv "$WF_ISAAC_SIF.tmp" "$WF_ISAAC_SIF"
fi

# 4. Build humble_ws.sif.
if [[ ! -f "$WF_HUMBLE_SIF" || $FORCE == 1 ]]; then
  apptainer build --force --fakeroot "$WF_HUMBLE_SIF.tmp" containers/humble_ws.def
  mv "$WF_HUMBLE_SIF.tmp" "$WF_HUMBLE_SIF"
fi

# Image checksums for the run manifests (only when images may have changed: ~40 GB to hash).
( cd "$WF_SIF_DIR" && sha256sum ./*.sif ) > "$WF_SIF_DIR/sif_sha256.txt"
apptainer exec "$WF_ISAAC_SIF" cat /opt/pegasus_commit /opt/isaac_pip_freeze.txt > "$WF_SIF_DIR/isaac_versions.txt"
apptainer exec "$WF_HUMBLE_SIF" cat /opt/versions.txt > "$WF_SIF_DIR/humble_versions.txt"
fi  # ASSETS_ONLY

# 5. Forest generator source at the pinned commit (its models are exported in step 6).
FOREST_DIR="$WF_SRC_CACHE/forest_generator"
FOREST_COMMIT="$(wf_cfg forest.generator_commit)"
if [[ ! -d "$FOREST_DIR/.git" ]]; then
  git clone "$(wf_cfg forest.repo)" "$FOREST_DIR"
fi
git -C "$FOREST_DIR" fetch -q origin || true
git -C "$FOREST_DIR" -c advice.detachedHead=false checkout -q "$FOREST_COMMIT"
test "$(git -C "$FOREST_DIR" rev-parse HEAD)" = "$FOREST_COMMIT"

# 6. Asset preparation (CPU): seeded forest export + Nova Carter mirror over HTTPS, inside
#    humble_ws.sif with usd-core. Runs from a snapshot of the committed source, like a gate.
mkdir -p "$WF_RUN_DIR"/{src,logs,tmp,home}
git -C "$WF_REPO" archive HEAD | tar -x -C "$WF_RUN_DIR/src"
WF_ASSETS_RW=1 bash scripts/cluster/ros_exec.sh 'python3 /workspace/src/scripts/cluster/prepare_assets.py'
cp "$WF_ASSETS/asset_manifest.json" "$WF_RUN_DIR/assets/asset_manifest.json"

# 7. Local checks on the compute node (nothing is pip-installed into $HOME).
bash scripts/cluster/ros_exec.sh 'cd /workspace/src && PXR_USDC_EMIT_DEPRECATION_WARNINGS=0 python3 -m pytest -q -p no:cacheprovider'   | tee "$WF_RUN_DIR/assets/pytest.txt"

# 8. Digests for the run manifests: image checksums + forest generator commit.
{ cat "$WF_SIF_DIR/sif_sha256.txt" 2>/dev/null || true; echo "forest_generator $FOREST_COMMIT"; } > "$WF_SIF_DIR/digests.txt"
cat "$WF_SIF_DIR/digests.txt"

OUT="$WF_REPO/results/install_${SLURM_JOB_ID}"
mkdir -p "$OUT"
cp "$WF_RUN_DIR/assets/summary.json" "$WF_RUN_DIR/assets/pytest.txt" "$WF_SIF_DIR/digests.txt" "$OUT/"
echo "== install OK $(date -u +%FT%TZ); summary in $OUT"
