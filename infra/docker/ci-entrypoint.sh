#!/usr/bin/env bash
set -euo pipefail
just check 2>&1 | tee /evidence/linux-check.txt
just test 2>&1 | tee /evidence/linux-test.txt
