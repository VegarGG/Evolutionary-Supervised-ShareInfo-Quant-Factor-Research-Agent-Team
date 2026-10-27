"""Unit bounds plus opt-in real runsc tests, never host execution of candidates."""

import io
import json
import os
import subprocess
import sys
import zipfile
from datetime import date
from pathlib import Path

import polars as pl
import pytest
from pydantic import ValidationError
from qfr_core.contracts.execution import RunnerInput
from qfr_core.contracts.intake import ExecutionContract
from qfr_core.runner_tables import pack_table, unpack_table
from qfr_eval.backtest.prefix import CausalOutput
from qfr_eval.sandbox.models import SandboxProfile
from qfr_eval.sandbox.runner import (
    SandboxRunner,
    SandboxUnavailable,
    _BoundExceeded,
    decode_result,
    unpack_package,
)
from qfr_eval.screening.causality import run_probes
from qfr_eval.screening.models import ScreeningExecutionPolicy

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def probe_profile():
    original = json.loads((ROOT / "configs/evaluation/sandbox_pilot_v2.json").read_bytes())
    return SandboxProfile.model_validate(
        {
            **original,
            "profile_id": "bounded-synthetic-test-v1",
            "scope": "bounded_synthetic_acceptance",
            "memory_bytes": 128 * 1024**2,
            "cpu_seconds": 3,
            "timeout_seconds": 5,
            "cpus": 0.5,
            "process_limit": 8,
            "max_output_bytes": 65536,
            "tmpfs_bytes": 2 * 1024**2,
            "max_package_bytes": 65536,
            "max_input_bytes": 65536,
        }
    )


@pytest.fixture
def runner_input():
    return RunnerInput.model_validate(
        {
            "schema_version": "1",
            "seed": 123,
            "tables": {"input": {"columns": ["value"], "dtypes": ["Float64"], "rows": [[1.0]]}},
        }
    )


def package(source: str) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("runner.py", source)
    return stream.getvalue()


def contract(profile, image):
    return ExecutionContract.model_validate(
        {
            "runner": "qfr-json-runner/1",
            "image_digest": image,
            "dependency_lock_sha256": profile.dependency_lock_sha256,
            "interface": "function",
            "command": None,
            "function": "runner.py:run",
            "input_schema_ref": "RunnerInput/1",
            "output_schema_ref": "RunnerOutput/1",
            "seeds": [123],
            "approved_sandbox_profile_ref": profile.profile_id,
            "limits": {
                "cpu_seconds": profile.cpu_seconds,
                "memory_bytes": profile.memory_bytes,
                "timeout_seconds": profile.timeout_seconds,
                "max_output_bytes": profile.max_output_bytes,
                "network": "none",
                "read_only_root": True,
                "non_root": True,
                "dropped_capabilities": "ALL",
            },
        }
    )


def test_package_path_link_expansion_and_count_bounds(probe_profile):
    assert unpack_package(package("# opaque"), probe_profile) == {"runner.py": b"# opaque"}
    for name in ("../escape.py", "/escape.py", "a/../escape", "a\\escape", "a//escape"):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr(name, "x")
        with pytest.raises(ValueError, match="unsafe"):
            unpack_package(stream.getvalue(), probe_profile)
    for kind in ("symlink", "expanded", "count"):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            if kind == "symlink":
                member = zipfile.ZipInfo("link")
                member.external_attr = 0o120777 << 16
                archive.writestr(member, "/eval/private")
            elif kind == "expanded":
                archive.writestr("large", b"0" * (probe_profile.max_package_bytes + 1))
            else:
                for index in range(probe_profile.max_package_files + 1):
                    archive.writestr(str(index), "")
        with pytest.raises(ValueError):
            unpack_package(stream.getvalue(), probe_profile)


def test_output_validation_drops_execution_text_and_checks_actual_dtypes():
    invalid = [
        b'{"code":"failed:secret text","output":null}',
        b'{"code":"failed:runtime","output":null,"traceback":"secret"}',
        b'{"code":"ok","output":{"schema_version":"1","kind":"factor","tables":{'
        b'"bad":{"columns":["x"],"dtypes":["Float64"],"rows":[["not a float"]]}}}}',
    ]
    for data in invalid:
        result = decode_result(data, 4096)
        assert result.code == "failed:invalid_output" and result.output is None
    assert decode_result(b"x" * 4097, 4096).code == "failed:output_limit"
    assert decode_result(b'{"code":"failed:network","output":null}', 4096).code == "failed:network"


