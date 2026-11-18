"""G3 preparation (network allowed): localize every asset the GPU scene job needs.

Run inside isaac_pegasus.sif with /workspace/assets mounted read-write:
  1. Export the seeded forest from the pinned generator's models -> /workspace/assets/forest
  2. Mirror the Nova Carter USD and its full dependency closure from the 5.1 asset root
     -> /workspace/assets/isaac/Isaac/... (same relative layout, so relative refs resolve
     and isaacsim.storage.native accepts the local root)
  3. Write /workspace/assets/asset_manifest.json (sha256 of every localized file)
"""
import hashlib, json, os, sys, time, traceback
from pathlib import Path

from isaacsim import SimulationApp

app = SimulationApp({"headless": True})

import yaml  # noqa: E402
import omni.client  # noqa: E402
from pxr import UsdUtils  # noqa: E402

from wildfire_swarm.forest.build_forest import build_forest  # noqa: E402  (PYTHONPATH set by isaac_exec.sh)

ASSETS = Path("/workspace/assets")
OUT = Path("/workspace/run/g3_prep")
OUT.mkdir(parents=True, exist_ok=True)
mission = yaml.safe_load(open("/workspace/src/config/mission.yaml"))
runtime = yaml.safe_load(open("/workspace/src/config/runtime.yaml"))
summary = {"errors": []}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# 1. Forest ----------------------------------------------------------------------------
try:
    p = mission["forest"]
    models = Path("/workspace/srccache/forest_generator/models")
    if not models.is_dir():
        raise FileNotFoundError(f"{models} missing: run ./install.sh first")
    t0 = time.time()
    rep = build_forest(models, ASSETS / "forest", p, p["seed"])
    rep["seconds"] = round(time.time() - t0, 1)
    rep["generator_commit"] = runtime["forest"]["generator_commit"]
    summary["forest"] = {k: rep[k] for k in ("counts", "corridor_max_slope", "remote_refs", "unresolved", "seconds")}
    if rep["remote_refs"]:
        summary["errors"].append(f"forest has remote refs: {rep['remote_refs'][:5]}")
except Exception as exc:
    traceback.print_exc()
    summary["errors"].append(f"forest: {exc!r}")

# 2. Nova Carter closure from the 5.1 asset root -----------------------------------------
try:
    from isaacsim.storage.native import get_assets_root_path

    root = get_assets_root_path()
    summary["asset_root"] = root
    if not root or root.startswith("/workspace"):
        raise RuntimeError(f"expected the remote 5.1 asset root, got {root!r}")
    chosen = None
    for rel in mission["robots"]["nova_carter_candidates"]:
        result, _ = omni.client.stat(root + rel)
        summary.setdefault("carter_candidates", {})[rel] = str(result)
        if result == omni.client.Result.OK and chosen is None:
            chosen = rel
    if chosen is None:
        raise FileNotFoundError("no Nova Carter candidate exists under the asset root")
    summary["nova_carter_rel"] = chosen

    layers, assets, unresolved = UsdUtils.ComputeAllDependencies(root + chosen)
    remote = [l.identifier for l in layers] + list(assets)
    copied, outside = [], []
    for src in remote:
        if not src.startswith(root):
            outside.append(src)
            continue
        dst = ASSETS / "isaac" / src[len(root):].lstrip("/")
        dst.parent.mkdir(parents=True, exist_ok=True)
        res = omni.client.copy(src, str(dst), behavior=omni.client.CopyBehavior.OVERWRITE)
        if res != omni.client.Result.OK:
            summary["errors"].append(f"copy failed {src}: {res}")
        copied.append(str(dst.relative_to(ASSETS)))
    summary["carter_files"] = len(copied)
    summary["carter_outside_root"] = outside
    summary["carter_unresolved"] = sorted({str(u) for u in unresolved})
    if outside:
        summary["errors"].append(f"{len(outside)} Carter dependencies outside the asset root")
except Exception as exc:
    traceback.print_exc()
    summary["errors"].append(f"nova_carter: {exc!r}")

# 3. Manifest -------------------------------------------------------------------------------
files = {str(p.relative_to(ASSETS)): sha256(p) for p in sorted(ASSETS.rglob("*"))
         if p.is_file() and p.name != "asset_manifest.json"}
manifest = {"created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "job_id": os.environ.get("SLURM_JOB_ID"), "summary": summary, "files": files}
(ASSETS / "asset_manifest.json").write_text(json.dumps(manifest, indent=1))
summary["n_files"] = len(files)
(OUT / "summary.json").write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))
app.close()
sys.exit(1 if summary["errors"] else 0)
