"""scripts/cluster/cfg.py must read config/runtime.yaml exactly like PyYAML for the keys shell scripts use."""
import subprocess, sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "scripts" / "cluster" / "cfg.py"
YAML = ROOT / "config" / "runtime.yaml"


def get(key):
    out = subprocess.run([sys.executable, "-I", str(CFG), str(YAML), key],
                         capture_output=True, text=True)
    return out.returncode, out.stdout.strip(), out.stderr


def test_scalars_match_pyyaml():
    ref = yaml.safe_load(YAML.read_text())
    for key in ["image.base", "image.isaac_sif", "image.humble_sif", "pegasus.commit", "pegasus.tag",
                "dds.rmw", "slurm.account", "slurm.gpu_constraint", "slurm.gpu_short.cpus", "slurm.gpu.mem", "assets.isaac_root_url",
                "slurm.gpu_short.time", "slurm.gpu_large.time", "gpu_budget.warn_fraction", "rates.physics_hz", "nvidia_env.PRIVACY_CONSENT"]:
        node = ref
        for part in key.split("."):
            node = node[part]
        code, out, err = get(key)
        assert code == 0, err
        assert out == str(node), key


def test_missing_key_fails():
    code, out, _ = get("image.nope")
    assert code != 0 and out == ""


def test_slurm_header_account_matches_runtime_config():
    """install.slurm / run.slurm carry the account in their #SBATCH header (Go2 style);
    it must stay equal to slurm.account in config/runtime.yaml."""
    want = yaml.safe_load(YAML.read_text())["slurm"]["account"]
    for job in ("install.slurm", "run.slurm"):
        lines = (ROOT / job).read_text().splitlines()
        accts = [l.split("=", 1)[1].strip() for l in lines if l.startswith("#SBATCH --account=")]
        assert accts == [want], (job, accts)
        assert not [l for l in lines if l.startswith("#SBATCH --partition")], job  # Torch: no manual partitions
