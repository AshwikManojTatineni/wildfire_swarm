#!/usr/bin/env bash
# Shared environment for install/run submitters and Slurm jobs. Source it:
#   source scripts/cluster/wf_env.sh
# Requires config/torch.env (copied from config/torch.env.example).

_wf_here="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# Jobs snapshot the committed code with `git archive HEAD`, so a copied folder (scp, zip) cannot run.
if [[ ! -e "$_wf_here/.git" ]]; then
  echo "wf_env: $_wf_here is not a git clone (no .git). Clone it instead of copying it:" >&2
  echo "  git clone <your-repo-url> <folder>" >&2
  return 2 2>/dev/null || exit 2
fi
# Optional overrides; created from the example on first use, so no manual copy is needed.
[[ -f "$_wf_here/config/torch.env" ]] || cp "$_wf_here/config/torch.env.example" "$_wf_here/config/torch.env"
if ! bash -n "$_wf_here/config/torch.env" 2>/dev/null; then
  echo "wf_env: config/torch.env has a syntax error (often a mangled paste). Delete it; it is recreated:" >&2
  echo "  rm $_wf_here/config/torch.env" >&2
  return 2 2>/dev/null || exit 2
fi
# shellcheck disable=SC1091
source "$_wf_here/config/torch.env"
# The repo is wherever this checkout lives (any folder name); torch.env does not set it.
export WF_REPO="$_wf_here"
export WF_SCRATCH="${WF_SCRATCH:-/scratch/$USER/wildfire_work}"
export WF_CFG="$WF_REPO/config/runtime.yaml"
wf_cfg() { python3 "$WF_REPO/scripts/cluster/cfg.py" "$WF_CFG" "$1"; }
export -f wf_cfg

# Slurm account: torch.env if set; inside a job, the job's own account; otherwise the project
# account from runtime.yaml (slurm.account, project 742). If Slurm lists a longer name that starts
# with it (e.g. torch_pr_742_<suffix>), that exact listed name is used.
if [[ -z "${SLURM_ACCOUNT:-}" || "$SLURM_ACCOUNT" == torch_pr_XXXX_XXXXX ]]; then
  _wf_acct="$(wf_cfg slurm.account)"
  _wf_listed="$(sacctmgr -n -P show assoc user="$USER" format=account 2>/dev/null | grep "^${_wf_acct}" | head -n 1 || true)"
  SLURM_ACCOUNT="${SLURM_JOB_ACCOUNT:-${_wf_listed:-$_wf_acct}}"
  unset _wf_acct _wf_listed
fi
export SLURM_ACCOUNT

export WF_SIF_DIR="$WF_SCRATCH/sif"
export WF_CACHE="$WF_SCRATCH/cache"
export WF_ASSETS="$WF_SCRATCH/assets"
export WF_SRC_CACHE="$WF_SCRATCH/src"
export APPTAINER_CACHEDIR="$WF_SCRATCH/apptainer-cache"
export WF_ISAAC_SIF="$WF_SIF_DIR/$(wf_cfg image.isaac_sif)"
export WF_HUMBLE_SIF="$WF_SIF_DIR/$(wf_cfg image.humble_sif)"

# Inside a job: per-attempt run directory (requeue-safe) and isolated DDS domain.
if [[ -n "${SLURM_JOB_ID:-}" ]]; then
  export WF_RUN_DIR="${WF_RUN_DIR:-$WF_SCRATCH/runs/${SLURM_JOB_ID}_r${SLURM_RESTART_COUNT:-0}}"
  export ROS_DOMAIN_ID=$((1 + SLURM_JOB_ID % 100))
  # Image builds unpack ~25 GB here; node-local /tmp may be smaller, scratch (flash) is not.
  export APPTAINER_TMPDIR="$WF_SCRATCH/tmp/apptainer-$SLURM_JOB_ID"
fi
export ROS_LOCALHOST_ONLY="$(wf_cfg dds.localhost_only)"
export RMW_IMPLEMENTATION="$(wf_cfg dds.rmw)"
# Only one wildfire job at a time: setup rewrites the assets a run job reads, and each run
# job holds a whole L40S. Prints the active job lines; empty output means none.
wf_active_jobs() { squeue --me --noheader --format='%i %j %T' 2>/dev/null | awk '$2 ~ /^wf_(run|install)$/' || true; }
unset _wf_here
