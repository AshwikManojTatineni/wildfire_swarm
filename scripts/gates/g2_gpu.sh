#!/usr/bin/env bash
# G2 GPU visibility: the allocated L40S and driver are visible on the host and inside
# the SIF (--nv), and NVIDIA's 5.1 compatibility check passes headless.
# Evidence: g2/nvidia-smi_{host,container}.txt, g2/compat.log, g2/summary.json
set -euo pipefail
S="$WF_RUN_DIR/src/scripts/cluster"
D="$WF_RUN_DIR/g2"; mkdir -p "$D"
Q="--query-gpu=name,uuid,driver_version,memory.total --format=csv"
nvidia-smi $Q | tee "$D/nvidia-smi_host.txt"
bash "$S/isaac_exec.sh" nvidia-smi $Q | tee "$D/nvidia-smi_container.txt"
bash "$S/isaac_exec.sh" bash -c 'ls /usr/share/vulkan/icd.d /etc/vulkan/icd.d 2>&1' > "$D/vulkan_icd.txt" || true
set +e
timeout 1200 bash "$S/isaac_exec.sh" /isaac-sim/isaac-sim.compatibility_check.sh --/app/quitAfter=10 --no-window \
  > "$D/compat.log" 2>&1
crc=$?
set -e
python3 - "$D" "$crc" <<'EOF'
import json, sys
d, crc = sys.argv[1], int(sys.argv[2])
host = open(f"{d}/nvidia-smi_host.txt").read().splitlines()[1:]
cont = open(f"{d}/nvidia-smi_container.txt").read().splitlines()[1:]
compat = open(f"{d}/compat.log", errors="replace").read()
s = {
  "host_gpus": host, "container_gpus": cont,
  "l40s": any("L40S" in l for l in cont),
  "same_gpu_in_container": sorted(host) == sorted(cont),
  "driver": cont[0].split(",")[2].strip() if cont else None,
  "pegasus_tested_driver": "550.163.01",
  "isaac_sim_5_1_tested_driver": "580.65.06",
  "compat_passed": "System checking result: PASSED" in compat,
  "compat_exit": crc,
}
json.dump(s, open(f"{d}/summary.json", "w"), indent=2)
ok = s["l40s"] and s["same_gpu_in_container"] and s["compat_passed"]
print("G2", "PASS" if ok else "FAIL", json.dumps(s, indent=1))
sys.exit(0 if ok else 1)
EOF
