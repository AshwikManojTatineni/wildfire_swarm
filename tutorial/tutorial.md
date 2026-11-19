# Tutorial: running the Narrow Corridor High Speed Robot project on Torch

Like the Go2 project, there are two kinds of job:

- **Setup** (`./install.sh`): one CPU-only job that builds the containers and prepares the assets.
- **Run** (`./run.sh`): one job on **one** L40S GPU. It runs the gates one after another (G1 → G3) and
  stops at the first failure.

Every job writes its evidence to `~/narrow_corridor_robot/results/<jobid>_r0/` and exits non-zero if its check fails.
Run the steps in order.

## 0. Connect and clone (login node, light work only)

Connect with `ssh torch` (off campus, use the NYU VPN; see the
[Torch connection guide](https://services.rt.nyu.edu/docs/hpc/connecting_to_hpc/connecting_to_hpc/)).

Clone into your home directory. Torch backs up `$HOME`, but `/scratch` is not backed up and is purged after
60 days without access.

```bash
cd $HOME
git clone <your-repo-url> narrow_corridor_robot
cd narrow_corridor_robot
```

There is nothing to configure. Jobs use the project account `torch_pr_742` (set as `slurm.account` in
`config/runtime.yaml`). If `my_slurm_accounts` lists a longer name that starts with it, that exact name is
used instead. The scripts print the account when they submit (`Slurm account: ...`). To use a different
account, set `SLURM_ACCOUNT` in `config/torch.env`, which is created automatically on the first run.

The project needs an **Active** allocation in [projects.hpc.nyu.edu](https://projects.hpc.nyu.edu) first.
Only the PI can request one; ask for the **Torch** resource, which includes the L40S GPUs.

Any folder name works for the clone, because the scripts find the repo from their own location. The paths
below assume `~/narrow_corridor_robot`.

Large data never goes in `$HOME`. Images, caches, assets and raw runs go to `/scratch/$USER/ncr_work`.
Nothing is pip- or conda-installed into `$HOME`: all Python packages live inside the container images.

## 1. Setup job (CPU only, about 1–1.5 h)

Run these on the login node, in the same terminal:

```bash
./install.sh
```

It prints the job ID and the exact command to follow the job, for example:

```
Submitted setup job 4815162. Follow it (Ctrl+C stops watching, not the job):
  tail -F /scratch/<netid>/ncr_work/slurm_logs/install_4815162.out
```

Paste that `tail -F` line to watch the job live.

- While the job is queued (`squeue --me` shows `PD`), the log file doesn't exist yet. `tail -F` waits for it.
- Ctrl+C only stops the viewer; the job keeps running.
- You can log out and check the same file later with `less`.

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
./run.sh                    # g1_startup -> g3_scene, same GPU, stops at first failure
squeue --me                 # PD = queued, R = running
tail -F /scratch/$USER/ncr_work/slurm_logs/run_<jobid>.out   # run.sh prints this exact line
```

To rerun a single gate, use `./run.sh g3_scene`. While one of your project jobs (setup or run) is queued or
running, `install.sh` and `run.sh` won't submit another. The sections below give each gate's pass rule.

**How long it runs.** G3 simulates exactly 20 s (`video_seconds` in `config/mission.yaml`), writes the two
videos and exits. The job ends right then and frees the GPU. `--time` is only a safety cap (10 min for G1,
15 min for G3, 25 min total) so that a hung simulator never holds the GPU.

The very first run is the slowest, because Isaac Sim compiles its shaders once and caches them in
`/scratch/$USER/ncr_work/cache`. If that first job hits the cap (`sacct` shows `TIMEOUT`), run
`./run.sh` again: the cache is kept and later starts are much faster.

### G1: container startup

Pass: `results/<job>_r0/g1/summary.json` shows:
- `isaac_python` 3.11.x
- `pegasus_import: true`
- `iris_in_robots: true`

`g1/humble.txt` shows Python 3.10 and the Nav2, robot_localization and rtabmap_odom prefixes.

There is no separate GPU-check gate. `manifest.json` records the allocated GPU and driver for every job,
G3 can only render with a working GPU, and Torch itself warns about idle GPU allocations.

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
== video: /home/<netid>/narrow_corridor_robot/results/<jobid>_r0/g3/overview.mp4 (12M)
== video: /home/<netid>/narrow_corridor_robot/results/<jobid>_r0/g3/chase.mp4 (11M)
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
scp -r torch:narrow_corridor_robot/results/latest/g3 ./ncr_g3
```

or a single file:

```bash
scp torch:narrow_corridor_robot/results/<jobid>_r0/g3/overview.mp4 .
```

For large or many files, use the data transfer node `dtn.torch.hpc.nyu.edu` instead of the login node.

**Option B: Open OnDemand.** Log in to Torch Open OnDemand
([guide](https://services.rt.nyu.edu/docs/hpc/ood/ood_intro/)), open **Files → Home Directory →
narrow_corridor_robot/results/<jobid>_r0/g3/**, then select `overview.mp4` and click **Download**. The browser can
also play it directly.

**Option C: VS Code Remote-SSH.** Open `~/narrow_corridor_robot/results/latest/g3/` in the Explorer, then right-click
`overview.mp4` and choose **Download…**.

`results/` is git-ignored, so videos and run files never end up in the repository. Each run's video pair is about 20–40 MB in
`$HOME` (50 GB quota). Check your usage with `myquota`, and delete old `results/<jobid>_r0/` folders you no
longer need.

## Where to look when something fails

| What | Where |
| --- | --- |
| Slurm output | `/scratch/$USER/ncr_work/slurm_logs/run_<jobid>.out` (gates are marked `== gate ... start/exit`) |
| Child process logs | `results/<job>_r0/*.log.tail`; full logs in `ncr_work/runs/<job>_r0/logs/` |
| Exact code that ran | `ncr_work/runs/<job>_r0/src/` (snapshot of the committed `HEAD`) |
| Job state and exit reason | `sacct -j <jobid> --format=JobID,State,ExitCode,Elapsed,MaxRSS,ReqTRES` |

If a job shows `CANCELLED` and `gpu_summary.json` shows low `util_mean_pct`, Torch's low-GPU-utilization
policy cancelled it (L40S nodes: cancel below 50 %, warning below 70 %).
