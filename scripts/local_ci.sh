#!/usr/bin/env bash
# Trusted test harness only. Application images never receive this secret mount.
set -euo pipefail
mkdir -p build/local-ci
read_setting() {
  python3 -c 'import json, sys; print(json.load(open("configs/local-ci.json"))[sys.argv[1]])' "$1"
}
just up 2>&1 | tee build/local-ci/compose-up.txt
uv run --locked --all-packages python scripts/verify_postgres_startup.py \
  2>&1 | tee build/local-ci/postgres-startup-regressions.txt
docker buildx build --load -f infra/docker/Dockerfile.ci \
  --tag "$(read_setting image)" --metadata-file build/local-ci/test-image.json . \
  2>&1 | tee build/local-ci/test-image-build.txt
docker run --rm --name "$(read_setting container_name)" \
  --network "$(read_setting database_network)" \
  --mount "type=bind,src=$PWD/.secrets,dst=/run/qfr-test-secrets,readonly" \
  --mount "type=bind,src=$PWD/build/local-ci,dst=/evidence" \
  --env "QFR_TEST_POSTGRES_DSN=$(read_setting database_dsn)" \
  --env QFR_TEST_SECRET_DIR=/run/qfr-test-secrets \
  "$(read_setting image)"
bash scripts/build_images.sh 2>&1 | tee build/local-ci/image-builds.txt
printf '%s\n' 'Local Linux checks and both-platform builds passed. See build/local-ci and build/digests.'
printf '%s\n' 'Build success is not native runtime or sandbox acceptance. Licensed input checks run separately on the host.'
