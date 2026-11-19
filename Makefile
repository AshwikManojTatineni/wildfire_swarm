# Local checks: unit tests, shell syntax/lint, Python compilation, config sanity.
PY ?= python
SHELL_FILES := $(wildcard *.sh *.slurm scripts/cluster/*.sh scripts/gates/*.sh tests/*.sh)

.PHONY: check test shell-check py-check config-check

check: config-check shell-check py-check test

test:
	PXR_USDC_EMIT_DEPRECATION_WARNINGS=0 $(PY) -m pytest -q -p no:dash
	bash tests/test_supervise.sh

shell-check:
	@for f in $(SHELL_FILES); do bash -n "$$f" || exit 1; done; echo "bash -n OK"
	@if command -v shellcheck >/dev/null; then shellcheck -S error -s bash $(SHELL_FILES) && echo "shellcheck OK"; else echo "shellcheck not installed (skipped)"; fi

py-check:
	$(PY) -m py_compile scripts/cluster/*.py scripts/gates/*.py source/narrow_corridor_robot/narrow_corridor_robot/*/*.py && echo "py_compile OK"

config-check:
	$(PY) -c "import yaml; d=yaml.safe_load(open('config/runtime.yaml')); r=d['rates']; assert r['physics_hz']==240 and r['render_hz']==60 and r['imu_report_hz']==60, r; assert r['physics_hz']//r['imu_report_hz']==4; assert d['pegasus']['commit']=='644da37e9d5268e5f9a34e78bdcfd57a8bab82b4'; yaml.safe_load(open('config/mission.yaml')); print('config OK')"
	$(PY) -c "import xml.dom.minidom as m; m.parse('containers/fastdds_udp.xml'); print('fastdds xml OK')"
	bash -n config/torch.env.example && echo "torch.env.example OK"
