import json

import pytest
import zstandard

from qfh.native_audit import assert_completed_tasks, audited_tasks, parse_task_log, read_task_log


def task_log():
    tasks = [
        {"id": "task-1", "revision": 1, "status": "in_progress", "ownerId": "worker"},
        {"id": "task-1", "revision": 2, "status": "completed", "ownerId": "worker"},
    ]
    records = [{"type": "session", "version": 4, "id": "root"}]
    records.extend(
        {"type": "team/task", "seq": i, "data": {"teamId": "root", "task": t}}
        for i, t in enumerate(tasks)
    )
    return records, tasks


def encode(records):
    return zstandard.ZstdCompressor().compress(
        b"\n".join(json.dumps(r).encode() for r in records) + b"\n"
    )


def test_truncated_tool_receipt_uses_independent_native_completion(tmp_path):
    records, tasks = task_log()
    path = tmp_path / "sessions/workspace/root/session.v4.jsonl.zstd"
    path.parent.mkdir(parents=True)
    path.write_bytes(encode(records))
    raw, proof = read_task_log(tmp_path, "root")
    assert raw == path.read_bytes()
    # Model-visible tool JSON was truncated, leaving only the earlier receipt.
    view = {**tasks[0], "ready": False, "writeScopeWarnings": []}
    recovered = audited_tasks({("task-1", 1): view}, proof)
    assert recovered == [tasks[1]]
    assert_completed_tasks([{"role": "author", "session_id": "worker"}], recovered)
    with pytest.raises(AssertionError, match="receipt differs"):
        audited_tasks({("task-1", 2): {**tasks[1], "status": "in_progress"}}, proof)


@pytest.mark.parametrize("damage", ["root", "team", "order", "revision"])
def test_native_log_rejects_identity_and_history_corruption(damage):
    records, _ = task_log()
    if damage == "root":
        records[0]["id"] = "wrong"
    elif damage == "team":
        records[1]["data"]["teamId"] = "wrong"
    elif damage == "order":
        records[2]["seq"] = records[1]["seq"]
    else:
        records[2]["data"]["task"]["revision"] = 1
    with pytest.raises(AssertionError):
        parse_task_log(encode(records), "root")


def test_latest_task_state_and_exact_owner_are_required():
    _, tasks = task_log()
    latest = {("task-1", 2): tasks[1], ("task-1", 3): {**tasks[0], "revision": 3}}
    members = [{"role": "author", "session_id": "worker"}]
    with pytest.raises(AssertionError, match="completion"):
        assert_completed_tasks(members, audited_tasks(latest))
    with pytest.raises(AssertionError, match="completion"):
        assert_completed_tasks(members, [{**tasks[1], "ownerId": "different-worker"}])
    with pytest.raises(AssertionError, match="count"):
        assert_completed_tasks(members, [])


def test_no_native_log_does_not_manufacture_receipts(tmp_path):
    assert read_task_log(tmp_path, "root") is None
    with pytest.raises(AssertionError, match="count"):
        assert_completed_tasks([{"role": "author", "session_id": "worker"}], audited_tasks({}))


def test_appended_compression_frames_retain_every_task_event():
    records, tasks = task_log()
    raw = b"".join(encode([record]) for record in records)
    proof = parse_task_log(raw, "root")
    assert proof["record_count"] == 3
    assert proof["latest_tasks"] == [tasks[-1]]
