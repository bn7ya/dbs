#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../manager-ui"
npm ci
npm run build:package
