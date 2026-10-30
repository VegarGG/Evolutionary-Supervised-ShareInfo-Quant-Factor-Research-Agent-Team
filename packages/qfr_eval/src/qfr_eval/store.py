"""The evaluation artifact store (PLAN Section 8.9): series files, fingerprints and each
evaluated version's W1 factor values, under QFR_EVAL_STORE_DIR (the eval_store volume).

Every file is written atomically and referenced by an evalstore:// URI plus its SHA-256;
reads verify the hash. Research has no mount of this volume.
"""

import hashlib
import io
import os
import uuid
from datetime import date
from pathlib import Path
from uuid import UUID

import numpy as np
import polars as pl
from qfr_core.metrics.fingerprint import Fingerprint

SCHEME = "evalstore://"


class StoreError(RuntimeError):
    pass


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, uri: str) -> Path:
        if not uri.startswith(SCHEME):
            raise StoreError(f"not an evaluation store URI: {uri}")
        relative = Path(uri[len(SCHEME) :])
        if relative.is_absolute() or ".." in relative.parts:
            raise StoreError("store URIs are relative paths inside the store")
        return self.root / relative

    def write(self, relative: str, data: bytes) -> tuple[str, str, int]:
        uri = SCHEME + relative
        path = self._path(uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        staging = path.with_name(f".{path.name}.{uuid.uuid4().hex}")
        staging.write_bytes(data)
        os.replace(staging, path)
        return uri, hashlib.sha256(data).hexdigest(), len(data)

    def read(self, uri: str, sha256: str) -> bytes:
        data = self._path(uri).read_bytes()
        if hashlib.sha256(data).hexdigest() != sha256:
            raise StoreError(f"{uri} does not match its recorded SHA-256")
        return data

    def scratch(self) -> Path:
        path = self.root / "scratch"
        path.mkdir(parents=True, exist_ok=True)
        return path

    # Series files (Parquet) ----------------------------------------------------------

    def write_series(self, run_id: UUID, kind: str, frame: pl.DataFrame) -> tuple[str, str, int]:
        buffer = io.BytesIO()
        frame.write_parquet(buffer, statistics=False)
        return self.write(f"series/{run_id}/{kind}.parquet", buffer.getvalue())

    def read_series(self, uri: str, sha256: str) -> pl.DataFrame:
        return pl.read_parquet(io.BytesIO(self.read(uri, sha256)))

    # Fingerprints --------------------------------------------------------------------

    def write_fingerprint(
        self, epoch_id: str, version_id: UUID, value: Fingerprint
    ) -> tuple[str, str, str]:
        buffer = io.BytesIO()
        np.savez(
            buffer,
            dates=np.array([d.isoformat() for d in value.dates]),
            instruments=np.array(value.instruments),
            ranks=value.ranks,
        )
        uri, sha, _ = self.write(f"fingerprints/{epoch_id}/{version_id}.npz", buffer.getvalue())
        return uri, sha, dates_sha256(value.dates)

    def read_fingerprint(self, uri: str, sha256: str) -> Fingerprint:
        with np.load(io.BytesIO(self.read(uri, sha256)), allow_pickle=False) as data:
            return Fingerprint(
                [date.fromisoformat(str(d)) for d in data["dates"]],
                [str(i) for i in data["instruments"]],
                np.asarray(data["ranks"], dtype=np.float64),
            )

    # W1 factor values, for the library correlation ---------------------------------

    def write_window_values(
        self, epoch_id: str, window: str, version_id: UUID, values: np.ndarray, columns: np.ndarray
    ) -> tuple[str, str]:
        buffer = io.BytesIO()
        np.savez_compressed(buffer, values=values[:, columns], columns=columns)
        uri, sha, _ = self.write(f"values/{epoch_id}/{window}/{version_id}.npz", buffer.getvalue())
        return uri, sha

    def read_window_values(self, uri: str, sha256: str, instruments: int) -> np.ndarray:
        with np.load(io.BytesIO(self.read(uri, sha256)), allow_pickle=False) as data:
            columns = np.asarray(data["columns"], dtype=np.int64)
            stored = np.asarray(data["values"], dtype=np.float64)
        out = np.full((stored.shape[0], instruments), np.nan)
        out[:, columns] = stored
        return out


def dates_sha256(dates: list[date]) -> str:
    return hashlib.sha256(",".join(d.isoformat() for d in dates).encode()).hexdigest()
