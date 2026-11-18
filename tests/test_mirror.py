"""HTTP asset mirror tests: a local http.server stands in for the Isaac Sim asset root."""
import functools
import http.server
import threading
from pathlib import Path

import pytest
from pxr import Sdf, Usd, UsdGeom, UsdShade

from wildfire_swarm.assets.mirror import mirror_usd


def _layer(path: Path, build):
    path.parent.mkdir(parents=True, exist_ok=True)
    stage = Usd.Stage.CreateNew(str(path))
    build(stage)
    stage.GetRootLayer().Save()


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    root = tmp_path_factory.mktemp("remote")
    lib = root / "Assets" / "Isaac" / "5.1"
    (lib / "Isaac" / "Materials" / "tex").mkdir(parents=True)
    (lib / "Isaac" / "Materials" / "tex" / "metal.png").write_bytes(b"png-bytes")
    (lib / "Isaac" / "Materials" / "custom.mdl").write_text("mdl 1.6;\n")

    def robot(stage):
        UsdGeom.Xform.Define(stage, "/Robot")
        stage.SetDefaultPrim(stage.GetPrimAtPath("/Robot"))
        stage.GetRootLayer().subLayerPaths.append("./robot_physics.usda")
        stage.GetPrimAtPath("/Robot").GetReferences().AddReference("../../../Props/wheel.usda")
        sh = UsdShade.Shader.Define(stage, "/Robot/Looks/M/Shader")
        sh.GetPrim().CreateAttribute("info:mdl:sourceAsset", Sdf.ValueTypeNames.Asset).Set("../../../Materials/custom.mdl")
        sh.GetPrim().CreateAttribute("inputs:tex", Sdf.ValueTypeNames.Asset).Set("../../../Materials/tex/metal.png")
        sh2 = UsdShade.Shader.Define(stage, "/Robot/Looks/M2/Shader")
        sh2.GetPrim().CreateAttribute("info:mdl:sourceAsset", Sdf.ValueTypeNames.Asset).Set("OmniPBR.mdl")

    _layer(lib / "Isaac" / "Robots" / "NVIDIA" / "Bot" / "bot.usd", robot)
    def physics(stage):
        UsdGeom.Xform.Define(stage, "/Robot/Physics")
        sh = UsdShade.Shader.Define(stage, "/Robot/Physics/M/Shader")  # same folder, same core MDL
        sh.GetPrim().CreateAttribute("info:mdl:sourceAsset", Sdf.ValueTypeNames.Asset).Set("OmniPBR.mdl")

    _layer(lib / "Isaac" / "Robots" / "NVIDIA" / "Bot" / "robot_physics.usda", physics)
    url_holder = {}

    def props(stage):
        UsdGeom.Xform.Define(stage, "/Wheel")
        # absolute URL under the same root, and one outside it
        stage.GetPrimAtPath("/Wheel").GetReferences().AddReference(url_holder["root"] + "/Isaac/Props/hub.usda")
        stage.GetPrimAtPath("/Wheel").GetPayloads().AddPayload("https://elsewhere.example.com/x.usd")

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    url_holder["root"] = f"http://127.0.0.1:{httpd.server_address[1]}/Assets/Isaac/5.1"
    _layer(lib / "Isaac" / "Props" / "wheel.usda", props)
    def hub(stage):
        UsdGeom.Xform.Define(stage, "/Hub")
        sh = UsdShade.Shader.Define(stage, "/Hub/Looks/M/Shader")   # second layer using a core MDL
        sh.GetPrim().CreateAttribute("info:mdl:sourceAsset", Sdf.ValueTypeNames.Asset).Set("OmniPBR.mdl")

    _layer(lib / "Isaac" / "Props" / "hub.usda", hub)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield url_holder["root"]
    httpd.shutdown()


@pytest.fixture(scope="module")
def mirrored(server, tmp_path_factory):
    dest = tmp_path_factory.mktemp("local")
    return dest, mirror_usd(server, "/Isaac/Robots/NVIDIA/Bot/bot.usd", dest)


def test_closure_downloaded_with_same_layout(mirrored):
    dest, rep = mirrored
    for rel in ["Isaac/Robots/NVIDIA/Bot/bot.usd", "Isaac/Robots/NVIDIA/Bot/robot_physics.usda",
                "Isaac/Props/wheel.usda", "Isaac/Props/hub.usda",
                "Isaac/Materials/custom.mdl", "Isaac/Materials/tex/metal.png"]:
        assert (dest / rel).is_file(), rel
    assert rep["downloaded"] == 6


def test_search_path_and_outside_refs_reported_not_fetched(mirrored):
    _, rep = mirrored
    assert rep["search_path_assets"] == ["OmniPBR.mdl"]
    assert rep["outside_root"] == ["https://elsewhere.example.com/x.usd"]
    assert rep["missing"] == []


def test_absolute_urls_under_root_rewritten_to_relative(mirrored):
    dest, rep = mirrored
    layer = Sdf.Layer.FindOrOpen(str(dest / "Isaac/Props/wheel.usda"))
    refs = [r.assetPath for r in layer.GetPrimAtPath("/Wheel").referenceList.GetAddedOrExplicitItems()]
    assert refs == ["./hub.usda"]
    assert rep["rewritten"] >= 1


def test_mirrored_stage_composes_offline(mirrored):
    dest, _ = mirrored
    stage = Usd.Stage.Open(str(dest / "Isaac/Robots/NVIDIA/Bot/bot.usd"))
    assert stage.GetPrimAtPath("/Robot/Physics")
    remote = [l.identifier for l in stage.GetUsedLayers() if "://" in l.identifier]
    assert remote == []


def test_missing_root_raises(server, tmp_path):
    with pytest.raises(FileNotFoundError):
        mirror_usd(server, "/Isaac/Robots/nope.usd", tmp_path)


def test_transient_network_error_is_retried(server, tmp_path, monkeypatch):
    import urllib.request
    from wildfire_swarm.assets import mirror as m
    real = urllib.request.urlopen
    calls = {"n": 0}

    def flaky(url, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.URLError("temporary failure in name resolution")
        return real(url, timeout=timeout)

    import urllib.error
    monkeypatch.setattr(m.urllib.request, "urlopen", flaky)
    monkeypatch.setattr(m, "RETRY_SLEEP_S", 0.0)
    rep = mirror_usd(server, "/Isaac/Robots/NVIDIA/Bot/bot.usd", tmp_path)
    assert rep["downloaded"] == 6 and calls["n"] > 1


def test_search_path_names_are_looked_up_once(server, tmp_path, monkeypatch):
    from wildfire_swarm.assets import mirror as m
    seen_urls = []
    real = m._fetch

    def spy(url, dst, timeout):
        seen_urls.append(url)
        return real(url, dst, timeout)

    monkeypatch.setattr(m, "_fetch", spy)
    mirror_usd(server, "/Isaac/Robots/NVIDIA/Bot/bot.usd", tmp_path)
    assert len(seen_urls) == len(set(seen_urls))
