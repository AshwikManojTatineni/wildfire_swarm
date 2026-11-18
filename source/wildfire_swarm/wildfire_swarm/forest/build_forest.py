"""Seeded, headless forest exporter.

A port of joevento/Nvidia-Isaac-Sim-Procedual-Forest-Generator (MIT, commit
9e5fcbe3) from a Kit UI extension into a pure pxr + numpy function, so the
forest can be exported in a batch job and verified locally with usd-core.

Kept from the generator: fractal-noise terrain with a configured elevation
difference; trees chosen by density per 10x10 m and species mix, scaled by
age/100 with the species height multipliers (Birch/Pine 1.35, Spruce 1.25) and a
random yaw; rocks per 10x10 m; vegetation as Blueberry clusters (10 plants) or
single Bushes; the 0.4 m tree edge margin; the generator's model USDs.

Changes from the upstream extension:
* Every random draw comes from one seed (the generator reseeds from the clock).
* The `noise` package's Perlin noise is replaced by numpy value-noise fBm (6 octaves).
* Heights come from the generated heightfield, not PhysX raycasts.
* A drivable AMR corridor and a UAV takeoff patch are flattened and kept clear.
* Each tree gets an invisible cylinder trunk collider and each rock a sphere
  collider. Vegetation stays non-colliding. Rocks scale uniformly, because PhysX
  spheres need uniform scale.
* Copied model layers are relabelled metersPerUnit=1 and upAxis=Z. Their
  geometry is already metres/Z-up, but the metadata says cm/Y.
* No physics scene is authored; the simulator's World owns the only one.
"""
from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import numpy as np
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdPhysics, UsdShade, UsdUtils, Vt

HEIGHT_MULT = {"Birch": 1.35, "Spruce": 1.25, "Pine": 1.35}


# --------------------------------------------------------------------------- terrain
def terrain_height(hf, x: float, y: float) -> float:
    """Bilinear height at world (x, y). hf: mapping with h[ix, iy], x0, y0, res (rows = x)."""
    h, x0, y0, res = hf["h"], float(hf["x0"]), float(hf["y0"]), float(hf["res"])
    fx = min(max((x - x0) / res, 0.0), h.shape[0] - 1.0)
    fy = min(max((y - y0) / res, 0.0), h.shape[1] - 1.0)
    i, j = min(int(fx), h.shape[0] - 2), min(int(fy), h.shape[1] - 2)
    tx, ty = fx - i, fy - j
    return float((h[i, j] * (1 - tx) + h[i + 1, j] * tx) * (1 - ty)
                 + (h[i, j + 1] * (1 - tx) + h[i + 1, j + 1] * tx) * ty)


def _value_noise_fbm(rng, xs, ys, scale_m, octaves=6):
    total = np.zeros((xs.size, ys.size))
    amp = 1.0
    for o in range(octaves):
        cell = scale_m / (2 ** o)
        gx = (xs - xs[0]) / cell
        gy = (ys - ys[0]) / cell
        lattice = rng.uniform(-1.0, 1.0, (int(gx[-1]) + 2, int(gy[-1]) + 2))
        ix, iy = np.floor(gx).astype(int), np.floor(gy).astype(int)
        tx, ty = gx - ix, gy - iy
        sx, sy = tx * tx * (3 - 2 * tx), ty * ty * (3 - 2 * ty)
        a = lattice[np.ix_(ix, iy)]
        b = lattice[np.ix_(ix + 1, iy)]
        c = lattice[np.ix_(ix, iy + 1)]
        d = lattice[np.ix_(ix + 1, iy + 1)]
        sxm, sym = sx[:, None], sy[None, :]
        total += amp * ((a * (1 - sxm) + b * sxm) * (1 - sym) + (c * (1 - sxm) + d * sxm) * sym)
        amp *= 0.5
    return total


