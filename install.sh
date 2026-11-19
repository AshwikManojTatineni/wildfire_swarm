#!/usr/bin/env bash
# Login-node submitter for the setup job (Go2 install.sh pattern, adapted to Torch:
# no `ssh burst` hop, the account comes from config/torch.env, no partition, CPU only).
#   ./install.sh                 # pull base image, build both SIFs, fetch sources, prepare assets
#   ./install.sh --force         # rebuild the SIFs even if present
#   ./install.sh --assets-only   # only re-prepare assets (after a scratch purge or mission.yaml change)
set -euo pipefail
cd "$(dirname "$0")"
source scripts/cluster/ncr_env.sh
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "Commit your changes first: the setup job snapshots the committed HEAD." >&2
  exit 2
fi
active="$(ncr_active_jobs)"
if [[ -n "$active" ]]; then
  echo "A project job is already queued/running; setup would rewrite the assets it reads:" >&2
  echo "$active" >&2
  echo "Wait for it, or cancel it with: scancel <jobid>" >&2
  exit 3
fi
echo "Slurm account: $SLURM_ACCOUNT"
mail=(--mail-user="${MAIL_USER:-${USER}@nyu.edu}")   # Go2: e-mail on END/FAIL to the NetID address
mkdir -p "$NCR_SCRATCH/slurm_logs"
jobid=$(sbatch --parsable --account="$SLURM_ACCOUNT" \
  --job-name="ncr_install" \
  --cpus-per-task="$(ncr_cfg slurm.install.cpus)" \
  --mem="$(ncr_cfg slurm.install.mem)" \
  --time="$(ncr_cfg slurm.install.time)" \
  --output="$NCR_SCRATCH/slurm_logs/install_%j.out" \
  "${mail[@]}" \
  install.slurm "$@")
jobid="${jobid%%;*}"
echo "Submitted setup job $jobid. Follow it (Ctrl+C stops watching, not the job):"
echo "  tail -F $NCR_SCRATCH/slurm_logs/install_${jobid}.out"
