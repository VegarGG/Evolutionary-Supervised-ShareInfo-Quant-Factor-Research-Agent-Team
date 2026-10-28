"""Small data-only upload/import fixtures; no model, sandbox or source execution."""

import hashlib
import io
import json
import os
import secrets
import sqlite3
import stat
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from qfr_core.access import BearerAuthority, ServicePrincipal
from qfr_core.contracts.access import ServiceAuthentication
from qfr_core.contracts.transfers import (
    IntakeTransportPolicy,
    MountedImportRequest,
    UploadDeclaration,
)
from qfr_eval.ingest.intake_app import create_app
from qfr_eval.ingest.quarantine import Quarantine, TransferConflict, TransferNotFound

ROOT = Path(__file__).resolve().parents[2]


def fixture(tmp_path, **changes):
    value = json.loads((ROOT / "configs/research/intake_transport_v1.json").read_bytes())
    value.update(
        chunk_bytes=256,
        max_upload_bytes=65536,
        max_expanded_bytes=4096,
        max_member_bytes=4096,
        max_archive_entries=8,
    )
    value.update(changes)
    root = tmp_path / "import"
    root.mkdir()
    store = Quarantine(
        tmp_path / "private", IntakeTransportPolicy.model_validate(value), {"originals": root}
    )
    program = uuid4()
    principal = ServicePrincipal(
        "synthetic-intake", "intake", frozenset({"research_lead"}), frozenset({str(program)})
    )
    return store, program, principal, root


def declaration(raw, **changes):
    value = dict(
        operation_key="source",
        asset_id="original",
        sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),
        media_type="text/plain",
        provenance="Synthetic original",
        intended_use="documentation",
        licence="Synthetic",
        source_is_untrusted_data=True,
    )
    value.update(changes)
    return UploadDeclaration.model_validate(value)


def upload(store, principal, program, raw, **changes):
    value = declaration(raw, **changes)
    state = store.create(principal, program, value, uuid4())
    for offset in range(0, len(raw), store.policy.chunk_bytes):
        data = raw[offset : offset + store.policy.chunk_bytes]
        store.chunk(
            principal,
            program,
            state.upload_id,
            offset,
            data,
            hashlib.sha256(data).hexdigest(),
            uuid4(),
        )
    return store.finalize(principal, program, state.upload_id, value.sha256, uuid4())


def zip_bytes(entries):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in entries:
            archive.writestr(name, raw)
    return stream.getvalue()


def test_chunks_retry_disconnect_restart_and_metadata_only(tmp_path):
    store, program, caller, _ = fixture(tmp_path)
    raw = "原始中文数据保持不变\n".encode() * 30
    value = declaration(raw)
    with ThreadPoolExecutor(4) as pool:
        states = list(pool.map(lambda _: store.create(caller, program, value, uuid4()), range(4)))
    assert all(s.upload_id == states[0].upload_id for s in states)
    identity = states[0].upload_id
    with pytest.raises(TransferConflict, match="incomplete"):
        store.finalize(caller, program, identity, value.sha256, uuid4())
    first = raw[:256]
    store.chunk(caller, program, identity, 0, first, hashlib.sha256(first).hexdigest(), uuid4())
    recreated = Quarantine(store.root, store.policy, store.mounts)
    assert recreated.status(caller, program, identity).bytes_received == 256
    result = upload(recreated, caller, program, raw)
    assert (
        result.state == "validated"
        and result.validation == "transport_only"
        and not result.execution_authorized
    )
    assert result.source.sha256 == value.sha256 and result.source.source_is_untrusted_data
    assert recreated.verify(caller, program, result.source) == result.source
    assert (store.root / f"{identity}.source").read_bytes() == raw
    assert recreated.finalize(caller, program, identity, value.sha256, uuid4()) == result
    with store.connection() as conn:
        assert conn.execute("SELECT count(*) FROM uploads").fetchone()[0] == 1
        assert (
            conn.execute("SELECT count(*) FROM events WHERE action='source_validated'").fetchone()[
                0
            ]
            == 1
        )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("DELETE FROM events")
    other = ServicePrincipal("other", "intake", caller.roles, frozenset({str(uuid4())}))
    with pytest.raises(TransferNotFound):
        recreated.status(other, program, identity)


def test_checksum_size_key_collision_and_reservation_fail_closed(tmp_path):
    store, program, caller, _ = fixture(tmp_path, max_uploads_per_program=1)
    value = declaration(b"abc")
    state = store.create(caller, program, value, uuid4())
    with pytest.raises(TransferConflict):
        store.create(caller, program, declaration(b"xyz"), uuid4())
    with pytest.raises(TransferConflict, match="reservation"):
        store.create(caller, program, declaration(b"abc", operation_key="new"), uuid4())
    with pytest.raises(ValueError, match="checksum"):
        store.chunk(caller, program, state.upload_id, 0, b"abc", "0" * 64, uuid4())
    with pytest.raises(ValueError, match="range"):
        store.chunk(caller, program, state.upload_id, 1, b"abc", value.sha256, uuid4())
    store.chunk(
        caller, program, state.upload_id, 0, b"xyz", hashlib.sha256(b"xyz").hexdigest(), uuid4()
    )
    rejected = store.finalize(caller, program, state.upload_id, value.sha256, uuid4())
    assert rejected.state == "rejected" and rejected.source is None
    assert not (store.root / f"{state.upload_id}.source").exists()


