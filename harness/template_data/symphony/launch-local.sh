#!/usr/bin/env sh
set -eu

python -m harness.cli run --workflow "${1:-WORKFLOW.md}"
