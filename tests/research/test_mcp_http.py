"""MCP SDK over actual HTTP and PostgreSQL; financial evidence is synthetic only."""

import asyncio
from uuid import UUID

import pytest
from mcp_support import connection, frontdoor
from qfr_research.api.exports import Exports
from test_delivery_acceptance import delivery_setup
from test_research_jobs import changed

pytestmark = pytest.mark.database


def test_sdk_schema_submit_reconnect_recover_lost_ack_and_conflict(research_connect, tmp_path):
    case = delivery_setup(research_connect, tmp_path / "research", service_class=Exports)
    args = dict(program_id=str(case.program), value=case.admission.model_dump(mode="json"))
    with frontdoor(case, tmp_path / "transport") as front:

        async def first():
            async with connection(front) as (session, info):
                assert info.server_info.name == "QFR"
                tools = (await session.list_tools()).tools
                names = {t.name for t in tools}
                assert {
                    "qfr_research_submit",
                    "qfr_research_status",
                    "qfr_delivery_export",
                } <= names
                assert not any(
                    any(x in name for x in ["activate", "evaluate", "official", "sign", "promote"])
                    for name in names
                )
                assert all(t.input_schema and t.output_schema and t.annotations for t in tools)
                assert not any("ctx" in t.input_schema.get("properties", {}) for t in tools)
                result = await session.call_tool("qfr_research_submit", args)
                assert not result.is_error, result
                return result.structured_content

        saved = asyncio.run(first())

        async def second():
            async with connection(front) as (session, _):
                retried = await session.call_tool("qfr_research_submit", args)
                assert not retried.is_error and retried.structured_content == saved
                job = saved["data"]["job"]["job_id"]
                status = await session.call_tool(
                    "qfr_research_status", dict(program_id=str(case.program), job_id=job)
                )
                assert (
                    not status.is_error
                    and status.structured_content["data"]["job"]["job_id"] == job
                )
                altered = changed(
                    case.admission,
                    input_bundle=changed(case.admission.input_bundle, objective="different"),
                    brief=changed(case.admission.brief, objective="different"),
                )
                rejected = await session.call_tool(
                    "qfr_research_submit", {**args, "value": altered.model_dump(mode="json")}
                )
                assert rejected.is_error and "409" in rejected.content[0].text

        asyncio.run(second())


def test_mcp_actual_signature_checks_and_paginated_resource(research_connect, tmp_path):
    import hashlib
    import json

    from qfr_core.data_layer.snapshots import canonical_json

    case = delivery_setup(research_connect, tmp_path / "research", service_class=Exports)
    report = case.evidence.signed_report
    args = dict(program_id=str(case.program), report_id=report.report_id)
    with frontdoor(
        case,
        tmp_path / "transport",
        policy_changes={
            "max_inline_result_bytes": 500,
            "resource_page_characters": 600,
        },
    ) as front:

        async def scenario():
            async with connection(front) as (session, _):
                result = await session.call_tool("qfr_report_read", args)
                assert not result.is_error, result
                value = result.structured_content
                assert value["official_signature_verified"]
                assert set(value["data"]) == {"read_resource", "bytes"}
                assert len(result.content[0].text) < 500
                text, page, pages = "", 0, 1
                while page < pages:
                    uri = f"report://{case.program}/{report.report_id}/{page}"
                    resource = await session.read_resource(uri)
                    part = json.loads(resource.contents[0].text)
                    pages = part["pages"]
                    assert part["page"] == page and part["official_signature_verified"]
                    assert part["document_sha256"] == value["document_sha256"]
                    text += part["text"]
                    page += 1
                assert text.encode() == canonical_json(report.model_dump(mode="json"))
                assert hashlib.sha256(text.encode()).hexdigest() == value["document_sha256"]

        asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["unsigned", "tampered", "cross-program"])
def test_mcp_refuses_unverifiable_official_evidence(research_connect, tmp_path, kind):
    import copy
    from uuid import uuid4

    case = delivery_setup(research_connect, tmp_path / "research", service_class=Exports)
    report = case.evidence.signed_report
    raw = copy.deepcopy(report.model_dump(mode="json"))
    if kind == "unsigned":
        raw.pop("signature")
    elif kind == "tampered":
        raw["content"]["scalar"]["measurement"]["value"] = 0.9
    else:
        raw.pop("signature")
        raw["program_id"] = str(uuid4())
        raw = case.evidence.signer.seal(type(report), "released_report", raw).model_dump(
            mode="json"
        )
    with frontdoor(case, tmp_path / "transport") as front:
        front.replacement[f"/v1/reports/{report.report_id}"] = raw

        async def scenario():
            async with connection(front) as (session, _):
                result = await session.call_tool(
                    "qfr_report_read",
                    dict(
                        program_id=str(case.program),
                        report_id=report.report_id,
                    ),
                )
                assert result.is_error and result.structured_content is None
                assert "verification refused" in result.content[0].text

        asyncio.run(scenario())


