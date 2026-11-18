# Tutorial: running the wildfire swarm on Torch

Each step below is one Slurm job, submitted from a Torch login node. Each one writes its evidence to
`results/<jobid>_r0/` and exits non-zero if its check fails. Run the steps in order. A later step assumes
the earlier ones passed.

## 0. Connect and clone

Connect to Torch (`ssh torch`, NYU VPN off campus; see the
[Torch connection guide](https://services.rt.nyu.edu/docs/hpc/connecting_to_hpc/connecting_to_hpc/)), then:

```bash
cd /scratch/$USER
git clone <your-repo-url> wildfire
cd wildfire
cp config/torch.env.example config/torch.env
my_slurm_accounts                     # copy your torch_pr_... account into config/torch.env
```

Optional local checks on the login node (they are light):

```bash
python3 -m pip install --user pyyaml pytest usd-core numpy
make check
```

## 1. Install (CPU job, about 1 h)

```bash
./install.sh
squeue --me
tail -f /scratch/$USER/wildfire_work/slurm_logs/install_<jobid>.out
```

This job:

- pulls `nvcr.io/nvidia/isaac-sim:5.1.0`
- builds `isaac_pegasus.sif` (Pegasus v5.1.0 at its pinned commit) and `humble_ws.sif` with `--fakeroot`
- clones the forest generator at its pinned commit
- writes `wildfire_work/sif/digests.txt`

| Problem | Fix |
| --- | --- |
| Exit code 3 | `--fakeroot` is not available. Contact hpc@nyu.edu. |
| The pull is denied | Put an NGC API key in `NGC_API_KEY` in `config/torch.env`. |

## 2. G1: container startup

```bash
./run.sh g1_startup
```

Pass: `results/<job>_r0/g1/summary.json` shows `isaac_python` 3.11.x, `pegasus_import: true` and
`iris_in_robots: true`, and `g1/humble.txt` shows Python 3.10 and the Nav2, robot_localization and
rtabmap_odom prefixes.

## 3. G2: GPU visibility

```bash
./run.sh g2_gpu
```

Pass: `g2/summary.json` has `l40s: true`, `same_gpu_in_container: true` and `compat_passed: true`. The
driver version is recorded next to the version Pegasus was tested with (550.163.01).

## 4. G3 prep: localize assets (network needed)

```bash
./run.sh g3_prep
```

This exports the seeded forest to `wildfire_work/assets/forest/`. It also mirrors the Nova Carter USD,
with everything it references, from the Isaac Sim 5.1 asset library to `wildfire_work/assets/isaac/`.

Pass: `g3_prep/summary.json` has no errors, a `nova_carter_rel` path and no forest remote references.
Run it again only after a scratch purge or a change to `config/mission.yaml`.

## 5. G3: forest and robots, with video

```bash
./run.sh g3_scene
```

This step loads the forest, the Iris (parked on the takeoff patch) and one Nova Carter from local files
only. It runs at 240 Hz physics and 60 Hz rendering, drives the Carter along the corridor and records two
20 s videos.

| File | Contents |
| --- | --- |
| `g3/overview.mp4`, `g3/chase.mp4` | videos (git-ignored) |
| `g3/still_*.png` | stills |
| `g3/stage_report.json` | timing, Carter joints and pose, collider hits |
| `g3/verdict.json` | each pass rule with its measured value |

Pass, when every one of these is true:

| Rule | Condition |
| --- | --- |
| `offline_ok` | no composed layer or asset path is remote |
| `terrain_collider_ok`, `trunk_collider_ok` | the raycasts hit the terrain and a tree trunk |
| `rates_ok` | mean physics step is 1/240 s, with 4 physics steps per render |
| `carter_drove_ok` | the Carter moves ≥ 2 m forward, drifts ≤ 0.5 m sideways and doesn't fall |
| `video_ok` | at least 90% of the expected frames are in both videos |

## Where to look when something fails

| What | Where |
| --- | --- |
| Slurm output | `/scratch/$USER/wildfire_work/slurm_logs/<gate>_<jobid>.out` |
| Child process logs | `results/<job>_r0/*.log.tail`; full logs in `wildfire_work/runs/<job>_r0/logs/` |
| Exact code that ran | `wildfire_work/runs/<job>_r0/src/` (snapshot of the committed `HEAD`) |
| Hardware, image digests and command | `results/<job>_r0/manifest.json` |
