"""Forest exporter tests (pure pxr + numpy; run locally with usd-core, in Kit on Torch)."""
import copy
import math
from pathlib import Path

import numpy as np
import pytest
import yaml
from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics, UsdUtils

from wildfire_swarm.forest.build_forest import build_forest, terrain_height

ROOT = Path(__file__).resolve().parents[1]
PARAMS = yaml.safe_load((ROOT / "config" / "mission.yaml").read_text())["forest"]
ALLOWED_UNRESOLVED = {"OmniPBR.mdl", "OmniPBR_Opacity.mdl"}  # Kit core MDLs, shipped in the image


def _fake_model(dirpath: Path, name: str, height: float):
    """A generator-like model: metersPerUnit 0.01 + upAxis Y metadata, metre/Z-up geometry."""
    dirpath.mkdir(parents=True)
    (dirpath / "textures").mkdir()
    (dirpath / "textures" / "bark.png").write_bytes(b"\x89PNG fake")
    stage = Usd.Stage.CreateNew(str(dirpath / f"{name}.usd"))
    UsdGeom.SetStageMetersPerUnit(stage, 0.01)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    world = UsdGeom.Xform.Define(stage, "/World")
    # The real generator models carry their own root xformOps (translate/orient/scale).
    world.AddTranslateOp().Set((0.0, 0.0, 0.0))
    world.AddOrientOp().Set(Gf.Quatf(1, 0, 0, 0))
    world.AddScaleOp().Set((1.0, 1.0, 1.0))
    stage.SetDefaultPrim(world.GetPrim())
    cube = UsdGeom.Cube.Define(stage, "/World/geo")
    cube.AddScaleOp().Set((0.5, 0.5, height / 2))
    shader = stage.DefinePrim("/World/Looks/M/Shader", "Shader")
    shader.CreateAttribute("info:mdl:sourceAsset", Sdf.ValueTypeNames.Asset).Set("OmniPBR.mdl")
    shader.CreateAttribute("inputs:diffuse_texture", Sdf.ValueTypeNames.Asset).Set("./textures/bark.png")
    stage.GetRootLayer().Save()


@pytest.fixture(scope="module")
def models(tmp_path_factory):
    src = tmp_path_factory.mktemp("generator_models")
    for name, h in [("Birch", 10), ("Spruce", 11), ("Pine", 10), ("Rock", 0.7), ("Bush", 1.7), ("Blueberry", 0.4)]:
        _fake_model(src / f"{name}_obj", name, h)
    return src


@pytest.fixture(scope="module")
def built(models, tmp_path_factory):
    out = tmp_path_factory.mktemp("forest")
    report = build_forest(models, out, PARAMS, seed=PARAMS["seed"])
    return out, report


def test_stage_units_axis_default_prim(built):
    out, _ = built
    stage = Usd.Stage.Open(str(out / "forest.usda"))
    assert UsdGeom.GetStageMetersPerUnit(stage) == 1.0
    assert UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.z
    assert stage.GetDefaultPrim().GetPath() == Sdf.Path("/Forest")


def test_no_physics_scene_authored(built):
    # One physics scene per simulation: the World creates it, the forest must not.
    stage = Usd.Stage.Open(str(built[0] / "forest.usda"))
    assert not [p for p in stage.Traverse() if p.IsA(UsdPhysics.Scene)]


def test_dependencies_local_and_resolved(built):
    out, report = built
    layers, assets, unresolved = UsdUtils.ComputeAllDependencies(str(out / "forest.usda"))
    paths = [l.identifier for l in layers] + list(assets)
    assert not [p for p in paths if "://" in p]
    assert {Path(u).name for u in unresolved} <= ALLOWED_UNRESOLVED
    assert all(Path(p).resolve().is_relative_to(out.resolve()) for p in paths)
    assert report["remote_refs"] == [] and set(report["unresolved"]) <= ALLOWED_UNRESOLVED


def test_copied_models_normalised_to_metres_z_up(built):
    out, _ = built
    for usd in (out / "models").glob("*_obj/*.usd"):
        layer = Sdf.Layer.FindOrOpen(str(usd))
        assert layer.pseudoRoot.GetInfo("metersPerUnit") == 1.0, usd
        assert layer.pseudoRoot.GetInfo("upAxis") == "Z", usd


def test_deterministic_for_seed(models, tmp_path):
    a = build_forest(models, tmp_path / "a", PARAMS, seed=7)
    b = build_forest(models, tmp_path / "b", PARAMS, seed=7)
    c = build_forest(models, tmp_path / "c", PARAMS, seed=8)
    ta = (tmp_path / "a" / "forest.usda").read_text()
    assert ta == (tmp_path / "b" / "forest.usda").read_text()
    assert ta != (tmp_path / "c" / "forest.usda").read_text()
    assert a["counts"] == b["counts"]


def _instances(stage, group):
    prim = stage.GetPrimAtPath(f"/Forest/{group}")
    out = list(prim.GetChildren())
    for p in out:  # placement Xform wraps the referenced model in a child "Model"
        model = p.GetChild("Model")
        assert model.HasAuthoredReferences(), p.GetPath()
        # Instanced so the GPU stores each species mesh once (~150M -> ~1.6M unique triangles).
        assert model.IsInstanceable(), p.GetPath()
    return out


