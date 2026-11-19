#!/usr/bin/env bash
# Run one command inside humble_ws.sif (native Ubuntu 22.04 / Humble, Python 3.10)
# with the same DDS settings as the simulator: Fast DDS, UDPv4-only profile,
# per-job ROS_DOMAIN_ID, localhost only. Never shares Python with Isaac Sim.
# The image also carries usd-core, so the CPU-only asset preparation in install.slurm runs here.
#
#   scripts/cluster/ros_exec.sh 'ros2 topic list'
set -euo pipefail
: "${NCR_RUN_DIR:?}" "${NCR_HUMBLE_SIF:?}" "${NCR_ASSETS:?}" "${NCR_SRC_CACHE:?}"
mkdir -p "$NCR_RUN_DIR"/{home,tmp,src} "$NCR_ASSETS" "$NCR_SRC_CACHE"
assets_mode=ro; [[ "${NCR_ASSETS_RW:-0}" == 1 ]] && assets_mode=rw

overlay=""
extra=()
if [[ -n "${NCR_ROS_WS:-}" && -f "$NCR_ROS_WS/setup.bash" ]]; then
  overlay="source /workspace/ros_ws/setup.bash;"
  extra+=(-B "$NCR_ROS_WS:/workspace/ros_ws:ro")
fi

exec apptainer exec --containall --cleanenv --writable-tmpfs \
  --env "HOME=/workspace/run/home" \
  --env "PYTHONNOUSERSITE=1" \
  --env "PYTHONPATH=/workspace/src/source/narrow_corridor_robot" \
  --env "RMW_IMPLEMENTATION=$RMW_IMPLEMENTATION" \
  --env "ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-0}" \
  --env "ROS_LOCALHOST_ONLY=$ROS_LOCALHOST_ONLY" \
  --env "FASTRTPS_DEFAULT_PROFILES_FILE=/workspace/src/containers/fastdds_udp.xml" \
  --env "SLURM_JOB_ID=${SLURM_JOB_ID:-local}" \
  -B "$NCR_RUN_DIR/src:/workspace/src:ro" \
  -B "$NCR_RUN_DIR:/workspace/run:rw" \
  -B "$NCR_RUN_DIR/tmp:/tmp:rw" \
  -B "$NCR_ASSETS:/workspace/assets:$assets_mode" \
  -B "$NCR_SRC_CACHE:/workspace/srccache:ro" \
  "${extra[@]}" \
  "$NCR_HUMBLE_SIF" bash -c "source /opt/ros/humble/setup.bash; $overlay $*"
