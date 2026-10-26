"""Explicit evaluator-owner CLI persistence, with database-enforced activation freeze."""

from pathlib import Path
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.types.json import Jsonb
from qfr_core.configuration import load_yaml

from qfr_eval.protocols.models import FrozenProtocol


def create_protocol(conn: Connection, path: Path, *, principal: str, request_id: UUID) -> str:
    protocol = load_yaml(path, FrozenProtocol)
    with conn.transaction():
        row = conn.execute(
            "INSERT INTO eval.protocols(id,payload,created_by,request_id,protocol_id,version,"
            "yaml,sha256,status) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'draft') "
            "ON CONFLICT(protocol_id,version) DO NOTHING RETURNING sha256",
            (
                uuid4(),
                Jsonb(protocol.model_dump(mode="json")),
                principal,
                request_id,
                protocol.protocol_id,
                protocol.version,
                path.read_text(),
                protocol.sha256,
            ),
        ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT sha256 FROM eval.protocols WHERE protocol_id=%s AND version=%s",
                (protocol.protocol_id, protocol.version),
            ).fetchone()
            if row is None or row[0] != protocol.sha256:
                raise ValueError("protocol version already exists with different content")
    return protocol.sha256


def activate_protocol(
    conn: Connection,
    protocol_id: str,
    version: str,
    *,
    expected_hash: str,
    principal: str,
    request_id: UUID,
) -> str:
    with conn.transaction():
        row = conn.execute(
            "SELECT payload,sha256,status FROM eval.protocols "
            "WHERE protocol_id=%s AND version=%s FOR UPDATE",
            (protocol_id, version),
        ).fetchone()
        if row is None:
            raise ValueError("unknown protocol revision")
        protocol = FrozenProtocol.model_validate(row[0])
        if row[1] != protocol.sha256 or expected_hash != protocol.sha256:
            raise ValueError("protocol hash mismatch")
        if row[2] == "active":
            return protocol.sha256
        if row[2] != "draft":
            raise ValueError("protocol cannot be activated")
        conn.execute(
            "UPDATE eval.protocols SET status='active',created_by=%s,request_id=%s "
            "WHERE protocol_id=%s AND version=%s",
            (principal, request_id, protocol_id, version),
        )
    return protocol.sha256


def get_active(conn: Connection, protocol_id: str, version: str) -> FrozenProtocol:
    row = conn.execute(
        "SELECT payload,sha256 FROM eval.protocols "
        "WHERE protocol_id=%s AND version=%s AND status='active'",
        (protocol_id, version),
    ).fetchone()
    if row is None:
        raise ValueError("protocol is not active")
    protocol = FrozenProtocol.model_validate(row[0])
    if protocol.sha256 != row[1]:
        raise ValueError("stored protocol hash mismatch")
    return protocol