def test_mcp_reader_and_program_scope_enforced_not_tool_annotations(research_connect, tmp_path):
    from uuid import uuid4

    case = delivery_setup(research_connect, tmp_path / "research", service_class=Exports)
    with frontdoor(case, tmp_path / "transport", roles=["reader"]) as front:

        async def scenario():
            async with connection(front) as (session, _):
                result = await session.call_tool(
                    "qfr_program_read", dict(program_id=str(case.program))
                )
                assert not result.is_error
                for name, args in [
                    ("qfr_program_read", dict(program_id=str(uuid4()))),
                    (
                        "qfr_research_submit",
                        dict(
                            program_id=str(case.program),
                            value=case.admission.model_dump(mode="json"),
                        ),
                    ),
                    (
                        "qfr_research_control",
                        dict(
                            program_id=str(case.program),
                            job_id=case.status.job.job_id,
                            value=dict(
                                operation_key="forbidden",
                                expected_revision=case.status.revision,
                                action="cancel",
                            ),
                        ),
                    ),
                ]:
                    result = await session.call_tool(name, args)
                    assert result.is_error and not result.structured_content

        asyncio.run(scenario())
        current = case.service.get_job(case.principal, UUID(case.status.job.job_id))
        assert current == case.status


def test_mcp_verified_export_reference_and_tampered_download_refusal(research_connect, tmp_path):
    import hashlib

    import httpx
    from test_delivery_acceptance import seal_receipt

    case = delivery_setup(research_connect, tmp_path / "research", service_class=Exports)
    receipt = seal_receipt(case)
    with frontdoor(case, tmp_path / "transport") as front:

        async def scenario():
            async with connection(front) as (session, _):
                accepted = await session.call_tool(
                    "qfr_delivery_accept",
                    dict(
                        program_id=str(case.program),
                        job_id=case.status.job.job_id,
                        value=dict(
                            operation_key="accept",
                            expected_revision=case.status.revision,
                            proposal_id=case.proposal.proposal_id,
                            receipt_id=receipt.receipt_id,
                        ),
                    ),
                )
                assert not accepted.is_error, accepted
                exported = await session.call_tool(
                    "qfr_delivery_export",
                    dict(
                        program_id=str(case.program),
                        job_id=case.status.job.job_id,
                        value=dict(operation_key="export", shortlist_only=False),
                    ),
                )
                assert not exported.is_error, exported
                assert exported.structured_content["official_signature_verified"]
                return exported.structured_content["data"]

        ref = asyncio.run(scenario())
        with httpx.Client(
            base_url=front.url,
            headers={"Authorization": "Bearer " + front.token},
            timeout=5,
            trust_env=False,
        ) as http:
            result = http.get(ref["download_path"])
            assert result.status_code == 200
            assert hashlib.sha256(result.content).hexdigest() == ref["archive_sha256"]
            tampered = receipt.model_dump(mode="json")
            tampered["signature"]["signature_hex"] = "0" * 128
            front.replacement[f"/v1/delivery-receipts/{receipt.receipt_id}"] = tampered
            result = http.get(ref["download_path"])
            assert result.status_code == 503 and b"PK" not in result.content


