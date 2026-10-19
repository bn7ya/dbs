#!/bin/sh
set -e
cd "$(dirname "$0")/.."
python -m pytest "$@"
python -m pytest tests/manager --ds=tests.manager.settings "$@"
python -m pytest tests/isolation --ds=tests.isolation.settings "$@"
python -m pytest tests/scaling --ds=tests.scaling.settings "$@"
DBS_LOAD_BASELINE=5 DBS_LOAD_AFTER=3 python -m pytest tests/load --ds=tests.load.settings "$@"
DBS_SCALE_ROWS=20000 python -m pytest tests/scale --ds=tests.scale.settings "$@"
