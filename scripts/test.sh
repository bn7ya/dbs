#!/bin/sh
set -e
cd "$(dirname "$0")/.."
python -m pytest "$@"
python -m pytest tests/manager --ds=tests.manager.settings "$@"
python -m pytest tests/isolation --ds=tests.isolation.settings "$@"
