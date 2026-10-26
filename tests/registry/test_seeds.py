import base64
import io
import json
import os
import secrets
import threading
import zipfile
from datetime import date
from pathlib import Path
from uuid import UUID, uuid4

import polars as pl
import pytest
from qfr_core.contracts.artifacts import ArtifactReference
from qfr_core.contracts.execution import RunnerTable
from qfr_core.contracts.intake import ExecutionContract
from qfr_core.contracts.publication import (
    RegistryClientConfiguration,
)
from qfr_core.registry_client import RegistryClient, RegistryTransportError
from qfr_core.runner_tables import pack_table, unpack_table
from qfr_registry.seeds import (
    dsl_seeds,
    note_seed,
    package_seed,
    pilot_seed,
    publish_mixed_bundle,
    sha256,
    verify_original,
)
from qfr_registry.validation import InvalidPublication

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def seed_contract():
    # Existing immutable Python image; this test proves declarations, NOT execution readiness.
    body = json.loads((ROOT / "contracts/examples/ExecutionContract.valid.json").read_bytes())
    body.update(
        {
            "runner": "qfr-json-runner/1",
            "interface": "function",
            "command": None,
            "function": "runner.py:run",
            "input_schema_ref": "RunnerInput/1",
            "output_schema_ref": "RunnerOutput/1",
            "approved_sandbox_profile_ref": "declaration-test-only",
            "image_digest": "sha256:"
            + "febd0be41adb897a0ab8f1f1c693d8912669ea60c4940e076e9946b60e210ef0",
            "dependency_lock_sha256": sha256((ROOT / "uv.lock").read_bytes()),
        }
    )
    return ExecutionContract.model_validate(body)


@pytest.fixture
def seed_request(seed_contract, program):
    def create(kind="factor", name=None, references=(), negative=None):
        source = ROOT / "fixtures/artifacts/runners" / ("negative.py" if negative else "generic.py")
        return package_seed(
            ROOT,
            program,
            name or "fixture-" + kind,
            kind,
            seed_contract,
            source=source.read_bytes(),
            weights={"kind": kind, "coefficient": 0.5, "case": negative},
            source_hashes=[],
            references=references,
        )

    return create


def test_runner_tables_roundtrip_dates_nulls_integers_boolean_empty_and_order():
    frame = pl.DataFrame(
        {
            "date": [date(2020, 1, 1), None],
            "code": ["中文", "0001"],
            "value": [1.2345678901234567, None],
            "integer": [2**63, 0],
            "eligible": [True, False],
        },
        schema_overrides={"integer": pl.UInt64},
    )
    for source in (frame, frame.head(0), pl.DataFrame()):
        encoded = pack_table(source).model_dump_json()
        actual = unpack_table(RunnerTable.model_validate_json(encoded))
        assert actual.equals(source) and actual.schema == source.schema
    for invalid in (
        {"columns": ["x", "x"], "dtypes": ["Int8", "Int8"], "rows": []},
        {"columns": ["x"], "dtypes": ["Int8"], "rows": [[1, 2]]},
        {"columns": ["x"], "dtypes": ["String"], "rows": [[{"object": "forbidden"}]]},
        {"columns": [], "dtypes": [], "rows": [[]]},
    ):
        with pytest.raises(ValueError):
            RunnerTable.model_validate(invalid)
    with pytest.raises(ValueError):
        pack_table(pl.DataFrame({"x": [float("nan")]}))
    with pytest.raises((ValueError, TypeError)):
        unpack_table(RunnerTable(columns=["x"], dtypes=["Date"], rows=[[1]]))