@pytest.mark.parametrize(
    "issue",
    [
        "parent",
        "absolute",
        "backslash",
        "symlink",
        "bomb",
        "entries",
        "malformed",
        "json_duplicates",
    ],
)
def test_unsafe_archives_and_json_remain_quarantined(tmp_path, issue):
    store, program, caller, _ = fixture(tmp_path)
    media = "application/zip"
    if issue == "malformed":
        raw = b"not a zip"
    elif issue == "json_duplicates":
        raw, media = b'{"a":1,"a":2}', "application/json"
    elif issue == "symlink":
        info = zipfile.ZipInfo("link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        raw = zip_bytes([(info, b"../../escape")])
    else:
        entries = {
            "parent": [("../outside", b"x")],
            "absolute": [("/outside", b"x")],
            "backslash": [("a\\b", b"x")],
            "bomb": [("big", b"x" * 4097)],
            "entries": [(str(n), b"x") for n in range(9)],
        }[issue]
        raw = zip_bytes(entries)
    result = upload(store, caller, program, raw, media_type=media)
    assert result.state == "rejected" and result.source is None
    assert not list(store.root.glob("*.source"))


def test_import_is_confined_verified_and_never_executes(tmp_path):
    store, program, caller, root = fixture(tmp_path)
    raw = b'raise RuntimeError("must not execute")\n'
    (root / "source.py").write_bytes(raw)
    request = MountedImportRequest(
        declaration=declaration(raw, media_type="text/x-python", intended_use="code"),
        mount_id="originals",
        relative_path="source.py",
    )
    result = store.import_file(caller, program, request, uuid4())
    assert result.state == "validated" and not result.execution_authorized
    assert result.source.reference.transport == "mounted_import"
    (root / "source.py").write_bytes(b"changed after immutable import")
    assert store.verify(caller, program, result.source) == result.source
    outside = tmp_path / "outside"
    outside.write_bytes(raw)
    (root / "link").symlink_to(outside)
    (root / "parentlink").symlink_to(tmp_path, target_is_directory=True)
    os.mkfifo(root / "pipe")
    for name in ["link", "parentlink/outside", "pipe"]:
        dangerous = request.model_copy(update={"relative_path": name})
        with pytest.raises((OSError, ValueError)):
            store.import_file(caller, program, dangerous, uuid4())
    with pytest.raises(ValueError):
        MountedImportRequest(
            declaration=request.declaration, mount_id="originals", relative_path="../outside"
        )


def test_authenticated_upload_http_keeps_raw_bytes_out_of_reads(tmp_path):
    store, program, _, _ = fixture(tmp_path)
    token = secrets.token_urlsafe(32)
    authority = BearerAuthority(
        ServiceAuthentication(
            revision=1,
            audience="intake",
            minimum_token_bytes=32,
            maximum_token_bytes=256,
            bindings=[
                dict(
                    principal="synthetic-http",
                    token_ref="env:UPLOAD",
                    roles=["research_lead"],
                    programs=[str(program)],
                )
            ],
        ),
        {"UPLOAD": token},
    )
    raw = b"synthetic-private-file"
    value = declaration(raw)
    logs = []
    with TestClient(
        create_app(store, authority=authority, request_log=logs.append),
        headers={"Authorization": "Bearer " + token},
    ) as client:
        route = f"/v1/programs/{program}/uploads"
        created = client.post(route, json=value.model_dump(mode="json"))
        assert created.status_code == 200, created.text
        identity = created.json()["upload_id"]
        chunk = client.post(
            route + f"/{identity}/chunks",
            content=raw,
            headers={
                "Content-Type": "application/octet-stream",
                "X-Chunk-Offset": "0",
                "X-Chunk-SHA256": value.sha256,
            },
        )
        assert chunk.status_code == 200, chunk.text
        done = client.post(route + f"/{identity}/finalize", json={"sha256": value.sha256})
        assert done.status_code == 200 and done.json()["state"] == "validated", done.text
        assert raw.decode() not in done.text
        source = done.json()["source"]
        verified = client.post(f"/v1/programs/{program}/assets/verify", json=source)
        assert verified.status_code == 200 and verified.json() == source
        assert client.get(route + f"/{identity}/download").status_code == 404
        paths = client.get("/openapi.json").json()["paths"]
        assert not any(
            word in path for path in paths for word in ["evaluate", "build", "execute", "download"]
        )
    assert token not in json.dumps(logs) and raw.decode() not in json.dumps(logs)
