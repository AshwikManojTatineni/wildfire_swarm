#!/usr/bin/env python3
"""Write manifest.json for one run: source/config snapshot, image digests, dependency
versions, exact command, job ID and hardware. Host python3, stdlib only.
"""
import argparse, datetime, json, os, platform, subprocess
from pathlib import Path


def sh(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=120).stdout.strip()
    except Exception as exc:  # recorded, never fatal
        return f"ERROR: {exc}"


def read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--command", required=True)
    args = ap.parse_args()
    env = os.environ
    sif_dir, repo = env.get("WF_SIF_DIR", ""), env.get("WF_REPO", "")
    sel = ["-i", env["CUDA_VISIBLE_DEVICES"].split(",")[0]] if env.get("CUDA_VISIBLE_DEVICES") else []
    gpu = sh("nvidia-smi", *sel, "--query-gpu=name,uuid,driver_version,memory.total", "--format=csv,noheader")
    digests = {}
    for line in read(f"{sif_dir}/digests.txt").splitlines():
        parts = line.split()
        if len(parts) == 2:
            digests[Path(parts[1]).name] = parts[0]
    base_inspect = read(f"{sif_dir}/isaac-sim_5.1.0.inspect.json")
    manifest = {
        "job_id": env.get("SLURM_JOB_ID"),
        "restart": env.get("SLURM_RESTART_COUNT", "0"),
        "gate": env.get("WF_GATE"),
        "command": args.command,
        "node": platform.node(),
        "cpus": env.get("SLURM_CPUS_PER_TASK"),
        "mem_per_node_mb": env.get("SLURM_MEM_PER_NODE"),
        "cuda_visible_devices": env.get("CUDA_VISIBLE_DEVICES"),
        "gpu": gpu,
        "apptainer": sh("apptainer", "--version"),
        "sif_and_source_digests": digests,
        "base_image_inspect_present": bool(base_inspect),
        "pegasus_commit_in_image": read(f"{sif_dir}/isaac_versions.txt").splitlines()[:1],
        "git_sha": sh("git", "-C", repo, "rev-parse", "HEAD"),
        "git_dirty": bool(sh("git", "-C", repo, "status", "--porcelain", "--untracked-files=no")),
        "ros_domain_id": env.get("ROS_DOMAIN_ID"),
        "run_dir": env.get("WF_RUN_DIR"),
        "start_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    Path(args.out).write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
