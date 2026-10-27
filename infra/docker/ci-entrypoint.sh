#!/usr/bin/env bash
set -euo pipefail
just check 2>&1 | tee /evidence/linux-check.txt
PYTEST_ADDOPTS="${PYTEST_ADDOPTS:-} --require-postgres" just test \
  2>&1 | tee /evidence/linux-test.txt
