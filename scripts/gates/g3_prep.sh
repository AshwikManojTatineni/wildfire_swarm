#!/usr/bin/env bash
# G3 prep (network allowed, assets mounted read-write): export the seeded forest and
# localize the Nova Carter closure into $WF_ASSETS. Run once (and after a scratch purge).
# Evidence: g3_prep/summary.json and $WF_ASSETS/asset_manifest.json
set -euo pipefail
S="$WF_RUN_DIR/src/scripts/cluster"
mkdir -p "$WF_RUN_DIR/g3_prep"
WF_ASSETS_RW=1 bash "$S/supervise.sh" \
  prep "WF_ASSETS_RW=1 bash $S/isaac_exec.sh /isaac-sim/python.sh /workspace/src/scripts/gates/g3_prep.py"
cp "$WF_ASSETS/asset_manifest.json" "$WF_RUN_DIR/g3_prep/asset_manifest.json"
python3 - "$WF_RUN_DIR/g3_prep/summary.json" <<'EOF'
import json, sys
s = json.load(open(sys.argv[1]))
ok = not s["errors"] and s.get("nova_carter_rel") and s.get("forest", {}).get("remote_refs") == []
print("G3_PREP", "PASS" if ok else "FAIL", json.dumps(s, indent=1))
sys.exit(0 if ok else 1)
EOF
