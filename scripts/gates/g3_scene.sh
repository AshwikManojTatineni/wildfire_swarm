#!/usr/bin/env bash
# G3 scene (offline): forest + Iris + Nova Carter load from localized read-only assets,
# colliders and 240/60 Hz rates are checked, the Carter drives, and the run is recorded.
# Evidence: g3/overview.mp4, g3/chase.mp4, g3/still_*.png, g3/stage_report.json, g3/verdict.json
set -euo pipefail
S="$WF_RUN_DIR/src/scripts/cluster"
[[ -f "$WF_ASSETS/asset_manifest.json" ]] || { echo "G3 FAIL: run ./install.sh first (it prepares the assets)"; exit 1; }
mkdir -p "$WF_RUN_DIR/g3"
set +e
WF_OFFLINE=1 bash "$S/supervise.sh" \
  scene "WF_OFFLINE=1 bash $S/isaac_exec.sh /isaac-sim/python.sh /workspace/src/scripts/gates/g3_scene.py"
rc=$?
set -e
if [[ ! -f "$WF_RUN_DIR/g3/verdict.json" ]]; then
  echo "G3 FAIL: no verdict (scene script exited $rc); see logs/scene.log"; exit 1
fi
python3 - "$WF_RUN_DIR/g3/verdict.json" <<'EOF'
import json, sys
v = json.load(open(sys.argv[1]))
print("G3", "PASS" if v["pass"] else "FAIL", json.dumps(v["measured"], indent=1))
sys.exit(0 if v["pass"] else 1)
EOF