def test_unavailable_backend_never_executes_or_uses_runc(probe_profile, runner_input):
    runner = SandboxRunner(
        probe_profile, "sha256:" + "0" * 64, docker_binary="/nonexistent-qfr-docker"
    )
    assert runner.readiness().status == "unavailable"
    with pytest.raises(SandboxUnavailable):
        runner.execute(
            contract(probe_profile, runner.image), package("raise Exception()"), runner_input
        )
    with pytest.raises(ValidationError):
        SandboxProfile.model_validate({**probe_profile.model_dump(), "runtime": "runc"})
    with pytest.raises(ValueError, match="immutable"):
        SandboxRunner(probe_profile, "python:latest")


def test_external_capture_limits_and_deadline_kill_the_control_child(probe_profile):
    runner = SandboxRunner(probe_profile, "sha256:" + "0" * 64)
    # Trusted small CLI simulations exercise host pipe/deadline guards only.
    runner.prefix = [sys.executable, "-c"]
    with pytest.raises(_BoundExceeded):
        runner._command(["import sys; sys.stdout.write('x'*100000)"], timeout=2, limit=1024)
    with pytest.raises(subprocess.TimeoutExpired):
        runner._command(["import time; time.sleep(3)"], timeout=0.1)
    assert runner._command(["print('ok')"], timeout=2) == b"ok\n"


def test_staged_input_readability_under_umask_077_keeps_private_parent(
    probe_profile, runner_input, monkeypatch
):
    runner = SandboxRunner(probe_profile, "sha256:" + "0" * 64)
    observed = []

    def control(args, **kwargs):
        if args[0] == "create":
            mount = args[args.index("--mount") + 1]
            root = Path(mount.split("src=", 1)[1].split(",dst=", 1)[0])
            observed.append(root)
            assert root.parent.stat().st_mode & 0o777 == 0o700
            for path in [root, root / "package", root / "package/nested"]:
                assert path.stat().st_mode & 0o777 == 0o755
            for path in [root / "guest.py", root / "request.json", root / "package/nested/run.py"]:
                assert path.stat().st_mode & 0o777 == 0o444
            raise SandboxUnavailable("stop before any Docker invocation")
        assert args[0] in ("rm", "ps")
        return b""

    monkeypatch.setattr(runner, "_command", control)
    previous = os.umask(0o077)
    try:
        with pytest.raises(SandboxUnavailable):
            runner._execute({"nested/run.py": b"# opaque"}, runner_input, {})
    finally:
        os.umask(previous)
    assert len(observed) == 1 and not observed[0].parent.exists()


@pytest.fixture
def actual_runner(probe_profile):
    image = os.environ.get("QFR_TEST_SANDBOX_IMAGE")
    if image is None:
        pytest.skip("actual runsc requires explicit local immutable QFR_TEST_SANDBOX_IMAGE")
    runner = SandboxRunner(probe_profile, image)
    readiness = runner.readiness()
    assert readiness.status == "ready", readiness.model_dump_json()
    return runner


def test_sbx_actual_controls_determinism_single_result_and_cleanup(actual_runner, runner_input):
    source = """
import random
def run(value):
    return {"schema_version":"1", "kind":"factor", "tables":{"output":{
        "columns":["score","hash"], "dtypes":["Float64","Int64"],
        "rows":[[random.random(), hash("fixed-seed")]]}}}
"""
    spec = contract(actual_runner.profile, actual_runner.image)
    first = actual_runner.execute(spec, package(source), runner_input)
    second = actual_runner.execute(spec, package(source), runner_input)
    assert first.code == second.code == "ok"
    assert first.output_sha256 == second.output_sha256
    assert all(first.isolation.values())


@pytest.mark.parametrize(
    ("source", "code"),
    [
        (
            "import socket\ndef run(v):\n s=socket.socket(); s.settimeout(.2); "
            "s.connect(('203.0.113.1',9))",
            "failed:network",
        ),
        ("def run(v):\n open('/eval/private-protocol.yaml').read()", "failed:filesystem"),
        ("def run(v):\n open('/escape','w').write('fixture')", "failed:filesystem"),
        ("import time\ndef run(v):\n time.sleep(20)", "failed:timeout"),
        ("def run(v):\n return 'x'*100000", "failed:output_limit"),
        (
            "import os,time\ndef run(v):\n for _ in range(32):\n  if os.fork()==0:\n"
            "   time.sleep(10); os._exit(0)",
            "failed:process_limit",
        ),
        (
            "import os\ndef run(v):\n os.symlink('/input/request.json','/tmp/qfr-result.json'); "
            "os._exit(0)",
            "failed:invalid_output",
        ),
    ],
)
def test_sbx_actual_bounded_negative_fixtures(actual_runner, runner_input, source, code):
    result = actual_runner.execute(
        contract(actual_runner.profile, actual_runner.image), package(source), runner_input
    )
    assert result.code == code
    assert result.output is None


