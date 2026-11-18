#!/usr/bin/env bash
# Run one command inside isaac_pegasus.sif inside a Slurm job.
# This is the batch replacement for Pegasus' workstation `isaac_run` bashrc
# function: ROS variables are dropped (--cleanenv), the internal
# Humble bridge libraries are put on LD_LIBRARY_PATH exactly once, and
# ROS_DISTRO/RMW are set before Kit starts.
#
#   scripts/cluster/isaac_exec.sh /isaac-sim/python.sh /workspace/src/scripts/gates/g1_startup.py
#
# Mounts (NVIDIA 5.1 container page, translated for Apptainer, where the
# process runs as the Torch user instead of uid 1234 and the SIF is read-only):
#   $WF_CACHE/{main,computecache,logs,config,data,pkg} -> /isaac-sim/{.cache,.nv/ComputeCache,
#        .nvidia-omniverse/logs,.nvidia-omniverse/config,.local/share/ov/data,.local/share/ov/pkg}
#   $WF_CACHE/kit/{cache,data}                -> /isaac-sim/kit/{cache,data}   (Go2 pattern)
#   $WF_RUN_DIR/src  (snapshot, ro)           -> /workspace/src
#   $WF_ASSETS       (ro unless WF_ASSETS_RW) -> /workspace/assets
#   $WF_RUN_DIR      (rw)                     -> /workspace/run
#   $WF_RUN_DIR/tmp  (rw)                     -> /tmp
set -euo pipefail
: "${WF_RUN_DIR:?}" "${WF_CACHE:?}" "${WF_ASSETS:?}" "${WF_ISAAC_SIF:?}"

for d in main computecache logs config data pkg kit/cache kit/data; do mkdir -p "$WF_CACHE/$d"; done
mkdir -p "$WF_RUN_DIR"/{tmp,src} "$WF_ASSETS" "$WF_SRC_CACHE"

assets_mode=ro; [[ "${WF_ASSETS_RW:-0}" == 1 ]] && assets_mode=rw

env_args=(
  --env "ACCEPT_EULA=$(wf_cfg nvidia_env.ACCEPT_EULA)"
  --env "PRIVACY_CONSENT=$(wf_cfg nvidia_env.PRIVACY_CONSENT)"
  --env "HOME=/isaac-sim"
  --env "ROS_DISTRO=humble"
  --env "RMW_IMPLEMENTATION=$RMW_IMPLEMENTATION"
  --env "ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-0}"
  --env "ROS_LOCALHOST_ONLY=$ROS_LOCALHOST_ONLY"
  --env "FASTRTPS_DEFAULT_PROFILES_FILE=/workspace/src/containers/fastdds_udp.xml"
  --env "LD_LIBRARY_PATH=/isaac-sim/exts/isaacsim.ros2.bridge/humble/lib"
  --env "PYTHONPATH=/workspace/src/source/wildfire_swarm"
  --env "PYTHONNOUSERSITE=1"
  --env "SLURM_JOB_ID=${SLURM_JOB_ID:-local}"
)
# Optional offline enforcement: a black-hole proxy makes accidental http(s) fetches fail fast.
if [[ "${WF_OFFLINE:-0}" == 1 ]]; then
  env_args+=(--env "HTTP_PROXY=http://127.0.0.1:9" --env "HTTPS_PROXY=http://127.0.0.1:9"
             --env "http_proxy=http://127.0.0.1:9" --env "https_proxy=http://127.0.0.1:9"
             --env "WF_OFFLINE=1")
fi

exec apptainer exec --nv --containall --cleanenv --no-home --writable-tmpfs \
  "${env_args[@]}" \
  -B "$WF_CACHE/main:/isaac-sim/.cache:rw" \
  -B "$WF_CACHE/computecache:/isaac-sim/.nv/ComputeCache:rw" \
  -B "$WF_CACHE/logs:/isaac-sim/.nvidia-omniverse/logs:rw" \
  -B "$WF_CACHE/config:/isaac-sim/.nvidia-omniverse/config:rw" \
  -B "$WF_CACHE/data:/isaac-sim/.local/share/ov/data:rw" \
  -B "$WF_CACHE/pkg:/isaac-sim/.local/share/ov/pkg:rw" \
  -B "$WF_CACHE/kit/cache:/isaac-sim/kit/cache:rw" \
  -B "$WF_CACHE/kit/data:/isaac-sim/kit/data:rw" \
  -B "$WF_RUN_DIR/src:/workspace/src:ro" \
  -B "$WF_ASSETS:/workspace/assets:$assets_mode" \
  -B "$WF_SRC_CACHE:/workspace/srccache:ro" \
  -B "$WF_RUN_DIR:/workspace/run:rw" \
  -B "$WF_RUN_DIR/tmp:/tmp:rw" \
  "$WF_ISAAC_SIF" "$@"
