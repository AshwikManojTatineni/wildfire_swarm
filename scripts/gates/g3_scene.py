"""G3 scene gate: forest + real robot assets load offline at 240 Hz physics / 60 Hz render,
colliders work, the Carter drives along the corridor, and the run is recorded to video.

Run inside isaac_pegasus.sif with WF_OFFLINE=1 (black-hole proxy) and read-only assets.
Evidence in /workspace/run/g3/: overview.mp4, chase.mp4, still_*.png, stage_report.json,
verdict.json. The video is gate evidence (Go2 play.py --video pattern), not a pass by itself.
"""
import json, math, os, sys, time, traceback
from pathlib import Path

import yaml

mission = yaml.safe_load(open("/workspace/src/config/mission.yaml"))
runtime = yaml.safe_load(open("/workspace/src/config/runtime.yaml"))
W, H = mission["render"]["video_resolution"]

from isaacsim import SimulationApp  # noqa: E402

app = SimulationApp({"headless": True, "width": W, "height": H, "renderer": "RayTracedLighting"})

import carb  # noqa: E402
import numpy as np  # noqa: E402

ASSETS = Path("/workspace/assets")
OUT = Path("/workspace/run/g3"); OUT.mkdir(parents=True, exist_ok=True)
LOCAL_ROOT = str(ASSETS / "isaac")
report = {"errors": [], "checks": {}}


def fail(msg):
    report["errors"].append(msg)
    print("G3 ERROR:", msg, flush=True)


# Offline asset root BEFORE anything imports pegasus.simulator.params (it resolves the root at import).
settings = carb.settings.get_settings()
for key in ("/persistent/isaac/asset_root/default", "/persistent/isaac/asset_root/cloud",
            "/persistent/isaac/asset_root/nvidia"):
    settings.set(key, LOCAL_ROOT)

from isaacsim.core.utils.extensions import enable_extension  # noqa: E402

enable_extension("omni.isaac.dynamic_control")  # Pegasus vehicles use it (deprecated in 5.x)
app.update()

from isaacsim.core.api.world import World  # noqa: E402  (same class PegasusInterface uses)
from isaacsim.core.prims import SingleArticulation  # noqa: E402
from isaacsim.core.utils.types import ArticulationAction  # noqa: E402
from isaacsim.sensors.camera import Camera  # noqa: E402
from omni.physx import get_physx_scene_query_interface  # noqa: E402
from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics  # noqa: E402
from scipy.spatial.transform import Rotation  # noqa: E402

from pegasus.simulator.params import ROBOTS  # noqa: E402
from pegasus.simulator.logic.interface.pegasus_interface import PegasusInterface  # noqa: E402
from pegasus.simulator.logic.vehicles.multirotor import Multirotor, MultirotorConfig  # noqa: E402

asset_manifest = json.loads((ASSETS / "asset_manifest.json").read_text())
carter_rel = asset_manifest["summary"]["nova_carter_rel"]
anchors = json.loads((ASSETS / "forest" / "anchors.json").read_text())
report["pegasus_assets_root"] = __import__("pegasus.simulator.params", fromlist=["NVIDIA_ASSETS_PATH"]).NVIDIA_ASSETS_PATH

# --- World with the project rates (Pegasus default is 1/250) ----------------------------------
physics_hz, render_hz = runtime["rates"]["physics_hz"], runtime["rates"]["render_hz"]
pg = PegasusInterface()
pg.set_world_settings(physics_dt=1.0 / physics_hz, rendering_dt=1.0 / render_hz, stage_units_in_meters=1.0)
pg._world = World(**pg._world_settings)
world = pg.world
stage = world.stage
report["world_settings"] = {k: (float(v) if isinstance(v, (int, float)) else v) for k, v in pg._world_settings.items()}

# --- Forest, anchors, robots ------------------------------------------------------------------
pg.load_asset(str(ASSETS / "forest" / "forest.usda"), "/World/Environment")
UsdGeom.Scope.Define(stage, "/World/Anchors")
for s in anchors["ugv_spawns"]:
    UsdGeom.Xform.Define(stage, f"/World/Anchors/{s['name']}_spawn").AddTranslateOp().Set(Gf.Vec3d(s["x"], s["y"], s["z"]))
tk = anchors["uav_takeoff"]
UsdGeom.Xform.Define(stage, "/World/Anchors/uav_takeoff").AddTranslateOp().Set(Gf.Vec3d(tk["x"], tk["y"], tk["z"]))

uav_cfg = MultirotorConfig()
uav_cfg.backends = []  # parked for G3; G4 attaches the nonlinear controller
Multirotor("/World/Robots/uav_1", ROBOTS["Iris"], 0, [tk["x"], tk["y"], tk["z"] + 0.07],
           Rotation.from_euler("XYZ", [0.0, 0.0, 0.0]).as_quat(), config=uav_cfg)

