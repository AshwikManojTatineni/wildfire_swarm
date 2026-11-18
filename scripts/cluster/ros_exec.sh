#!/usr/bin/env bash
# Run one command inside humble_ws.sif (native Ubuntu 22.04 / Humble, Python 3.10)
# with the same DDS settings as the simulator: Fast DDS, UDPv4-only profile,
# per-job ROS_DOMAIN_ID, localhost only. Never shares Python with Isaac Sim.
# The image also carries usd-core, so the CPU-only asset preparation in install.slurm runs here.
#
#   scripts/cluster/ros_exec.sh 'ros2 topic list'
set -euo pipefail
: "${WF_RUN_DIR:?}" "${WF_HUMBLE_SIF:?}" "${WF_ASSETS:?}" "${WF_SRC_CACHE:?}"
mkdir -p "$WF_RUN_DIR"/{home,tmp,src} "$WF_ASSETS" "$WF_SRC_CACHE"
assets_mode=ro; [[ "${WF_ASSETS_RW:-0}" == 1 ]] && assets_mode=rw

overlay=""
extra=()
if [[ -n "${WF_ROS_WS:-}" && -f "$WF_ROS_WS/setup.bash" ]]; then
  overlay="source /workspace/ros_ws/setup.bash;"
  extra+=(-B "$WF_ROS_WS:/workspace/ros_ws:ro")
fi

exec apptainer exec --containall --cleanenv --writable-tmpfs \
  --env "HOME=/workspace/run/home" \
  --env "PYTHONNOUSERSITE=1" \
  --env "PYTHONPATH=/workspace/src/source/wildfire_swarm" \
  --env "RMW_IMPLEMENTATION=$RMW_IMPLEMENTATION" \
  --env "ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-0}" \
  --env "ROS_LOCALHOST_ONLY=$ROS_LOCALHOST_ONLY" \
  --env "FASTRTPS_DEFAULT_PROFILES_FILE=/workspace/src/containers/fastdds_udp.xml" \
  --env "SLURM_JOB_ID=${SLURM_JOB_ID:-local}" \
  -B "$WF_RUN_DIR/src:/workspace/src:ro" \
  -B "$WF_RUN_DIR:/workspace/run:rw" \
  -B "$WF_RUN_DIR/tmp:/tmp:rw" \
  -B "$WF_ASSETS:/workspace/assets:$assets_mode" \
  -B "$WF_SRC_CACHE:/workspace/srccache:ro" \
  "${extra[@]}" \
  "$WF_HUMBLE_SIF" bash -c "source /opt/ros/humble/setup.bash; $overlay $*"