def test_mcp_binary_transport_resume_hash_and_mount_confinement(research_connect, tmp_path):
    import hashlib

    import httpx

    case = delivery_setup(research_connect, tmp_path / "research", service_class=Exports)
    raw = "原始中文数据\n".encode() * 20
    value = dict(
        operation_key="file",
        asset_id="original",
        sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),
        media_type="text/plain",
        provenance="Synthetic fixture",
        intended_use="documentation",
        licence="Synthetic",
        source_is_untrusted_data=True,
    )
    with frontdoor(case, tmp_path / "transport") as front:

        async def prepare():
            async with connection(front) as (session, _):
                result = await session.call_tool(
                    "qfr_upload_prepare", dict(program_id=str(case.program), value=value)
                )
                assert not result.is_error, result
                return result.structured_content["data"]

        saved = asyncio.run(prepare())
        path = f"/v1/programs/{case.program}/uploads/{saved['upload_id']}/chunks"
        headers = {"Authorization": "Bearer " + front.token}
        with httpx.Client(base_url=front.url, headers=headers, timeout=5, trust_env=False) as http:
            for offset in range(0, len(raw), saved["chunk_bytes"]):
                data = raw[offset : offset + saved["chunk_bytes"]]
                chunk_headers = {
                    "Content-Type": "application/octet-stream",
                    "X-Chunk-Offset": str(offset),
                    "X-Chunk-SHA256": hashlib.sha256(data).hexdigest(),
                }
                response = http.post(
                    path, content=data, headers={**chunk_headers, "X-Chunk-SHA256": "0" * 64}
                )
                assert response.status_code == 400
                response = http.post(path, content=data, headers=chunk_headers)
                assert response.status_code == 200, response.text
                assert (
                    http.post(path, content=data, headers=chunk_headers).json() == response.json()
                )
            assert http.get(path).status_code == 405

        async def finalize():
            async with connection(front) as (session, _):
                status = await session.call_tool(
                    "qfr_upload_status",
                    dict(program_id=str(case.program), upload_id=saved["upload_id"]),
                )
                assert not status.is_error and status.structured_content["data"][
                    "bytes_received"
                ] == len(raw)
                result = await session.call_tool(
                    "qfr_upload_finalize",
                    dict(
                        program_id=str(case.program),
                        upload_id=saved["upload_id"],
                        value=dict(sha256=value["sha256"]),
                    ),
                )
                assert not result.is_error, result
                state = result.structured_content["data"]
                assert state["state"] == "validated" and not state["execution_authorized"]
                source = await session.call_tool(
                    "qfr_sources_list", dict(program_id=str(case.program))
                )
                assert not source.is_error and len(source.structured_content["data"]["items"]) == 1
                for relative in ["../escape", "/etc/passwd", "link"]:
                    request = dict(
                        declaration={**value, "operation_key": relative},
                        mount_id="originals",
                        relative_path=relative,
                    )
                    refused = await session.call_tool(
                        "qfr_source_import", dict(program_id=str(case.program), value=request)
                    )
                    assert refused.is_error
                request = dict(
                    declaration={**value, "operation_key": "mounted", "asset_id": "mounted"},
                    mount_id="originals",
                    relative_path="original.txt",
                )
                imported = await session.call_tool(
                    "qfr_source_import", dict(program_id=str(case.program), value=request)
                )
                assert not imported.is_error, imported

        (front.mount / "original.txt").write_bytes(raw)
        (front.mount / "link").symlink_to(front.mount / "original.txt")
        asyncio.run(finalize())
        assert (front.store.root / f"{saved['upload_id']}.source").read_bytes() == raw


@pytest.mark.parametrize("version", ["2025-03-26", "2025-06-18", "2025-11-25"])
def test_standard_http_jsonrpc_client_and_transport_rejections(research_connect, tmp_path, version):
    import json

    import httpx

    case = delivery_setup(research_connect, tmp_path / "research", service_class=Exports)
    with frontdoor(case, tmp_path / "transport") as front:
        headers = {
            "Authorization": "Bearer " + front.token,
            "Accept": "application/json, text/event-stream",
        }
        with httpx.Client(base_url=front.url, headers=headers, timeout=5, trust_env=False) as http:
            request = dict(
                jsonrpc="2.0",
                id=1,
                method="initialize",
                params=dict(
                    protocolVersion=version,
                    capabilities={},
                    clientInfo=dict(name="independent-jsonrpc-fixture", version="1"),
                ),
            )
            response = http.post("/mcp", json=request)
            assert response.status_code == 200, response.text
            assert response.json()["result"]["protocolVersion"] == version
            http.headers["MCP-Protocol-Version"] = version
            result = http.post("/mcp", json=dict(jsonrpc="2.0", id=2, method="tools/list"))
            assert result.status_code == 200 and result.json()["result"]["tools"]
            assert (
                http.post("/mcp", json=request, headers={"Host": "evil.example"}).status_code == 421
            )
            assert (
                http.post(
                    "/mcp", json=request, headers={"Origin": "https://evil.example"}
                ).status_code
                == 403
            )
            large = dict(
                jsonrpc="2.0",
                id=3,
                method="tools/call",
                params=dict(
                    name="qfr_program_read",
                    arguments={"program_id": str(case.program), "forbidden_blob": "x" * 262144},
                ),
            )
            assert http.post("/mcp", json=large).status_code == 413
            assert (
                http.post(
                    "/mcp", json=request, headers={"Authorization": "Bearer " + "x" * 40}
                ).status_code
                == 401
            )
            assert (
                http.post(
                    "/mcp",
                    content=b'{"jsonrpc":"2.0","id":1,"id":2}',
                    headers={"Content-Type": "application/json"},
                ).status_code
                == 400
            )
            assert http.get("/v1/evaluate").status_code == 404
        serialized = json.dumps(front.logs)
        assert front.token not in serialized and "forbidden_blob" not in serialized