@pytest.mark.database
def test_p2_5_real_http_seed_bundle_all_kinds_and_retries(registry_http, seed_request):
    requests = [seed_request(kind) for kind in ("factor", "model", "strategy", "data_product")]
    first = publish_mixed_bundle(registry_http, requests)
    repeated = publish_mixed_bundle(registry_http, requests)
    assert all(r.created for r in first) and not any(r.created for r in repeated)
    assert [r.artifact for r in first] == [r.artifact for r in repeated]
    assert len({r.artifact.manifest.kind for r in first}) == 4
    for result, request in zip(first, requests, strict=True):
        artifact = registry_http.get(UUID(result.artifact.manifest.artifact_version_id))
        assert artifact == result.artifact
        content = registry_http.payload(artifact, "package")
        assert content == base64.b64decode(
            next(f.data_base64 for f in request.files if f.asset_id == "package")
        )
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            assert archive.namelist() == ["runner.json", "runner.py", "weights.json"]
    page = registry_http.page(since_seq=first[0].artifact.published_seq - 1, limit=100)
    assert page.items == [r.artifact for r in first]
    references = tuple(
        ArtifactReference(
            artifact_version_id=r.artifact.manifest.artifact_version_id,
            content_hash=r.artifact.manifest.content_hash,
        )
        for r in first[:2]
    )
    mixed = registry_http.publish(
        seed_request("strategy", name="mixed-strategy", references=references)
    )
    assert mixed.artifact.manifest.payload.signal_artifacts == list(references)


@pytest.mark.database
def test_strategy_reference_cannot_forge_hash_or_cross_program(
    registry_service, publisher, seed_request
):
    source = registry_service.publish(seed_request(), publisher, uuid4()).artifact
    reference = ArtifactReference(
        artifact_version_id=source.manifest.artifact_version_id, content_hash="0" * 64
    )
    with pytest.raises(InvalidPublication, match="reference unavailable or mismatched"):
        registry_service.publish(
            seed_request("strategy", references=(reference,)), publisher, uuid4()
        )


@pytest.mark.database
@pytest.mark.parametrize(
    "case", ["lookahead", "network", "filesystem", "readonly", "fork", "timeout", "nondeterminism"]
)
def test_negative_fixture_publication_is_opaque(registry_http, seed_request, case):
    request = seed_request(negative=case)
    result = registry_http.publish(request)
    assert result.created
    assert registry_http.payload(result.artifact, "package")
    assert result.artifact.manifest.research_side_checks.development_prefix_check == "not_run"


@pytest.mark.database
def test_six_v4_dsl_seeds_pass_registry_analysis(registry_service, publisher, program):
    requests = dsl_seeds(ROOT, program)
    assert len(requests) == 6
    published = [registry_service.publish(r, publisher, uuid4()).artifact for r in requests]
    assert all(a.manifest.canonical_fingerprint for a in published)
    assert all(a.profile == "pilot_industry_v1" for a in published)


@pytest.mark.database
@pytest.mark.pilot
def test_original_p0_p1_seed_provenance_and_no_raw_data(registry_http, seed_contract, program):
    if "QFR_PILOT_ROOT" not in os.environ:
        pytest.skip("Original licensed P0/P1 input packages required")
    root = Path(os.environ["QFR_PILOT_ROOT"])
    config = json.loads((ROOT / "configs/registry/seeds_v1.json").read_bytes())
    for model in ("P0", "P1"):
        request = pilot_seed(ROOT, root, program, model, seed_contract)
        assert request == pilot_seed(ROOT, root, program, model, seed_contract)
        assert (
            config["original_manifest_sha256"][model] in request.manifest.provenance.source_hashes
        )
        assert request.manifest.provenance.operator == "import"
        published = registry_http.publish(request).artifact
        archive = registry_http.payload(published, "package")
        assert len(archive) < 20_000
        with zipfile.ZipFile(io.BytesIO(archive)) as package:
            assert package.namelist() == ["runner.json", "runner.py", "weights.json"]
            assert json.loads(package.read("weights.json"))["variant"] == model
        assert published.manifest.provenance.exposure.history == "previously_seen"


def test_seed_requires_explicit_matching_runtime(seed_contract, program):
    invalid = seed_contract.model_copy(update={"dependency_lock_sha256": "0" * 64})
    with pytest.raises(ValueError, match="explicit seed runtime"):
        package_seed(
            ROOT, program, "bad", "factor", invalid, source=b"opaque", weights={}, source_hashes=[]
        )


