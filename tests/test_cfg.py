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
                "dds.rmw", "slurm.gpu_constraint", "slurm.small.cpus", "slurm.small.mem",
                "slurm.small.time", "slurm.large.time", "rates.physics_hz", "nvidia_env.PRIVACY_CONSENT"]:
        node = ref
        for part in key.split("."):
            node = node[part]
        code, out, err = get(key)
        assert code == 0, err
        assert out == str(node), key


def test_missing_key_fails():
    code, out, _ = get("image.nope")
    assert code != 0 and out == ""
