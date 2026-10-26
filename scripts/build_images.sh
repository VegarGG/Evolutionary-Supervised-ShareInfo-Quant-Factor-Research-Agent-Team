#!/usr/bin/env bash
set -euo pipefail
mkdir -p build/digests
architectures="${1:-$(python3 -c 'import json; print(" ".join(p.split("/")[1] for p in json.load(open("configs/build-matrix.json"))["platforms"]))')}"
source_revision="$(git rev-parse HEAD)"
source_state=clean
if [[ -n "$(git status --porcelain)" ]]; then source_state=dirty; fi
for arch in $architectures; do
  case "$arch" in amd64|arm64) ;; *) exit 2;; esac
  for package in $(python3 -c 'import json; print(" ".join(json.load(open("configs/build-matrix.json"))["packages"]))'); do
    docker buildx build --platform "linux/$arch" --build-arg "QFR_PACKAGE=$package" \
      --label "org.opencontainers.image.revision=$source_revision" \
      --provenance=false -f infra/docker/Dockerfile \
      --output "type=oci,dest=build/${package}-${arch}.tar" \
      --metadata-file "build/digests/${package}-${arch}.json" .
    python3 -m scripts.record_image_digest "build/${package}-${arch}.tar" \
      "build/digests/${package}-${arch}.json" "$package" "$arch" \
      --source-revision "$source_revision" --source-state "$source_state"
  done
done
printf '%s\n' 'Build success is not native runtime or sandbox acceptance.'