def test_invalid_client_inputs_never_echo_credentials():
    config = RegistryClientConfiguration(
        revision=1,
        base_url="http://127.0.0.1:1",
        token_ref="env:TEST_TOKEN",
        timeout_seconds=1,
        max_request_bytes=10,
        max_response_bytes=10,
    )
    for value in (None, "", "bad\ncredential", "short"):
        with pytest.raises(ValueError, match="credential is missing or invalid"):
            RegistryClient.from_environment(config, {} if value is None else {"TEST_TOKEN": value})
    token = secrets.token_urlsafe(32)
    client = RegistryClient.from_environment(config, {"TEST_TOKEN": token})
    assert token not in repr(client)
    with pytest.raises(RegistryTransportError, match="request size limit"):
        client.request("v1/artifacts", body=b"a" * 11)
    with pytest.raises(ValueError):
        client.request("https://other.invalid/v1/artifacts")
    for url in (
        "http://user:secret@localhost",
        "http://localhost?token=secret",
        "http://localhost#fragment",
    ):
        with pytest.raises(ValueError):
            RegistryClientConfiguration.model_validate({**config.model_dump(), "base_url": url})


def test_client_redirect_errors_and_size_limits():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            received.append(self.path)
            status = 302 if self.path == "/v1/redirect" else 200
            if self.path == "/v1/denied":
                status = 403
            body = b"x" * 33 if self.path == "/v1/large" else b"private-remote-body"
            self.send_response(status)
            if status == 302:
                self.send_header("Location", "/v1/target")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        config = RegistryClientConfiguration(
            revision=1,
            base_url=f"http://127.0.0.1:{server.server_port}",
            token_ref="env:TOKEN",
            timeout_seconds=1,
            max_request_bytes=32,
            max_response_bytes=32,
        )
        client = RegistryClient.from_environment(config, {"TOKEN": secrets.token_urlsafe(32)})
        try:
            for path, status in (("redirect", 302), ("denied", 403)):
                with pytest.raises(RegistryTransportError) as caught:
                    client.request("v1/" + path)
                assert caught.value.status == status and "private" not in str(caught.value)
            assert "/v1/target" not in received
            with pytest.raises(RegistryTransportError, match="response size limit"):
                client.request("v1/large")
            with pytest.raises(RegistryTransportError, match="invalid registry artifact response"):
                client.get(uuid4())
        finally:
            server.shutdown()
            worker.join(5)
            assert not worker.is_alive()


@pytest.mark.database
def test_research_note_preserves_document_kind_and_cli(
    registry_http, program, monkeypatch, tmp_path, capsys
):
    from qfr_registry.cli import main

    request = note_seed(ROOT, program)
    request_file = tmp_path / "request.json"
    request_file.write_text(request.model_dump_json())
    client_file = tmp_path / "client.json"
    client_file.write_text(registry_http.config.model_dump_json())
    monkeypatch.setenv("TEST_REGISTRY_TOKEN", registry_http.token)
    monkeypatch.setattr(
        "sys.argv", ["qfr-registry", str(request_file), "--client-config", str(client_file)]
    )
    main()
    published = json.loads(capsys.readouterr().out)["artifact"]
    assert published["manifest"]["kind"] == "research_note"
    assert published["manifest"]["cycles"] == []
    assert (
        registry_http.get(UUID(published["manifest"]["artifact_version_id"])).manifest.kind.value
        == "research_note"
    )


def test_original_source_verification_rejects_missing_changed_and_symlinked_files(tmp_path):
    root = tmp_path / "P0_English_Delivery_20261022"
    root.mkdir()
    source = root / "source.txt"
    source.write_bytes(b"original")
    manifest = json.dumps(
        {"model": "P0", "files": {"source.txt": {"bytes": 8, "sha256": sha256(b"original")}}}
    ).encode()
    (root / "SHA256SUMS.json").write_bytes(manifest)
    assert verify_original(tmp_path, "P0", sha256(manifest)) == sha256(manifest)
    source.write_bytes(b"changed!")
    with pytest.raises(ValueError, match="original file checksum mismatch"):
        verify_original(tmp_path, "P0", sha256(manifest))
    source.unlink()
    with pytest.raises(FileNotFoundError):
        verify_original(tmp_path, "P0", sha256(manifest))
    original = tmp_path / "elsewhere"
    original.write_bytes(b"original")
    source.symlink_to(original)
    with pytest.raises(ValueError, match="cannot be symlinks"):
        verify_original(tmp_path, "P0", sha256(manifest))