def test_vegetation_is_instanced(built):
    stage = Usd.Stage.Open(str(built[0] / "forest.usda"))
    plants = list(stage.GetPrimAtPath("/Forest/Vegetation").GetChildren())
    assert plants and all(p.GetChild("Model").IsInstanceable() for p in plants)
    assert len(stage.GetPrototypes()) <= 6   # one prototype per model file


def test_counts_follow_generator_densities(built):
    _, report = built
    sx, sy = PARAMS["size_m"]
    area = sx * sy
    expected_trees = sum(int(PARAMS["tree_density_per_100m2"] * area / 100 * pct / 100)
                         for pct in PARAMS["tree_mix_percent"].values())
    assert report["counts"]["trees"] == expected_trees
    assert report["counts"]["rocks"] == int(PARAMS["rocks_per_100m2"] * area / 100)


def test_objects_sit_on_terrain_and_corridor_is_clear(built):
    out, report = built
    stage = Usd.Stage.Open(str(out / "forest.usda"))
    hf = np.load(out / "heightfield.npz")
    c = PARAMS["corridor"]
    keep_out = c["half_width_m"] + c["clearance_m"]
    for group in ("Trees", "Rocks"):
        for prim in _instances(stage, group):
            t = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default()).ExtractTranslation()
            assert t[2] == pytest.approx(terrain_height(hf, t[0], t[1]), abs=1e-4)
            in_x = c["x_min"] - keep_out <= t[0] <= c["x_max"] + keep_out
            assert not (in_x and abs(t[1]) < keep_out), (group, tuple(t))
            tk = PARAMS["takeoff"]
            assert math.hypot(t[0] - tk["x"], t[1] - tk["y"]) >= tk["radius_m"] + tk["clearance_m"]


def test_every_tree_has_trunk_collider_and_terrain_collides(built):
    stage = Usd.Stage.Open(str(built[0] / "forest.usda"))
    trees = _instances(stage, "Trees")
    assert trees
    for tree in trees:
        col = stage.GetPrimAtPath(tree.GetPath().AppendChild("TrunkCollider"))
        assert col.IsA(UsdGeom.Cylinder) and col.HasAPI(UsdPhysics.CollisionAPI)
        assert UsdGeom.Imageable(col).GetPurposeAttr().Get() == UsdGeom.Tokens.guide
    terrain = stage.GetPrimAtPath("/Forest/Terrain")
    assert terrain.HasAPI(UsdPhysics.CollisionAPI) and terrain.HasAPI(UsdPhysics.MeshCollisionAPI)
    assert UsdPhysics.MeshCollisionAPI(terrain).GetApproximationAttr().Get() == "none"


def test_corridor_drivable_and_takeoff_flat(built):
    out, report = built
    hf = np.load(out / "heightfield.npz")
    c, tk = PARAMS["corridor"], PARAMS["takeoff"]
    xs = np.arange(c["x_min"], c["x_max"], 0.25)
    for y in (-c["half_width_m"], 0.0, c["half_width_m"]):
        z = np.array([terrain_height(hf, x, y) for x in xs])
        assert np.max(np.abs(np.diff(z) / 0.25)) <= c["max_slope"]
    ring = [terrain_height(hf, tk["x"] + r * math.cos(a), tk["y"] + r * math.sin(a))
            for r in (0, tk["radius_m"] * 0.5, tk["radius_m"]) for a in np.linspace(0, 2 * math.pi, 12)]
    assert max(ring) - min(ring) < 0.05
    assert report["corridor_max_slope"] <= c["max_slope"]


def test_anchors_report(built):
    out, report = built
    a = report["anchors"]
    assert [s["name"] for s in a["ugv_spawns"]] == ["ugv_1", "ugv_2", "ugv_3", "ugv_4"]
    hf = np.load(out / "heightfield.npz")
    for s in a["ugv_spawns"]:
        assert s["y"] == 0.0 and s["z"] == pytest.approx(terrain_height(hf, s["x"], s["y"]), abs=1e-6)
    assert a["uav_takeoff"]["z"] == pytest.approx(terrain_height(hf, a["uav_takeoff"]["x"], a["uav_takeoff"]["y"]))
    assert len(a["corridor_polygon"]) == 4
    assert (out / "anchors.json").exists()


def test_terrain_height_bilinear_inside_grid():
    hf = {"h": np.array([[0.0, 1.0], [2.0, 3.0]]), "x0": 0.0, "y0": 0.0, "res": 1.0}
    assert terrain_height(hf, 0.5, 0.5) == pytest.approx(1.5)
    assert terrain_height(hf, 1.0, 0.0) == pytest.approx(2.0)   # rows = x, cols = y
    assert terrain_height(hf, 5.0, 5.0) == pytest.approx(3.0)   # clamped to edge


def test_interrupted_model_copy_is_redone(models, tmp_path):
    out = tmp_path / "f"
    partial = out / "models" / "Birch_obj"
    partial.mkdir(parents=True)            # a copy that was killed before any file landed
    rep = build_forest(models, out, PARAMS, seed=3)
    assert (partial / "Birch.usd").is_file()
    assert set(rep["unresolved"]) <= ALLOWED_UNRESOLVED
