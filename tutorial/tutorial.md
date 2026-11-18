# Tutorial: running the wildfire swarm on Torch

Like the Go2 project, there are two kinds of job:

- **Setup** (`./install.sh`): one CPU-only job that builds the containers and prepares the assets.
- **Run** (`./run.sh`): one job on **one** L40S GPU. It runs the gates one after another (G1 → G2 → G3) and
  stops at the first failure.

Every job writes its evidence to `~/wildfire/results/<jobid>_r0/` and exits non-zero if its check fails.
Run the steps in order.

## 0. Connect and clone (login node, light work only)

Connect with `ssh torch` (off campus, use the NYU VPN; see the
[Torch connection guide](https://services.rt.nyu.edu/docs/hpc/connecting_to_hpc/connecting_to_hpc/)).

Clone into your home directory. Torch backs up `$HOME`, but `/scratch` is not backed up and is purged after
60 days without access.

```bash
cd $HOME
git clone <your-repo-url> wildfire
cd wildfire
cp config/torch.env.example config/torch.env
my_slurm_accounts                     # copy your torch_pr_... account into config/torch.env
```

Large data never goes in `$HOME`. Images, caches, assets and raw runs go to `/scratch/$USER/wildfire_work`.
Nothing is pip- or conda-installed into `$HOME`: all Python packages live inside the container images.

## 1. Setup job (CPU only, about 1–1.5 h)

```bash
./install.sh
squeue --me
tail -f /scratch/$USER/wildfire_work/slurm_logs/install_<jobid>.out
```

The setup job does the following, all on a CPU compute node:

1. Pulls `nvcr.io/nvidia/isaac-sim:5.1.0`.
2. Builds `isaac_pegasus.sif` (Isaac Sim + Pegasus v5.1.0) and `humble_ws.sif` (ROS 2 Humble + usd-core) with `--fakeroot`.
3. Clones the forest generator at its pinned commit.
4. Exports the seeded forest. About 600 MB, mostly textures.
5. Downloads the Nova Carter robot and everything it references from the Isaac Sim 5.1 asset library. About 820 files, 425 MB.
6. Runs the unit tests.

The summary is written to `results/install_<jobid>/summary.json`.

| Problem | Fix |
| --- | --- |
| Exit code 3 | `--fakeroot` is not available. Contact hpc@nyu.edu. |
| The pull is denied | Put an NGC API key in `NGC_API_KEY` in `config/torch.env`. |
| Scratch was purged, or `config/mission.yaml` changed | `./install.sh --assets-only` |

## 2. Run the gates (one job, one L40S)

```bash
./run.sh                    # g1_startup -> g2_gpu -> g3_scene, same GPU, stops at first failure
squeue --me
tail -f /scratch/$USER/wildfire_work/slurm_logs/run_<jobid>.out
```

To rerun a single gate, use `./run.sh g3_scene`. While one wildfire GPU job is queued or running, `run.sh`
won't submit another. The sections below give each gate's pass rule.

### G1: container startup

Pass: `results/<job>_r0/g1/summary.json` shows:
- `isaac_python` 3.11.x
- `pegasus_import: true`
- `iris_in_robots: true`

`g1/humble.txt` shows Python 3.10 and the Nav2, robot_localization and rtabmap_odom prefixes.

### G2: GPU visibility

Pass: `g2/summary.json` has `l40s: true`, `same_gpu_in_container: true` and `compat_passed: true`. The
driver is recorded next to the version Isaac Sim 5.1 was tested on (580.65.06).

### G3: forest and robots, with video

This step loads the forest, the Iris (parked on the takeoff patch) and one Nova Carter from local files
only. It runs at 240 Hz physics and 60 Hz rendering, drives the Carter 4 m along the corridor and records
two 20 s videos.

Pass, when every one of these is true in `g3/verdict.json`:

| Rule | Condition |
| --- | --- |
| `offline_ok` | no composed layer or asset path is remote |
| `terrain_collider_ok`, `trunk_collider_ok` | the raycasts hit the terrain and a tree trunk |
| `rates_ok` | mean physics step is 1/240 s, with 4 physics steps per render |
| `carter_drove_ok` | the Carter moves ≥ 2 m forward, drifts ≤ 0.5 m sideways and doesn't fall |
| `video_ok` | at least 90 % of the expected frames are in both videos |

## 3. Getting the simulation video and results

At the end of each run job, the Slurm log prints the video paths:

```
== video: /home/<netid>/wildfire/results/<jobid>_r0/g3/overview.mp4 (12M)
== video: /home/<netid>/wildfire/results/<jobid>_r0/g3/chase.mp4 (11M)
```

`results/latest` always points to the most recent run.

| File | Contents |
| --- | --- |
| `g3/overview.mp4` | wide shot of the corridor, Carter and Iris |
| `g3/chase.mp4` | camera following the Carter |
| `g3/still_*.png` | first and middle frames |
| `g3/verdict.json`, `g3/stage_report.json` | pass rules, measured values, timing, Carter joints and pose |
| `gpu_summary.json` | mean and peak GPU utilization and peak VRAM for the job |
| `manifest.json` | node, GPU, driver, image digests, git SHA, exact command |

**Option A: copy to your laptop with `scp`** (run on your laptop; uses the same `torch` SSH alias as login):

```bash
scp -r torch:wildfire/results/latest/g3 ./wildfire_g3
```

or a single file:

```bash
scp torch:wildfire/results/<jobid>_r0/g3/overview.mp4 .
```

For large or many files, use the data transfer node `dtn.torch.hpc.nyu.edu` instead of the login node.

**Option B: Open OnDemand.** Log in to Torch Open OnDemand
([guide](https://services.rt.nyu.edu/docs/hpc/ood/ood_intro/)), open **Files → Home Directory →
wildfire/results/<jobid>_r0/g3/**, then select `overview.mp4` and click **Download**. The browser can
also play it directly.

**Option C: VS Code Remote-SSH.** Open `~/wildfire/results/latest/g3/` in the Explorer, then right-click
`overview.mp4` and choose **Download…**.

Videos are git-ignored, so they never end up in the repository. Each run's video pair is about 20–40 MB in
`$HOME` (50 GB quota). Check your usage with `myquota`, and delete old `results/<jobid>_r0/` folders you no
longer need.

## Where to look when something fails

| What | Where |
| --- | --- |
| Slurm output | `/scratch/$USER/wildfire_work/slurm_logs/run_<jobid>.out` (gates are marked `== gate ... start/exit`) |
| Child process logs | `results/<job>_r0/*.log.tail`; full logs in `wildfire_work/runs/<job>_r0/logs/` |
| Exact code that ran | `wildfire_work/runs/<job>_r0/src/` (snapshot of the committed `HEAD`) |
| Job state and exit reason | `sacct -j <jobid> --format=JobID,State,ExitCode,Elapsed,MaxRSS,ReqTRES` |

If a job shows `CANCELLED` and `gpu_summary.json` shows low `util_mean_pct`, Torch's low-GPU-utilization
policy cancelled it (L40S nodes: cancel below 50 %, warning below 70 %).