def test_cancel_status_then_recreate_mcp_keeps_job(research_connect, tmp_path, monkeypatch):
    import threading

    from mcp_support import serving
    from qfr_core.contracts.research import JobStatus
    from qfr_mcp.server import create_app

    case = delivery_setup(research_connect, tmp_path / "research", service_class=Exports)
    with frontdoor(case, tmp_path / "transport") as front:
        started, finish = threading.Event(), threading.Event()
        original = front.gateway.research

        def delayed(caller, program, model, method, path, *args, **kwargs):
            if model is JobStatus and method == "GET":
                started.set()
                assert finish.wait(3)
            return original(caller, program, model, method, path, *args, **kwargs)

        monkeypatch.setattr(front.gateway, "research", delayed)

        async def scenario():
            async with connection(front) as (session, _):
                pending = asyncio.create_task(
                    session.call_tool(
                        "qfr_research_status",
                        dict(program_id=str(case.program), job_id=case.status.job.job_id),
                    )
                )
                try:
                    assert await asyncio.to_thread(started.wait, 2)
                    pending.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await pending
                finally:
                    finish.set()

        asyncio.run(scenario())
        monkeypatch.setattr(front.gateway, "research", original)
        # The serving process owns no jobs; recreating the whole app retains state.
        authority = front.app.user_middleware[0].kwargs["authority"]
        with serving(create_app(front.gateway, authority=authority)) as restarted:
            front.url = restarted

            async def read():
                async with connection(front) as (session, _):
                    return await session.call_tool(
                        "qfr_research_status",
                        dict(program_id=str(case.program), job_id=case.status.job.job_id),
                    )

            result = asyncio.run(read())
            assert not result.is_error
            assert result.structured_content["data"] == case.status.model_dump(mode="json")
        assert case.service.get_job(case.principal, UUID(case.status.job.job_id)) == case.status


def test_mcp_configuration_refuses_missing_or_widened_mapping(research_connect, tmp_path):
    from dataclasses import replace

    from mcp_support import authority
    from qfr_mcp.server import create_app

    case = delivery_setup(research_connect, tmp_path / "research", service_class=Exports)
    with frontdoor(case, tmp_path / "transport") as front:
        auth, _ = authority(case.program, "mcp", ["reader"])
        with pytest.raises(PermissionError, match="not authorized"):
            create_app(front.gateway, authority=auth)
        key = next(iter(front.gateway.bindings))
        front.gateway.bindings[key] = replace(
            front.gateway.bindings[key], roles=frozenset({"reader"})
        )
        create_app(front.gateway, authority=auth)
        front.gateway.bindings.clear()
        with pytest.raises(PermissionError, match="not authorized"):
            create_app(front.gateway, authority=auth)


def test_independent_cli_reconnects_without_model_calls(research_connect, tmp_path):
    import json
    import os
    import subprocess
    import sys

    case = delivery_setup(research_connect, tmp_path / "research", service_class=Exports)
    with frontdoor(case, tmp_path / "transport") as front:
        config = tmp_path / "client.json"
        config.write_text(
            json.dumps(
                dict(
                    revision=1,
                    base_url=front.url,
                    token_ref="env:TRANSPORT_TOKEN",
                    timeout_seconds=5,
                    max_request_bytes=262144,
                    max_response_bytes=1048576,
                )
            )
        )
        values = tmp_path / "arguments.json"
        values.write_text(
            json.dumps(
                dict(program_id=str(case.program), value=case.admission.model_dump(mode="json"))
            )
        )
        environment = {
            "PATH": os.defpath,
            "TRANSPORT_TOKEN": front.token,
            "POLARS_MAX_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
        }
        command = [sys.executable, "-m", "qfr_mcp.client", "--client-config", str(config)]
        first = subprocess.run(
            [*command, "call", "qfr_research_submit", str(values)],
            env=environment,
            capture_output=True,
            text=True,
            timeout=12,
        )
        assert first.returncode == 0, first.stderr
        second = subprocess.run(
            [*command, "call", "qfr_research_submit", str(values)],
            env=environment,
            capture_output=True,
            text=True,
            timeout=12,
        )
        assert second.returncode == 0, second.stderr
        assert json.loads(first.stdout) == json.loads(second.stdout)
        for raw in ['{"program_id":"a","program_id":"b"}', '{"a": NaN}']:
            values.write_text(raw)
            refused = subprocess.run(
                [*command, "call", "qfr_program_read", str(values)],
                env=environment,
                capture_output=True,
                text=True,
                timeout=12,
            )
            assert refused.returncode == 1 and refused.stdout == ""
            assert front.token not in refused.stderr
