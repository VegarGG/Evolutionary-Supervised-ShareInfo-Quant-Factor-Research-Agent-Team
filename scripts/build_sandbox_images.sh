#!/usr/bin/env bash
# Build evidence only. This script never installs/registers a runtime or publishes images.
set -euo pipefail
mkdir -p build/digests
architectures="${1:-$(python3 -c 'import json; print(" ".join(p.split("/")[1] for p in json.load(open("configs/build-matrix.json"))["platforms"]))')}"
source_revision="$(git rev-parse HEAD)"
source_state=clean
if [[ -n "$(git status --porcelain)" ]]; then source_state=dirty; fi
for arch in $architectures; do
  case "$arch" in amd64|arm64) ;; *) exit 2;; esac
  docker buildx build --platform "linux/$arch" \
    --label "org.opencontainers.image.revision=$source_revision" \
    --provenance=false -f infra/docker/Dockerfile.sandbox \
    --output "type=oci,dest=build/qfr_sandbox-${arch}.tar" \
    --metadata-file "build/digests/qfr_sandbox-${arch}.json" .
  python3 -m scripts.record_image_digest "build/qfr_sandbox-${arch}.tar" \
    "build/digests/qfr_sandbox-${arch}.json" qfr_sandbox "$arch" \
    --source-revision "$source_revision" --source-state "$source_state"
done
printf '%s\n' 'Core-only image builds are not sandbox readiness or native runtime acceptance.'
