"""Read-only access to the trusted ingest catalog, never to a full snapshot root."""

import hashlib
import re
from pathlib import Path

from qfr_core.contracts.data import ResearchDatasetRegistration
from qfr_core.data_layer.snapshots import Snapshot, canonical_json


def registration_hash(value: ResearchDatasetRegistration) -> str:
    return hashlib.sha256(
        canonical_json(value.model_dump(mode="json", exclude={"registration_id"}))
    ).hexdigest()


def read_registration(root: Path, identity: str, program: str) -> ResearchDatasetRegistration:
    if not re.fullmatch(r"[0-9a-f]{64}", identity):
        raise ValueError("invalid research dataset registration ID")
    path = root / "catalog" / (identity + ".json")
    if (
        path.is_symlink()
        or path.parent.is_symlink()
        or not path.resolve().is_relative_to(root.resolve())
    ):
        raise ValueError("research catalog path escapes its read-only root")
    with path.open("rb") as stream:
        raw = stream.read(1048577)
    if len(raw) > 1048576:
        raise ValueError("research dataset registration exceeds size limit")
    value = ResearchDatasetRegistration.model_validate_json(raw)
    if (
        value.registration_id != identity
        or registration_hash(value) != identity
        or value.program_id != program
        or hashlib.sha256(
            canonical_json(value.research_manifest.model_dump(mode="json"))
        ).hexdigest()
        != value.research_manifest_sha256
    ):
        raise ValueError("research dataset registration hash or scope differs")
    return value


def registered_snapshot(root: Path, value: ResearchDatasetRegistration) -> Snapshot:
    """Verify actual authorized slice bytes before admission or export."""
    verified = read_registration(root, value.registration_id, value.program_id)
    if verified != value:
        raise ValueError("research registration differs from the trusted catalog")
    path = root / value.research_manifest.snapshot_id
    if path.is_symlink():
        raise ValueError("research snapshot cannot be a symlink")
    snapshot = Snapshot.load(path)
    if snapshot.manifest != value.research_manifest:
        raise ValueError("research snapshot differs from registration")
    return snapshot
