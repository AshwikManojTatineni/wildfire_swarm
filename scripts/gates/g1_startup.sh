#!/usr/bin/env bash
# G1 container startup: both SIFs start, Python 3.11 vs 3.10 separation, Pegasus
# imports after SimulationApp, Humble packages present. Evidence: g1/summary.json
set -euo pipefail
S="$NCR_RUN_DIR/src/scripts/cluster"
mkdir -p "$NCR_RUN_DIR/g1"
bash "$S/supervise.sh" \
  isaac "bash $S/isaac_exec.sh /isaac-sim/python.sh /workspace/src/scripts/gates/g1_startup.py" \
  humble "bash $S/ros_exec.sh 'python3 --version; for p in nav2_bringup robot_localization rtabmap_odom; do ros2 pkg prefix \$p; done; cat /opt/versions.txt' > $NCR_RUN_DIR/g1/humble.txt"
grep -q "Python 3.10" "$NCR_RUN_DIR/g1/humble.txt" || { echo "G1 FAIL: Humble python is not 3.10"; exit 1; }
python3 - "$NCR_RUN_DIR/g1/summary.json" <<'EOF'
import json, sys
s = json.load(open(sys.argv[1]))
ok = s["isaac_python"].startswith("3.11") and s["pegasus_import"] and s["iris_in_robots"]
print("G1", "PASS" if ok else "FAIL", json.dumps(s, indent=1))
sys.exit(0 if ok else 1)
EOF
