"""Record the actual single-platform manifest digest from a Buildx OCI archive."""

import argparse
import hashlib
import json
import tarfile
from pathlib import Path


def record(
    archive: Path,
    metadata: Path,
    package: str,
    architecture: str,
    source_revision: str,
    source_state: str,
):
    meta = json.loads(metadata.read_text())
    if not meta.get("containerimage.digest", "").startswith("sha256:"):
        raise ValueError("Buildx did not record an image digest")
    with tarfile.open(archive) as tar:

        def read(name):
            stream = tar.extractfile(name)
            if stream is None:
                raise ValueError(f"Missing OCI member: {name}")
            return stream.read()

        node = json.loads(read("index.json"))
        digest = None
        while "manifests" in node:
            candidates = [
                m
                for m in node["manifests"]
                if m.get("platform", {}).get("architecture", architecture) == architecture
            ]
            if len(candidates) != 1:
                raise ValueError("Expected exactly one platform image manifest")
            digest = candidates[0]["digest"]
            data = read("blobs/sha256/" + digest.removeprefix("sha256:"))
            if "sha256:" + hashlib.sha256(data).hexdigest() != digest:
                raise ValueError("OCI manifest digest mismatch")
            node = json.loads(data)
        config_digest = node["config"]["digest"]
        config_data = read("blobs/sha256/" + config_digest.removeprefix("sha256:"))
        if "sha256:" + hashlib.sha256(config_data).hexdigest() != config_digest:
            raise ValueError("OCI config digest mismatch")
        config = json.loads(config_data)
        if config["architecture"] != architecture or config["os"] != "linux":
            raise ValueError("Image platform differs from requested build")
        if (
            config.get("config", {}).get("Labels", {}).get("org.opencontainers.image.revision")
            != source_revision
        ):
            raise ValueError("Image source revision differs from build evidence")
    result = {
        "package": package,
        "platform": f"linux/{architecture}",
        "manifest_digest": digest,
        "buildx_digest": meta["containerimage.digest"],
        "source_revision": source_revision,
        "source_state": source_state,
        "acceptance": "Build success is not native runtime or sandbox acceptance.",
    }
    output = metadata.with_suffix(".digest.json")
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"{package} linux/{architecture}: {digest}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("metadata", type=Path)
    parser.add_argument("package")
    parser.add_argument("architecture", choices=["amd64", "arm64"])
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--source-state", choices=["clean", "dirty"], required=True)
    args = parser.parse_args()
    record(
        args.archive,
        args.metadata,
        args.package,
        args.architecture,
        args.source_revision,
        args.source_state,
    )