@pytest.mark.parametrize(
    ("source", "code"),
    [
        ("def run(v):\n return bytearray(192*1024*1024)", "failed:memory"),
        ("def run(v):\n return sum(i*i for i in range(100000000))", "failed:cpu_limit"),
    ],
)
def test_sbx_actual_resource_exhaustion_is_bounded(probe_profile, runner_input, source, code):
    image = os.environ.get("QFR_TEST_SANDBOX_IMAGE")
    if image is None:
        pytest.skip("actual resource enforcement requires explicit local sandbox image")
    profile = SandboxProfile.model_validate(
        {
            **probe_profile.model_dump(),
            "cpu_seconds": 6 if code == "failed:memory" else 1,
            "timeout_seconds": 15 if code == "failed:memory" else 8,
        }
    )
    runner = SandboxRunner(profile, image)
    result = runner.execute(contract(profile, image), package(source), runner_input)
    assert result.code == code
    assert result.output is None


@pytest.mark.parametrize("case", ["lookahead", "nondeterminism"])
def test_sbx_actual_output_drives_causality_gate(actual_runner, case):
    request = RunnerInput(
        schema_version="1",
        seed=123,
        tables={
            "prices": pack_table(
                pl.DataFrame(
                    {
                        "date": [date(2020, 1, day) for day in range(1, 7)],
                        "code": ["a"] * 6,
                        "close": [1.0, 2.0, 4.0, 8.0, 16.0, 32.0],
                    }
                )
            )
        },
    )
    # Deliberately trusted, tiny negative fixtures run through the actual
    # isolation boundary, bypassing static admission only to test the defenses.
    source = """
import os
def run(value):
    rows=value["tables"]["prices"]["rows"]
    score=SCORE
    return {"schema_version":"1", "kind":"factor", "tables":{"output":{
        "columns":["date","code","score"], "dtypes":["Date","String","Float64"],
        "rows":[[row[0],row[1],score] for row in rows]}}}
""".replace(
        "SCORE",
        "sum(r[2] for r in rows)/len(rows)"
        if case == "lookahead"
        else "float(int.from_bytes(os.urandom(6)))",
    )
    spec = contract(actual_runner.profile, actual_runner.image)

    def execute(value):
        return actual_runner.execute(spec, package(source), value)

    def project(output, value):
        frame = unpack_table(output.tables["output"])
        return {
            "output": CausalOutput(
                frame.with_columns(pl.col("date").alias("_available_date")), ("date", "code")
            )
        }

    policy = ScreeningExecutionPolicy.model_validate_json(
        (ROOT / "configs/evaluation/screening_execution_v1.json").read_bytes()
    )
    evidence, _ = run_probes(
        request, execute, project, [date(2020, 1, 3)], policy, atol=1e-12, rtol=1e-12
    )
    assert evidence.status == "failed"
    if case == "lookahead":
        assert evidence.code == "failed:lookahead"
        assert evidence.prefix_passed is evidence.perturbation_passed is False
    else:
        assert evidence.code == "failed:nondeterministic" and evidence.deterministic is False


def _structural_publication(definition):
    from uuid import uuid4

    from qfr_core.contracts.publication import PublishedArtifact

    body = definition.model_dump(mode="json")
    body.update(
        artifact_version_id=str(uuid4()),
        artifact_id=str(uuid4()),
        family_id=str(uuid4()),
        content_hash="0" * 64,
        implementation_fingerprint="0" * 64,
        canonical_fingerprint=None,
        created_at="2026-10-26T00:00:00Z",
        created_by="sandbox-structural-fixture",
    )
    return PublishedArtifact.model_validate(
        dict(
            manifest=body,
            profile="generic",
            version_no=1,
            published_seq=1,
            dsl_policy_hash=None,
            payload_digest="0" * 64,
        )
    )