def _make_heightfield(params, rng):
    sx, sy = params["size_m"]
    res = params["grid_m"]
    xs = np.linspace(-sx / 2, sx / 2, int(round(sx / res)) + 1)
    ys = np.linspace(-sy / 2, sy / 2, int(round(sy / res)) + 1)
    n = _value_noise_fbm(rng, xs, ys, params["noise_scale_m"])
    n = (n - n.min()) / (n.max() - n.min() + 1e-12)
    h = (n - 0.5) * params["elevation_diff_m"]

    c = params["corridor"]
    hw_full = c["half_width_m"] + 1.5 * res
    band = np.abs(ys) <= c["half_width_m"]
    profile = h[:, band].mean(axis=1)
    win = max(1, int(round(c["profile_smooth_m"] / res)))
    pad = np.pad(profile, (win // 2, win - 1 - win // 2), mode="edge")
    profile = np.convolve(pad, np.ones(win) / win, mode="valid")
    mean = profile.mean()
    for _ in range(50):  # shrink relief until the surveyed slope limit holds
        if np.max(np.abs(np.diff(profile))) / res <= 0.9 * c["max_slope"]:
            break
        profile = mean + (profile - mean) * 0.8
    wy = np.clip(1 - (np.abs(ys) - hw_full) / c["blend_m"], 0, 1)
    wy[np.abs(ys) <= hw_full] = 1.0
    xlo, xhi = c["x_min"] - c["clearance_m"] - 1.5 * res, c["x_max"] + c["clearance_m"] + 1.5 * res
    dx = np.maximum(xlo - xs, xs - xhi)
    wx = np.clip(1 - dx / c["blend_m"], 0, 1)
    wx[dx <= 0] = 1.0
    w = wx[:, None] * wy[None, :]
    h = h * (1 - w) + profile[:, None] * w

    t = params["takeoff"]
    hf = {"h": h, "x0": xs[0], "y0": ys[0], "res": res}
    target = terrain_height(hf, t["x"], t["y"])
    d = np.hypot(xs[:, None] - t["x"], ys[None, :] - t["y"])
    r_full = t["radius_m"] + 1.5 * res
    wt = np.clip(1 - (d - r_full) / c["blend_m"], 0, 1)
    wt[d <= r_full] = 1.0
    h = h * (1 - wt) + target * wt
    corridor_slope = float(np.max(np.abs(np.diff(profile))) / res)
    return {"h": h, "x0": float(xs[0]), "y0": float(ys[0]), "res": float(res)}, xs, ys, corridor_slope


# --------------------------------------------------------------------------- placement
def _keep_out(params, x, y, extra=0.0):
    c, t = params["corridor"], params["takeoff"]
    k = c["half_width_m"] + c["clearance_m"] + extra
    if c["x_min"] - k <= x <= c["x_max"] + k and abs(y) < k:
        return True
    return math.hypot(x - t["x"], y - t["y"]) < t["radius_m"] + t["clearance_m"] + extra


def _sample_xy(rng, params, margin):
    sx, sy = params["size_m"]
    while True:
        x = rng.uniform(-sx / 2 + margin, sx / 2 - margin)
        y = rng.uniform(-sy / 2 + margin, sy / 2 - margin)
        if not _keep_out(params, x, y):
            return x, y


def _yaw_quat(deg):
    r = math.radians(deg) / 2
    return Gf.Quatf(math.cos(r), 0.0, 0.0, math.sin(r))


def _place(stage, path, ref, xyz, yaw_deg, scale):
    # Placement lives on our own Xform; the model (which carries its own root
    # xformOps) is referenced on a child so the two op stacks never collide.
    xf = UsdGeom.Xform.Define(stage, path)
    model = UsdGeom.Xform.Define(stage, path + "/Model").GetPrim()
    model.GetReferences().AddReference(ref)
    # Instanceable: the renderer/BVH store each model's mesh once, not once per tree.
    # Colliders stay on the (non-instanced) placement Xform, so physics is unaffected.
    model.SetInstanceable(True)
    xf.AddTranslateOp().Set(Gf.Vec3d(*map(float, xyz)))
    xf.AddOrientOp().Set(_yaw_quat(yaw_deg))
    xf.AddScaleOp().Set(Gf.Vec3f(*map(float, scale)))
    return xf


def _collider(stage, path, kind, **attrs):
    geom = (UsdGeom.Cylinder if kind == "cylinder" else UsdGeom.Sphere).Define(stage, path)
    for name, value in attrs.items():
        if name == "translate":
            geom.AddTranslateOp().Set(Gf.Vec3d(*value))
        else:
            geom.GetPrim().GetAttribute(name).Set(float(value) if isinstance(value, (int, float)) else value)
    geom.CreatePurposeAttr(UsdGeom.Tokens.guide)
    UsdPhysics.CollisionAPI.Apply(geom.GetPrim())
    return geom


# --------------------------------------------------------------------------- stage
def _copy_models(models_src: Path, out: Path, params) -> dict:
    refs = {}
    for name, rel in params["models"].items():
        src_dir = models_src / Path(rel).parent
        dst_dir = out / "models" / Path(rel).parent
        if not dst_dir.exists():
            shutil.copytree(src_dir, dst_dir, ignore=shutil.ignore_patterns("*.blend", ".thumbs"))
            for usd in dst_dir.glob("*.usd*"):
                layer = Sdf.Layer.FindOrOpen(str(usd))
                layer.pseudoRoot.SetInfo("metersPerUnit", 1.0)
                layer.pseudoRoot.SetInfo("upAxis", "Z")
                layer.Save()
        refs[name] = "./models/" + Path(rel).as_posix()
    return refs


def _terrain_mesh(stage, hf, xs, ys):
    h = hf["h"]
    nx, ny = h.shape
    xx, yy = np.meshgrid(xs, ys, indexing="ij")
    pts = np.stack([xx.ravel(), yy.ravel(), h.ravel()], axis=1).astype(np.float32)
    idx = np.arange(nx * ny).reshape(nx, ny)
    a, b, c, d = idx[:-1, :-1].ravel(), idx[1:, :-1].ravel(), idx[:-1, 1:].ravel(), idx[1:, 1:].ravel()
    faces = np.stack([np.stack([a, b, d], 1), np.stack([a, d, c], 1)], 1).reshape(-1)
    mesh = UsdGeom.Mesh.Define(stage, "/Forest/Terrain")
    mesh.CreatePointsAttr(Vt.Vec3fArray.FromNumpy(pts))
    mesh.CreateFaceVertexIndicesAttr(Vt.IntArray.FromNumpy(faces.astype(np.int32)))
    mesh.CreateFaceVertexCountsAttr(Vt.IntArray.FromNumpy(np.full(faces.size // 3, 3, np.int32)))
    mesh.CreateSubdivisionSchemeAttr(UsdGeom.Tokens.none)
    mesh.CreateExtentAttr([Gf.Vec3f(*map(float, pts.min(0))), Gf.Vec3f(*map(float, pts.max(0)))])
    UsdPhysics.CollisionAPI.Apply(mesh.GetPrim())
    UsdPhysics.MeshCollisionAPI.Apply(mesh.GetPrim()).CreateApproximationAttr("none")
    mat = UsdShade.Material.Define(stage, "/Forest/Looks/ForestFloor")
    sh = UsdShade.Shader.Define(stage, "/Forest/Looks/ForestFloor/Shader")
    sh.CreateIdAttr("UsdPreviewSurface")
    sh.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0.24, 0.19, 0.11))
    sh.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.95)
    mat.CreateSurfaceOutput().ConnectToSource(sh.ConnectableAPI(), "surface")
    UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(mat)


def _lights(stage):
    dome = UsdLux.DomeLight.Define(stage, "/Forest/Lights/Sky")
    dome.CreateIntensityAttr(700.0)
    dome.CreateColorAttr(Gf.Vec3f(0.78, 0.86, 1.0))
    sun = UsdLux.DistantLight.Define(stage, "/Forest/Lights/Sun")
    sun.CreateIntensityAttr(2500.0)
    sun.CreateAngleAttr(0.53)
    sun.CreateColorAttr(Gf.Vec3f(1.0, 0.95, 0.85))
    sun.AddRotateXYZOp().Set(Gf.Vec3f(35.0, 0.0, 30.0))


def build_forest(models_src, out_dir, params: dict, seed: int) -> dict:
    models_src, out = Path(models_src), Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    streams = np.random.SeedSequence(seed).spawn(4)
    rng_terrain, rng_trees, rng_rocks, rng_veg = (np.random.default_rng(s) for s in streams)

    refs = _copy_models(models_src, out, params)
    hf, xs, ys, corridor_slope = _make_heightfield(params, rng_terrain)
    np.savez(out / "heightfield.npz", **hf)

    usda = out / "forest.usda"
    if usda.exists():
        usda.unlink()
    stage = Usd.Stage.CreateNew(str(usda))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    root = UsdGeom.Xform.Define(stage, "/Forest")
    stage.SetDefaultPrim(root.GetPrim())
    stage.GetRootLayer().customLayerData = {"generator": "wildfire_swarm.forest.build_forest", "seed": int(seed)}
    _terrain_mesh(stage, hf, xs, ys)
    _lights(stage)

    sx, sy = params["size_m"]
    area = sx * sy
    counts = {"trees": 0, "rocks": 0, "vegetation": 0}
    UsdGeom.Scope.Define(stage, "/Forest/Trees")
    for species, pct in params["tree_mix_percent"].items():
        for _ in range(int(params["tree_density_per_100m2"] * area / 100 * pct / 100)):
            x, y = _sample_xy(rng_trees, params, params["edge_margin_m"])
            age = rng_trees.integers(params["tree_age_range"][0], params["tree_age_range"][1] + 1) / 100.0
            s = rng_trees.uniform(0.9, 1.1) * age
            sh = rng_trees.uniform(0.9, 1.1) * HEIGHT_MULT[species] * age
            yaw = float(rng_trees.integers(-180, 180))
            path = f"/Forest/Trees/Tree_{counts['trees']:04d}"
            _place(stage, path, refs[species], (x, y, terrain_height(hf, x, y)), yaw, (s, s, sh))
            th = params["trunk_collider_height_m"]
            _collider(stage, path + "/TrunkCollider", "cylinder", radius=params["trunk_radius_m"][species],
                      height=th, axis="Z", translate=(0.0, 0.0, th / 2))
            counts["trees"] += 1

    UsdGeom.Scope.Define(stage, "/Forest/Rocks")
    for _ in range(int(params["rocks_per_100m2"] * area / 100)):
        x, y = _sample_xy(rng_rocks, params, 0.3)
        s = rng_rocks.uniform(0.2, 0.3)
        path = f"/Forest/Rocks/Rock_{counts['rocks']:04d}"
        _place(stage, path, refs["Rock"], (x, y, terrain_height(hf, x, y)),
               float(rng_rocks.integers(-180, 180)), (s, s, s))
        _collider(stage, path + "/Collider", "sphere", radius=0.7)
        counts["rocks"] += 1

    UsdGeom.Scope.Define(stage, "/Forest/Vegetation")

    def plant(kind, x, y, scale):
        if _keep_out(params, x, y, extra=-params["corridor"]["clearance_m"] + 0.5):
            return
        path = f"/Forest/Vegetation/Plant_{counts['vegetation']:04d}"
        _place(stage, path, refs[kind], (x, y, terrain_height(hf, x, y)),
               float(rng_veg.integers(-180, 180)), scale)
        counts["vegetation"] += 1

    for _ in range(int(params["vegetation_per_100m2"] * area / 100)):
        if rng_veg.integers(0, 2) == 1:
            cx, cy = _sample_xy(rng_veg, params, 0.5)
            for _ in range(10):
                ox = rng_veg.choice([-1, 1]) * rng_veg.uniform(0.2, 0.4) + rng_veg.normal(0, 0.09)
                oy = rng_veg.choice([-1, 1]) * rng_veg.uniform(0.2, 0.4) + rng_veg.normal(0, 0.09)
                plant("Blueberry", cx + ox, cy + oy,
                      (rng_veg.uniform(0.8, 1.2), rng_veg.uniform(0.8, 1.2), rng_veg.uniform(0.8, 1.0)))
        else:
            x, y = _sample_xy(rng_veg, params, 0.5)
            plant("Bush", x, y, tuple(rng_veg.uniform(0.4, 1.0, 3)))

    stage.GetRootLayer().Save()

    c, t = params["corridor"], params["takeoff"]
    anchors = {
        "size_m": [sx, sy],
        "ugv_spawns": [{"name": f"ugv_{i + 1}", "x": float(x), "y": 0.0,
                        "z": terrain_height(hf, x, 0.0), "yaw_deg": 0.0}
                       for i, x in enumerate(params["ugv_spawns_x"])],
        "uav_takeoff": {"x": t["x"], "y": t["y"], "z": terrain_height(hf, t["x"], t["y"])},
        "corridor_polygon": [[c["x_min"], -c["half_width_m"]], [c["x_max"], -c["half_width_m"]],
                             [c["x_max"], c["half_width_m"]], [c["x_min"], c["half_width_m"]]],
        "overview_camera": {"eye": [-48.0, -38.0, 30.0], "target": [-18.0, -2.0, 0.0]},
    }
    (out / "anchors.json").write_text(json.dumps(anchors, indent=2))

    layers, assets, unresolved = UsdUtils.ComputeAllDependencies(str(usda))
    report = {
        "stage": str(usda), "seed": int(seed), "counts": counts,
        "corridor_max_slope": corridor_slope, "anchors": anchors,
        "remote_refs": [p for p in [l.identifier for l in layers] + list(assets) if "://" in p],
        "unresolved": sorted({Path(u).name for u in unresolved}),
        "n_layers": len(layers), "n_assets": len(assets),
    }
    (out / "forest_report.json").write_text(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    import argparse
    import yaml

    ap = argparse.ArgumentParser()
    ap.add_argument("models_src")
    ap.add_argument("out_dir")
    ap.add_argument("--mission", default=str(Path(__file__).resolve().parents[2] / "config" / "mission.yaml"))
    a = ap.parse_args()
    p = yaml.safe_load(open(a.mission))["forest"]
    print(json.dumps(build_forest(a.models_src, a.out_dir, p, p["seed"]), indent=2))
