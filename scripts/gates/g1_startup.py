"""G1 payload, run with /isaac-sim/python.sh inside isaac_pegasus.sif.

Starts Kit headless, then imports Pegasus (Kit-dependent modules must come after
SimulationApp) and records which World namespaces resolve.
"""
import json, os, sys, traceback

from isaacsim import SimulationApp

app = SimulationApp({"headless": True})
out = {"isaac_python": sys.version.split()[0], "pegasus_import": False, "iris_in_robots": False,
       "errors": []}


def probe(label, fn):
    try:
        out[label] = fn()
    except Exception as exc:  # recorded, not fatal
        out[label] = False
        out["errors"].append(f"{label}: {exc!r}")
        traceback.print_exc()


from isaacsim.core.utils.extensions import enable_extension  # noqa: E402

# Pegasus vehicles import omni.isaac.dynamic_control (deprecated in 5.x); enable explicitly.
for ext in ("omni.isaac.dynamic_control", "isaacsim.ros2.bridge"):
    probe(f"ext_{ext}", lambda e=ext: bool(enable_extension(e) is not False))
app.update()

probe("isaacsim_core_api_world", lambda: bool(__import__("isaacsim.core.api.world", fromlist=["World"]).World))
probe("omni_isaac_core_world", lambda: bool(__import__("omni.isaac.core.world", fromlist=["World"]).World))


def _pegasus():
    import pegasus.simulator  # noqa: F401
    from pegasus.simulator.params import ROBOTS, WORLD_SETTINGS
    out["iris_in_robots"] = "Iris" in ROBOTS and os.path.isfile(ROBOTS["Iris"])
    out["iris_usd"] = ROBOTS.get("Iris")
    out["pegasus_default_physics_dt"] = WORLD_SETTINGS["px4"]["physics_dt"]
    from pegasus.simulator.logic.vehicles.multirotor import Multirotor  # noqa: F401
    from pegasus.simulator.logic.interface.pegasus_interface import PegasusInterface  # noqa: F401
    return True


probe("pegasus_import", _pegasus)
out["pegasus_commit"] = open("/opt/pegasus_commit").read().strip()
out["ros_env"] = {k: os.environ.get(k) for k in ("ROS_DISTRO", "RMW_IMPLEMENTATION", "ROS_DOMAIN_ID",
                                                   "LD_LIBRARY_PATH", "FASTRTPS_DEFAULT_PROFILES_FILE")}
os.makedirs("/workspace/run/g1", exist_ok=True)
json.dump(out, open("/workspace/run/g1/summary.json", "w"), indent=2)
print(json.dumps(out, indent=2))
app.close()
