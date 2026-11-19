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
#   $NCR_CACHE/{main,computecache,logs,config,data,pkg} -> /isaac-sim/{.cache,.nv/ComputeCache,
#        .nvidia-omniverse/logs,.nvidia-omniverse/config,.local/share/ov/data,.local/share/ov/pkg}
#   $NCR_CACHE/kit/{cache,data}                -> /isaac-sim/kit/{cache,data}   (Go2 pattern)
#   $NCR_RUN_DIR/src  (snapshot, ro)           -> /workspace/src
#   $NCR_ASSETS       (ro unless NCR_ASSETS_RW) -> /workspace/assets
#   $NCR_RUN_DIR      (rw)                     -> /workspace/run
#   $NCR_RUN_DIR/tmp  (rw)                     -> /tmp
set -euo pipefail
: "${NCR_RUN_DIR:?}" "${NCR_CACHE:?}" "${NCR_ASSETS:?}" "${NCR_ISAAC_SIF:?}"

for d in main computecache logs config data pkg kit/cache kit/data; do mkdir -p "$NCR_CACHE/$d"; done
mkdir -p "$NCR_RUN_DIR"/{tmp,src} "$NCR_ASSETS" "$NCR_SRC_CACHE"

assets_mode=ro; [[ "${NCR_ASSETS_RW:-0}" == 1 ]] && assets_mode=rw

env_args=(
  --env "ACCEPT_EULA=$(ncr_cfg nvidia_env.ACCEPT_EULA)"
  --env "PRIVACY_CONSENT=$(ncr_cfg nvidia_env.PRIVACY_CONSENT)"
  --env "HOME=/isaac-sim"
  --env "ROS_DISTRO=humble"
  --env "RMW_IMPLEMENTATION=$RMW_IMPLEMENTATION"
  --env "ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-0}"
  --env "ROS_LOCALHOST_ONLY=$ROS_LOCALHOST_ONLY"
  --env "FASTRTPS_DEFAULT_PROFILES_FILE=/workspace/src/containers/fastdds_udp.xml"
  --env "LD_LIBRARY_PATH=/isaac-sim/exts/isaacsim.ros2.bridge/humble/lib"
  --env "PYTHONPATH=/workspace/src/source/narrow_corridor_robot"
  --env "PYTHONNOUSERSITE=1"
  --env "SLURM_JOB_ID=${SLURM_JOB_ID:-local}"
)
# Optional offline enforcement: a black-hole proxy makes accidental http(s) fetches fail fast.
if [[ "${NCR_OFFLINE:-0}" == 1 ]]; then
  env_args+=(--env "HTTP_PROXY=http://127.0.0.1:9" --env "HTTPS_PROXY=http://127.0.0.1:9"
             --env "http_proxy=http://127.0.0.1:9" --env "https_proxy=http://127.0.0.1:9"
             --env "NCR_OFFLINE=1")
fi

exec apptainer exec --nv --containall --cleanenv --no-home --writable-tmpfs \
  "${env_args[@]}" \
  -B "$NCR_CACHE/main:/isaac-sim/.cache:rw" \
  -B "$NCR_CACHE/computecache:/isaac-sim/.nv/ComputeCache:rw" \
  -B "$NCR_CACHE/logs:/isaac-sim/.nvidia-omniverse/logs:rw" \
  -B "$NCR_CACHE/config:/isaac-sim/.nvidia-omniverse/config:rw" \
  -B "$NCR_CACHE/data:/isaac-sim/.local/share/ov/data:rw" \
  -B "$NCR_CACHE/pkg:/isaac-sim/.local/share/ov/pkg:rw" \
  -B "$NCR_CACHE/kit/cache:/isaac-sim/kit/cache:rw" \
  -B "$NCR_CACHE/kit/data:/isaac-sim/kit/data:rw" \
  -B "$NCR_RUN_DIR/src:/workspace/src:ro" \
  -B "$NCR_ASSETS:/workspace/assets:$assets_mode" \
  -B "$NCR_SRC_CACHE:/workspace/srccache:ro" \
  -B "$NCR_RUN_DIR:/workspace/run:rw" \
  -B "$NCR_RUN_DIR/tmp:/tmp:rw" \
  "$NCR_ISAAC_SIF" "$@"
