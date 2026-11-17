"""Read native DSH task events without relying on model-visible tool output."""

import hashlib
import io
import json
import re

import zstandard


def parse_task_log(raw, session_id):
    chunks, size = [], 0
    with zstandard.ZstdDecompressor().stream_reader(
        io.BytesIO(raw), read_across_frames=True
    ) as reader:
        while chunk := reader.read(64 * 1024):
            size += len(chunk)
            assert size <= 64 * 1024 * 1024, "Native audit log exceeds bounded read"
            chunks.append(chunk)
    decoded = b"".join(chunks)
    records = [json.loads(line) for line in decoded.splitlines() if line]
    assert records and records[0]["type"] == "session", "Missing native session header"
    assert records[0]["id"] == session_id and records[0]["version"] == 4, "Wrong native session"
    sequence = [r["seq"] for r in records[1:]]
    assert all(type(n) is int for n in sequence)
    assert all(b > a for a, b in zip(sequence, sequence[1:], strict=False)), (
        "Native event order changed"
    )
    tasks, events = {}, []
    for record in records[1:]:
        if record["type"] != "team/task":
            continue
        assert record["data"]["teamId"] == session_id, "Foreign native team"
        task = record["data"]["task"]
        assert type(task["revision"]) is int and task["revision"] > 0
        previous = tasks.get(task["id"])
        assert previous is None or task["revision"] > previous["revision"], "Stale task revision"
        tasks[task["id"]] = task
        events.append(record)
    return {
        "source": "native DSH append-only compressed session log",
        "session_id": session_id,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "record_count": len(records),
        "task_events": events,
        "latest_tasks": list(tasks.values()),
    }


def read_task_log(home, session_id):
    assert re.fullmatch(r"[A-Za-z0-9_-]+", session_id), "Invalid native session identifier"
    paths = list((home / "sessions").glob(f"*/{session_id}/session.v4.jsonl.zstd"))
    assert len(paths) <= 1, "Ambiguous native session log"
    if not paths:
        return None
    raw = paths[0].read_bytes()
    return raw, parse_task_log(raw, session_id)


def audited_tasks(wire_tasks, native_proof=None):
    """Cross-check any wire receipts and use latest native events when available."""
    if native_proof is not None:
        events = {
            (e["data"]["task"]["id"], e["data"]["task"]["revision"]): e["data"]["task"]
            for e in native_proof["task_events"]
        }
        for key, task in wire_tasks.items():
            # DSH's tool view adds these derived display fields to persisted tasks.
            view_fields = {"ready", "writeScopeWarnings"}
            persisted = events.get(key)
            assert (
                persisted is not None
                and {k: v for k, v in task.items() if k not in view_fields} == persisted
            ), "Wire/native task receipt differs"
        return native_proof["latest_tasks"]
    latest = {}
    for task in wire_tasks.values():
        previous = latest.get(task["id"])
        if previous is None or task["revision"] > previous["revision"]:
            latest[task["id"]] = task
    return list(latest.values())


def assert_completed_tasks(members, tasks):
    workers = [m for m in members if m["role"] != "supervisor"]
    assert len(tasks) == len(workers), "Native task count differs"
    for member in workers:
        matches = [t for t in tasks if t.get("ownerId") == member["session_id"]]
        assert len(matches) == 1 and matches[0]["status"] == "completed", (
            "Native Team completion not observed"
        )
