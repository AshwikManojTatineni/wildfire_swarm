#!/usr/bin/env bash
# Login-node submitter for the setup job (Go2 install.sh pattern, adapted to Torch:
# no `ssh burst` hop, the account comes from config/torch.env, no partition).
#   ./install.sh            # pull base image, build both SIFs, fetch forest generator
#   ./install.sh --force    # rebuild SIFs even if present
set -euo pipefail
cd "$(dirname "$0")"
source scripts/cluster/wf_env.sh
mkdir -p "$WF_SCRATCH/slurm_logs"
sbatch --account="$SLURM_ACCOUNT" \
  --job-name="wf_install" \
  --cpus-per-task="$(wf_cfg slurm.install.cpus)" \
  --mem="$(wf_cfg slurm.install.mem)" \
  --time="$(wf_cfg slurm.install.time)" \
  --output="$WF_SCRATCH/slurm_logs/install_%j.out" \
  install.slurm "$@"
