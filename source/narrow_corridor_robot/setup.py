"""Installation script for the 'narrow_corridor_robot' python package.

Inside the cluster jobs the package is used from the read-only source snapshot via
PYTHONPATH (scripts/cluster/isaac_exec.sh). For local development and tests:

    pip install -e source/narrow_corridor_robot
"""
from setuptools import find_packages, setup

setup(
    name="narrow_corridor_robot",
    version="0.1.0",
    description="Forest wildfire response with a Pegasus Iris UAV and Nova Carter AMRs in Isaac Sim 5.1",
    packages=find_packages(),
    install_requires=["numpy", "pyyaml"],
    python_requires=">=3.10",
    license="BSD-3-Clause",
    classifiers=[
        "Natural Language :: English",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Isaac Sim :: 5.1.0",
    ],
    zip_safe=False,
)
