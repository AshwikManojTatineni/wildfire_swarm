# Wildfire Swarm: Isaac Sim 5.1

One thermal Pegasus Iris UAV and four Nova Carter AMRs respond to wildfire hotspots in a procedurally
generated forest. The stack is Isaac Sim 5.1.0, Pegasus Simulator v5.1.0 and an external ROS 2 Humble
environment. Everything runs in Apptainer on NYU Torch L40S nodes.

The cluster workflow (separate setup and runtime jobs, immutable images, staged source, persistent
caches, per-job results) follows the ROB6323 Go2 project.

## Repository structure

```
wildfire_swarm/
├── install.sh / install.slurm      # setup job: pull Isaac Sim 5.1.0, build images, fetch forest generator
├── run.sh / run.slurm              # runtime job: snapshot source, manifest, run one gate, copy results
├── config/
│   ├── runtime.yaml                # image/Pegasus pins, rates, DDS, Slurm sizes
│   ├── mission.yaml                # forest, corridor, spawns, robots, video
│   └── torch.env.example           # Slurm account and paths (copy to torch.env)
├── containers/
│   ├── isaac_pegasus.def           # Isaac Sim 5.1.0 + Pegasus v5.1.0
│   ├── humble_ws.def               # ROS 2 Humble + Nav2, robot_localization, rtabmap_odom
│   └── fastdds_udp.xml             # UDPv4-only Fast DDS profile shared by both
├── scripts/
│   ├── cluster/                    # env, Apptainer wrappers, process supervisor, manifest
│   └── gates/                      # g1_startup, g2_gpu, g3_prep, g3_scene
├── source/wildfire_swarm/          # python package (forest exporter, later: sensors, fire, mission)
├── tests/                          # local unit tests
└── tutorial/tutorial.md            # step-by-step cluster walkthrough
```

## Quick start on Torch

Clone this repository into `/scratch/$USER/wildfire`, then:

```bash
cd /scratch/$USER/wildfire
cp config/torch.env.example config/torch.env    # set SLURM_ACCOUNT (see my_slurm_accounts)
./install.sh                                    # ~1 h CPU job; wait for it to finish
./run.sh g1_startup
./run.sh g2_gpu
./run.sh g3_prep
./run.sh g3_scene                               # forest + robots, saves overview.mp4 and chase.mp4
```

Results land in `results/<jobid>_r0/`. The full walkthrough, with the pass rules for each step, is in
[tutorial/tutorial.md](tutorial/tutorial.md).

## Storage

| Path | Contents |
| --- | --- |
| `/scratch/$USER/wildfire` | this repository; jobs snapshot its committed `HEAD` |
| `/scratch/$USER/wildfire_work/sif` | Apptainer images, digests and versions |
| `/scratch/$USER/wildfire_work/assets` | localized forest and Nova Carter assets, `asset_manifest.json` |
| `/scratch/$USER/wildfire_work/cache` | Kit, shader and compute caches |
| `/scratch/$USER/wildfire_work/runs/<job>_r<n>` | per-job source snapshot, manifest, logs, evidence |

Scratch is purged after 60 days without access. `./install.sh` and `./run.sh g3_prep` rebuild everything in
`wildfire_work` from the pinned sources.

## Local checks

```bash
python3 -m pip install --user pyyaml pytest usd-core numpy
make check
```

## Pinned versions

`nvcr.io/nvidia/isaac-sim:5.1.0`; Pegasus Simulator `v5.1.0` (`644da37e`); forest generator
[joevento/Nvidia-Isaac-Sim-Procedual-Forest-Generator](https://github.com/joevento/Nvidia-Isaac-Sim-Procedual-Forest-Generator)
(`9e5fcbe3`, MIT); `osrf/ros:humble-desktop`. See [config/runtime.yaml](config/runtime.yaml).