s1 = anchors["ugv_spawns"][0]
ugv = UsdGeom.Xform.Define(stage, "/World/Robots/ugv_1")
ugv.AddTranslateOp().Set(Gf.Vec3d(s1["x"], s1["y"], s1["z"] + 0.05))
body = stage.DefinePrim("/World/Robots/ugv_1/nova_carter")
body.GetReferences().AddReference(LOCAL_ROOT + carter_rel)

# Asset-native ROS graphs must not own TF: deactivate any OmniGraph in robots.
graphs = [p for p in Usd.PrimRange(stage.GetPrimAtPath("/World/Robots")) if p.GetTypeName() == "OmniGraph"]
for g in graphs:
    g.SetActive(False)
report["deactivated_robot_graphs"] = [str(g.GetPath()) for g in graphs]

# --- Offline proof: no composed layer or asset path is remote --------------------------------
remote_layers = [l.identifier for l in stage.GetUsedLayers() if "://" in l.identifier]
remote_assets = []
for prim in stage.Traverse():
    for attr in prim.GetAttributes():
        if attr.GetTypeName() == Sdf.ValueTypeNames.Asset:
            v = attr.Get()
            rp = getattr(v, "resolvedPath", "") or getattr(v, "path", "")
            if "://" in rp:
                remote_assets.append(f"{prim.GetPath()}.{attr.GetName()}={rp}")
report["checks"]["remote_layers"] = remote_layers
report["checks"]["remote_asset_paths"] = remote_assets[:20]
report["checks"]["offline_ok"] = not remote_layers and not remote_assets
report["checks"]["stage_meters_per_unit"] = UsdGeom.GetStageMetersPerUnit(stage)
report["checks"]["stage_up_axis"] = str(UsdGeom.GetStageUpAxis(stage))

# --- Cameras (isaacsim.sensors.camera.Camera) ---------------------------------
def look_at_quat(eye, target):
    f = np.asarray(target, float) - np.asarray(eye, float)
    yaw = math.atan2(f[1], f[0])
    pitch = math.atan2(-f[2], math.hypot(f[0], f[1]))
    x, y, z, w = Rotation.from_euler("ZYX", [yaw, pitch, 0.0]).as_quat()
    return np.array([w, x, y, z])


ov = anchors["overview_camera"]
cam_over = Camera("/World/Cameras/Overview", resolution=(W, H),
                  position=np.array(ov["eye"]), orientation=look_at_quat(ov["eye"], ov["target"]))
cam_chase = Camera("/World/Cameras/Chase", resolution=(W, H),
                   position=np.array([s1["x"] - 6, s1["y"] - 2, s1["z"] + 3]),
                   orientation=look_at_quat([s1["x"] - 6, s1["y"] - 2, s1["z"] + 3], [s1["x"] + 2, 0, s1["z"]]))

# --- Physics step accounting -------------------------------------------------------------------
phys_dts = []
world.add_physics_callback("wf_dt_probe", lambda dt: phys_dts.append(dt))

world.reset()
for cam in (cam_over, cam_chase):
    cam.initialize()
    cam.set_focal_length(1.8)
    cam.set_clipping_range(0.05, 500.0)

# --- Collider checks with PhysX scene queries ----------------------------------------------------
sq = get_physx_scene_query_interface()
terrain_hits = []
for x in (-20.0, 0.0, 20.0):
    hit = sq.raycast_closest(carb.Float3(x, 0.0, 30.0), carb.Float3(0, 0, -1), 100.0)
    terrain_hits.append(hit.get("collision", "") if hit.get("hit") else "")
report["checks"]["terrain_raycasts"] = terrain_hits
report["checks"]["terrain_collider_ok"] = all(h.endswith("/Terrain") for h in terrain_hits)
tree0 = stage.GetPrimAtPath("/World/Environment/Trees/Tree_0000")
tpos = UsdGeom.Xformable(tree0).ComputeLocalToWorldTransform(Usd.TimeCode.Default()).ExtractTranslation()
hit = sq.raycast_closest(carb.Float3(tpos[0] - 3.0, tpos[1], tpos[2] + 1.0), carb.Float3(1, 0, 0), 6.0)
report["checks"]["trunk_raycast"] = hit.get("collision", "") if hit.get("hit") else ""
report["checks"]["trunk_collider_ok"] = report["checks"]["trunk_raycast"].endswith("TrunkCollider")

# --- Carter articulation and wheel drive ------------------------------------------------------------
art_root = next((p.GetPath() for p in Usd.PrimRange(body) if p.HasAPI(UsdPhysics.ArticulationRootAPI)), None)
if art_root is None:
    fail("no ArticulationRootAPI under the Nova Carter reference")
carter = SingleArticulation(prim_path=str(art_root), name="ugv_1")
carter.initialize()
dof = list(carter.dof_names)
report["carter_dofs"] = dof
wheels = [i for i, n in enumerate(dof) if "wheel" in n.lower() and "caster" not in n.lower()]
left = [i for i in wheels if "left" in dof[i].lower()]
right = [i for i in wheels if "right" in dof[i].lower()]
if len(left) != 1 or len(right) != 1:
    fail(f"could not identify left/right drive wheels in {dof}")
