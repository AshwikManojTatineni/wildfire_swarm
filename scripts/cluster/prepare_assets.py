"""Asset preparation, run by install.slurm (CPU setup job, network allowed).

Localizes every asset the GPU jobs need, using python3 + usd-core inside humble_ws.sif.
Like the Go2 project, setup runs on CPU and every simulator run gets a GPU.
  1. Export the seeded forest from the pinned generator's models -> assets/forest
  2. Mirror the Nova Carter USD closure from the Isaac Sim 5.1 asset root over HTTPS
     -> assets/isaac/Isaac/... (same relative layout)
  3. Check the mirrored Carter composes offline, and record its articulation and joints
  4. Write assets/asset_manifest.json (sha256 of every localized file)
"""
import hashlib, json, os, sys, time, traceback
from pathlib import Path

import yaml
from pxr import Usd, UsdPhysics

from wildfire_swarm.assets.mirror import mirror_usd
from wildfire_swarm.forest.build_forest import build_forest

ASSETS = Path("/workspace/assets")
OUT = Path("/workspace/run/assets")
OUT.mkdir(parents=True, exist_ok=True)
mission = yaml.safe_load(open("/workspace/src/config/mission.yaml"))
runtime = yaml.safe_load(open("/workspace/src/config/runtime.yaml"))
summary = {"errors": [], "warnings": []}
CORE_MDL = {"OmniPBR.mdl", "OmniPBR_Opacity.mdl", "OmniGlass.mdl"}  # shipped inside Isaac Sim, found via its MDL path


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# 1. Forest -------------------------------------------------------------------------------
try:
    p = mission["forest"]
    models = Path("/workspace/srccache/forest_generator/models")
    if not models.is_dir():
        raise FileNotFoundError(f"{models} missing: run ./install.sh first")
    t0 = time.time()
    rep = build_forest(models, ASSETS / "forest", p, p["seed"])
    summary["forest"] = {k: rep[k] for k in ("counts", "corridor_max_slope", "remote_refs", "unresolved")}
    summary["forest"]["seconds"] = round(time.time() - t0, 1)
    summary["forest"]["generator_commit"] = runtime["forest"]["generator_commit"]
    if rep["remote_refs"]:
        summary["errors"].append(f"forest has remote refs: {rep['remote_refs'][:5]}")
    missing = sorted(set(rep["unresolved"]) - CORE_MDL)
    if missing:
        summary["errors"].append(f"forest references files that are not there: {missing[:10]}")
except Exception as exc:
    traceback.print_exc()
    summary["errors"].append(f"forest: {exc!r}")

# 2-3. Nova Carter closure -----------------------------------------------------------------
try:
    root = runtime["assets"]["isaac_root_url"]
    summary["asset_root"] = root
    chosen, last_exc = None, None
    for rel in mission["robots"]["nova_carter_candidates"]:
        try:
            t0 = time.time()
            m = mirror_usd(root, rel, ASSETS / "isaac")
            chosen = rel
            break
        except FileNotFoundError as exc:
            last_exc = exc
            summary["warnings"].append(f"candidate not found: {rel}")
    if chosen is None:
        raise FileNotFoundError(f"no Nova Carter candidate under {root}: {last_exc}")
    summary["nova_carter_rel"] = chosen
    summary["carter_mirror"] = {k: m[k] for k in ("downloaded", "rewritten", "search_path_assets",
                                                  "outside_root", "missing", "udim")}
    summary["carter_mirror"]["files"] = len(m["files"])
    summary["carter_mirror"]["seconds"] = round(time.time() - t0, 1)
    if m["outside_root"]:
        summary["errors"].append(f"Carter references outside the asset root: {m['outside_root'][:5]}")
    if m["missing"]:
        summary["warnings"].append(f"{len(m['missing'])} unreferenceable paths (see carter_mirror.missing)")

    stage = Usd.Stage.Open(str(ASSETS / "isaac" / chosen.lstrip("/")))
    remote = [l.identifier for l in stage.GetUsedLayers() if "://" in l.identifier]
    roots = [str(p.GetPath()) for p in stage.Traverse() if p.HasAPI(UsdPhysics.ArticulationRootAPI)]
    joints = [p.GetName() for p in stage.Traverse() if p.IsA(UsdPhysics.RevoluteJoint)]
    graphs = [str(p.GetPath()) for p in stage.Traverse() if p.GetTypeName() == "OmniGraph"]
    summary["carter_offline"] = {"remote_layers": remote, "articulation_roots": roots,
                                 "revolute_joints": joints, "omnigraphs": graphs}
    if remote:
        summary["errors"].append(f"mirrored Carter still composes remote layers: {remote[:3]}")
    if len(roots) != 1:
        summary["errors"].append(f"expected one articulation root, found {roots}")
    if not {"joint_wheel_left", "joint_wheel_right"} <= set(joints):
        summary["warnings"].append(f"drive joint names differ from joint_wheel_left/right: {joints}")
except Exception as exc:
    traceback.print_exc()
    summary["errors"].append(f"nova_carter: {exc!r}")

# 4. Manifest --------------------------------------------------------------------------------
files = {str(p.relative_to(ASSETS)): sha256(p) for p in sorted(ASSETS.rglob("*"))
         if p.is_file() and p.name != "asset_manifest.json"}
manifest = {"created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "job_id": os.environ.get("SLURM_JOB_ID"), "summary": summary, "files": files}
(ASSETS / "asset_manifest.json").write_text(json.dumps(manifest, indent=1))
summary["n_files"] = len(files)
(OUT / "summary.json").write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))
sys.exit(1 if summary["errors"] else 0)
