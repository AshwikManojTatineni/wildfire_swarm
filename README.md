# Wildfire Swarm: Isaac Sim 5.1

One thermal Pegasus Iris UAV and four Nova Carter AMRs respond to wildfire hotspots in a procedurally
generated forest. The stack is Isaac Sim 5.1.0, Pegasus Simulator v5.1.0 and an external ROS 2 Humble
environment. Everything runs in Apptainer on NYU Torch L40S nodes.

The cluster workflow (separate setup and runtime jobs, immutable images, staged source, persistent
caches, per-job results) follows the ROB6323 Go2 project.

## Repository structure

```
wildfire_swarm/
├── install.sh / install.slurm      # CPU setup job: pull Isaac Sim 5.1.0, build images, prepare assets
├── run.sh / run.slurm              # L40S runtime job: snapshot source, manifest, run one gate, copy results
├── config/
│   ├── runtime.yaml                # image/Pegasus pins, rates, DDS, Slurm sizes
│   ├── mission.yaml                # forest, corridor, spawns, robots, video
│   └── torch.env.example           # Slurm account and paths (copy to torch.env)
├── containers/
│   ├── isaac_pegasus.def           # Isaac Sim 5.1.0 + Pegasus v5.1.0
│   ├── humble_ws.def               # ROS 2 Humble + Nav2, robot_localization, rtabmap_odom
│   └── fastdds_udp.xml             # UDPv4-only Fast DDS profile shared by both
├── scripts/
│   ├── cluster/                    # env, Apptainer wrappers, supervisor, manifest, asset preparation
│   └── gates/                      # g1_startup, g2_gpu, g3_scene
├── source/wildfire_swarm/          # python package (forest exporter, asset mirror; later sensors, fire, mission)
├── tests/                          # local unit tests
└── tutorial/tutorial.md            # step-by-step cluster walkthrough
```

## Quick start on Torch

Clone into your home directory: code belongs in backed-up `$HOME`, and large data goes to `/scratch`.

```bash
cd $HOME && git clone <your-repo-url> wildfire && cd wildfire
cp config/torch.env.example config/torch.env    # set SLURM_ACCOUNT (see my_slurm_accounts)
./install.sh                                    # CPU setup job (~1-1.5 h): images, assets, unit tests
./run.sh g1_startup                             # L40S: containers start, Pegasus imports
./run.sh g2_gpu                                 # L40S: GPU + driver visible, NVIDIA compatibility check
./run.sh g3_scene                               # L40S: forest + robots, saves overview.mp4 and chase.mp4
```

Results land in `results/<jobid>_r0/`, and `results/latest` points to the newest one. To copy the videos to
your laptop:

```bash
scp -r torch:wildfire/results/latest/g3 ./wildfire_g3
```

The full walkthrough is in [tutorial/tutorial.md](tutorial/tutorial.md). It covers the pass rules, Open
OnDemand and VS Code downloads, and troubleshooting.

## Cluster resources

| Job | Request | Why |
| --- | --- | --- |
| `install.sh` | CPU only: 10 cores, 20 GB RAM, ≤ 4 h | builds and downloads need no GPU (same as the Go2 install job) |
| `g1_startup`, `g2_gpu` | 1× L40S, 10 cores, 20 GB RAM, ≤ 30 min | Go2 sizing; no scene is loaded |
| `g3_scene` | 1× L40S, 10 cores, 32 GB RAM, ≤ 1 h | rendered forest scene; 32 GB is NVIDIA's minimum host RAM for Isaac Sim 5.1 |

`--mem` is host RAM. GPU memory is not requested: each job gets one whole L40S (48 GB VRAM). The L40S is the
right Torch GPU because Isaac Sim needs RT cores, which A100, H100, H200 and B200 lack.

| Scene | Estimated VRAM |
| --- | --- |
| G3 scene | ~10 GB |
| Full four-AMR mission | ~16 GB |

These estimates assume forest models are USD-instanced, so each tree mesh is stored once. Every GPU job
logs utilization and peak VRAM to `gpu_summary.json`. Torch cancels jobs with low GPU utilization.

## Storage

| Path | Contents |
| --- | --- |
| `$HOME/wildfire` | this repository and copied results (`results/`; videos git-ignored) |
| `/scratch/$USER/wildfire_work/sif` | Apptainer images, digests and versions |
| `/scratch/$USER/wildfire_work/assets` | localized forest and Nova Carter assets, `asset_manifest.json` |
| `/scratch/$USER/wildfire_work/cache` | Kit, shader and compute caches |
| `/scratch/$USER/wildfire_work/runs/<job>_r<n>` | per-job source snapshot, manifest, full logs |

Scratch is purged after 60 days without access. `./install.sh` (or `./install.sh --assets-only`) rebuilds it
from the pinned sources. No conda or pip environments are created in `$HOME`: every Python dependency is
inside the container images.

## Local checks (workstation)

```bash
python3 -m pip install pyyaml pytest usd-core numpy
make check
```

The setup job also runs the unit tests on Torch, inside `humble_ws.sif`.

## Pinned versions

`nvcr.io/nvidia/isaac-sim:5.1.0`; Pegasus Simulator `v5.1.0` (`644da37e`); forest generator
[joevento/Nvidia-Isaac-Sim-Procedual-Forest-Generator](https://github.com/joevento/Nvidia-Isaac-Sim-Procedual-Forest-Generator)
(`9e5fcbe3`, MIT); `osrf/ros:humble-desktop`. See [config/runtime.yaml](config/runtime.yaml).