drive = mission["robots"]["g3_drive"]
omega = drive["speed_mps"] / mission["robots"]["carter_wheel_radius_m"]
p0, _ = carter.get_world_pose()

# --- Run + record -------------------------------------------------------------------------------
import imageio.v2 as imageio  # noqa: E402  (baked into the SIF)

fps, seconds = mission["render"]["video_fps"], mission["render"]["video_seconds"]
every = max(1, round(render_hz / fps))
writers = {n: imageio.get_writer(str(OUT / f"{n}.mp4"), fps=fps, codec="libx264", quality=7,
                                 macro_block_size=8) for n in ("overview", "chase")}
frames = {"overview": 0, "chase": 0}
uav = pg.get_vehicle("/World/Robots/uav_1") if hasattr(pg, "get_vehicle") else None
world.play()
for _ in range(30):  # shader/renderer warmup frames, not recorded
    world.step(render=True)
phys_dts.clear()
t_wall = time.time()
n_render = int(seconds * render_hz)
for k in range(n_render):
    t = k / render_hz
    v = omega if t < drive["seconds"] else 0.0
    if left and right:
        carter.apply_action(ArticulationAction(joint_velocities=np.array([v, v]),
                                               joint_indices=np.array([left[0], right[0]])))
    world.step(render=True)
    pos, _ = carter.get_world_pose()
    cam_chase.set_world_pose(position=np.array([pos[0] - 6, pos[1] - 2, pos[2] + 3]),
                             orientation=look_at_quat([pos[0] - 6, pos[1] - 2, pos[2] + 3], [pos[0] + 2, pos[1], pos[2]]))
    if k % every == 0:
        for name, cam in (("overview", cam_over), ("chase", cam_chase)):
            rgba = cam.get_rgba()
            if rgba is not None and rgba.size and rgba.ndim == 3:
                writers[name].append_data(np.ascontiguousarray(rgba[:, :, :3]))
                frames[name] += 1
                if frames[name] in (1, int(seconds * fps // 2)):
                    imageio.imwrite(str(OUT / f"still_{name}_{frames[name]:04d}.png"), rgba[:, :, :3])
for w_ in writers.values():
    w_.close()
wall = time.time() - t_wall

p1, _ = carter.get_world_pose()
dts = np.array(phys_dts)
report["timing"] = {
    "render_steps": n_render, "physics_steps": int(dts.size),
    "physics_steps_per_render": float(dts.size / max(n_render, 1)),
    "physics_dt_mean": float(dts.mean()) if dts.size else None,
    "physics_dt_max_abs_err": float(np.max(np.abs(dts - 1.0 / physics_hz))) if dts.size else None,
    "sim_seconds": float(dts.sum()), "wall_seconds": round(wall, 2),
    "real_time_factor": float(dts.sum() / wall) if wall > 0 else None,
}
report["frames"] = frames
report["carter"] = {"start": [float(x) for x in p0], "end": [float(x) for x in p1],
                    "dx": float(p1[0] - p0[0]), "dy": float(p1[1] - p0[1]), "dz": float(p1[2] - p0[2])}
if uav is not None:
    report["uav_1_final_pos"] = [float(x) for x in uav.state.position]

c = report["checks"]
c["rates_ok"] = (dts.size > 0 and abs(dts.mean() - 1.0 / physics_hz) < 1e-6
                 and abs(report["timing"]["physics_steps_per_render"] - physics_hz / render_hz) < 0.05)
c["carter_drove_ok"] = (report["carter"]["dx"] >= drive["min_distance_m"]
                        and abs(report["carter"]["dy"]) <= drive["max_lateral_m"]
                        and abs(report["carter"]["dz"]) < 0.5)
c["video_ok"] = all(n >= int(0.9 * seconds * fps) for n in frames.values())
passed = not report["errors"] and all(c[k] for k in ("offline_ok", "terrain_collider_ok", "trunk_collider_ok",
                                                      "rates_ok", "carter_drove_ok", "video_ok"))
verdict = {"gate": "G3", "pass": bool(passed),
           "rules": {"offline_ok": "no composed layer or asset path contains ://",
                     "terrain_collider_ok": "3 downward raycasts on the corridor hit /Terrain",
                     "trunk_collider_ok": "horizontal raycast at 1 m hits the first tree's TrunkCollider",
                     "rates_ok": f"mean physics dt = 1/{physics_hz} (±1e-6) and {physics_hz // render_hz} physics steps per render",
                     "carter_drove_ok": f"dx >= {drive['min_distance_m']} m, |dy| <= {drive['max_lateral_m']} m, |dz| < 0.5 m",
                     "video_ok": ">= 90% of expected frames in both videos"},
           "measured": {k: c[k] for k in c}}
(OUT / "stage_report.json").write_text(json.dumps(report, indent=2, default=str))
(OUT / "verdict.json").write_text(json.dumps(verdict, indent=2, default=str))
print(json.dumps(verdict, indent=2, default=str), flush=True)
world.stop()
app.close()
