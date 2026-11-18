Changelog
---------

0.1.0
~~~~~

Added
^^^^^

* Torch cluster workflow: ``install.sh``/``install.slurm`` (image pull and builds) and
  ``run.sh``/``run.slurm`` (per-job snapshot, manifest, supervised gate, results).
* Apptainer images for Isaac Sim 5.1.0 + Pegasus v5.1.0 and for ROS 2 Humble.
* Seeded headless forest exporter (``wildfire_swarm.forest.build_forest``).
* Verification gates G1 (container startup), G2 (GPU), G3 (forest and robot assets, video).