def test_kind_constrained_python_receives_no_calendar_or_instrument_ids(actual_runner):
    import hashlib

    from qfr_core.contracts.artifacts import ArtifactDefinition
    from qfr_eval.screening.execution import prepare_execution

    source = b"""def run(value):
    assert list(value["tables"]) == ["values"]
    table = value["tables"]["values"]
    assert table["columns"] == ["series", "observation", "close"]
    assert all(isinstance(x, (int, float)) for row in table["rows"] for x in row)
    return {"schema_version":"1","kind":"factor","tables":{"output":{
      "columns":["series","observation","score"],"dtypes":["Int64","Int64","Float64"],
      "rows":[[r[0],r[1],2*r[2]] for r in table["rows"]]}}}
"""
    body = json.loads((ROOT / "contracts/examples/ArtifactDefinition.valid.json").read_bytes())
    body.update(
        implementation=dict(
            type="constrained_python",
            source_asset_id="source",
            entrypoint="runner.py:run",
            execution_contract=contract(actual_runner.profile, actual_runner.image).model_dump(
                mode="json"
            ),
        ),
        payload_files=[
            dict(
                asset_id="source",
                sha256=hashlib.sha256(source).hexdigest(),
                media_type="text/x-python",
            )
        ],
    )
    body["payload"].update(fields_used=["close"], max_lookback_days=0)
    artifact = _structural_publication(ArtifactDefinition.model_validate(body))
    policy = ScreeningExecutionPolicy.model_validate_json(
        (ROOT / "configs/evaluation/screening_execution_v1.json").read_bytes()
    )
    request = RunnerInput(
        schema_version="1",
        seed=123,
        tables={
            "prices": pack_table(
                pl.DataFrame(
                    {
                        "date": [date(2021, 1, 1), date(2021, 1, 2)],
                        "code": ["private-a", "private-a"],
                        "close": [1.0, 2.0],
                    }
                )
            )
        },
    )
    prepared = prepare_execution(
        artifact, {"source": source}, policy, None, actual_runner, anonymous_universe=("private-a",)
    )
    result = prepared.execute(request)
    assert result.code == "ok" and result.output is not None
    frame = unpack_table(result.output.tables["output"])
    assert frame["code"].to_list() == ["private-a", "private-a"]
    assert frame["score"].to_list() == [2.0, 4.0]
    assert prepared.execute(request).output_sha256 == result.output_sha256


def test_kind_frozen_model_json_weights_execute_in_actual_sandbox(actual_runner):
    import base64

    from qfr_eval.screening.execution import prepare_execution
    from qfr_registry.seeds import package_seed

    source = b"""import json
from pathlib import Path
def run(value):
    coefficient = json.loads(Path(__file__).with_name("weights.json").read_text())["coefficient"]
    rows = value["tables"]["prices"]["rows"]
    previous = {}
    output = []
    for day, code, close in rows:
        score = None if code not in previous else coefficient * (close / previous[code] - 1)
        previous[code] = close
        output.append([day, code, score])
    return {"schema_version":"1","kind":"model","tables":{"output":{
      "columns":["date","code","score"],"dtypes":["Date","String","Float64"],"rows":output}}}
"""
    definition = package_seed(
        ROOT,
        "sandbox-model-fixture",
        "frozen-json-model",
        "model",
        contract(actual_runner.profile, actual_runner.image),
        source=source,
        weights={"kind": "model", "coefficient": 0.5},
        source_hashes=[],
    )
    artifact = _structural_publication(definition.manifest)
    assets = {item.asset_id: base64.b64decode(item.data_base64) for item in definition.files}
    policy = ScreeningExecutionPolicy.model_validate_json(
        (ROOT / "configs/evaluation/screening_execution_v1.json").read_bytes()
    )
    request = RunnerInput(
        schema_version="1",
        seed=123,
        tables={
            "prices": pack_table(
                pl.DataFrame(
                    {
                        "date": [date(2021, 1, 1), date(2021, 1, 2)],
                        "code": ["a", "a"],
                        "close": [10.0, 15.0],
                    }
                )
            )
        },
    )
    prepared = prepare_execution(
        artifact, assets, policy, None, actual_runner, anonymous_universe=("a",)
    )
    result = prepared.execute(request)
    assert result.code == "ok" and result.output is not None
    assert unpack_table(result.output.tables["output"])["score"].to_list() == [None, 0.25]
    assert prepared.execute(request).output_sha256 == result.output_sha256
