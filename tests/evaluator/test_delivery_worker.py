"""Independent HTTP pull with real DB/signatures and synthetic Registry evidence."""

import secrets
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from qfr_core.contracts.delivery import DeliveryCandidate
from qfr_core.service_client import PublicServiceClient, ServiceTransportError
from qfr_eval.delivery.models import DeliveryWorkerConfiguration
from qfr_eval.delivery.worker import pull_and_check
from test_delivery_checker import changed, delivery_case

pytestmark = pytest.mark.database


@contextmanager
def endpoints(case, *, replacement=None):
    calls = []
    candidate = DeliveryCandidate(schema_version="1", context=case.context, proposal=case.proposal)
    raw = replacement if replacement is not None else candidate.model_dump_json().encode()
    tokens = {"RESEARCH": secrets.token_urlsafe(32), "REGISTRY": secrets.token_urlsafe(32)}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            calls.append(("GET", self.path))
            path = urlsplit(self.path).path
            expected = tokens["RESEARCH" if path.startswith("/v1/jobs/") else "REGISTRY"]
            if self.headers.get("Authorization") != "Bearer " + expected:
                self.send_error(401)
                return
            if path.startswith("/v1/jobs/"):
                body = raw
            elif path.startswith("/v1/artifacts/"):
                identity = path.split("/")[3]
                artifact, payload = case.registry.values[identity]
                body = payload if path.endswith("/payload") else artifact.model_dump_json().encode()
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        shared = dict(
            revision=1,
            base_url=f"http://127.0.0.1:{server.server_port}",
            timeout_seconds=2,
            max_request_bytes=1048576,
            max_response_bytes=1048576,
        )
        config = DeliveryWorkerConfiguration(
            schema_version="1",
            program_id=case.context.job.project_id,
            policy=case.policy,
            research_client={**shared, "token_ref": "env:RESEARCH"},
            registry_client={**shared, "token_ref": "env:REGISTRY"},
        )
        try:
            yield config, tokens, calls
        finally:
            server.shutdown()
            thread.join(5)
            assert not thread.is_alive()


def run(factory, case, config, environment):
    with factory() as conn:
        return pull_and_check(
            conn,
            config,
            environment,
            UUID(case.context.job.job_id),
            UUID(case.proposal.proposal_id),
            case.signer,
            case.verifier,
            case.store,
            principal="synthetic-pulling-worker",
            request_id=uuid4(),
        )


def test_delivery_worker_independently_pulls_and_checks_without_research_push(
    eval_connect, tmp_path
):
    case = delivery_case(eval_connect, tmp_path)
    with endpoints(case) as (config, env, calls):
        result = run(eval_connect, case, config, env)
        assert result.result == "pass"
        assert calls[0] == (
            "GET",
            f"/v1/jobs/{case.context.job.job_id}/delivery-proposals/" + case.proposal.proposal_id,
        )
        assert len(calls) == 5 and all(method == "GET" for method, _ in calls)
        assert run(eval_connect, case, config, env) == result
        # Retry re-reads the admitted intent but does not execute or create a trial.
        assert len(calls) == 6


@pytest.mark.parametrize("issue", ["program", "job", "schema", "credential"])
def test_delivery_pull_rejects_substitution_before_registry_or_checking(
    eval_connect, tmp_path, issue
):
    case = delivery_case(eval_connect, tmp_path)
    replacement = b'{"result":"pass"}' if issue == "schema" else None
    if issue == "job":
        job = changed(case.context.job, job_id=str(uuid4()))
        replacement = (
            DeliveryCandidate(
                schema_version="1",
                context=changed(case.context, job=job),
                proposal=changed(case.proposal, job_id=job.job_id),
            )
            .model_dump_json()
            .encode()
        )
    with endpoints(case, replacement=replacement) as (config, env, calls):
        if issue == "program":
            config = changed(config, program_id=str(uuid4()))
        if issue == "credential":
            env = {}
        with pytest.raises((ValueError, ServiceTransportError)):
            run(eval_connect, case, config, env)
        assert len(calls) == (0 if issue == "credential" else 1)
        with eval_connect() as conn:
            assert conn.execute(
                "SELECT count(*) FROM eval.delivery_attempts WHERE job_id=%s",
                [case.context.job.job_id],
            ).fetchone() == (0,)


def test_public_transport_refuses_redirects_excess_bytes_and_unsafe_routes():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            calls.append(self.path)
            self.send_response(302 if self.path == "/v1/redirect" else 200)
            self.send_header("Location", "/v1/credential-target")
            self.send_header("Content-Length", "33")
            self.end_headers()
            self.wfile.write(b"x" * 33)

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        from qfr_core.contracts.access import PublicServiceClientConfiguration

        config = PublicServiceClientConfiguration(
            revision=1,
            base_url=f"http://127.0.0.1:{server.server_port}",
            token_ref="env:TOKEN",
            timeout_seconds=1,
            max_request_bytes=32,
            max_response_bytes=32,
        )
        client = PublicServiceClient.from_environment(config, {"TOKEN": secrets.token_urlsafe(32)})
        try:
            with pytest.raises(ServiceTransportError) as error:
                client.request("GET", "v1/redirect")
            assert error.value.status == 302 and calls == ["/v1/redirect"]
            with pytest.raises(ServiceTransportError, match="size bound"):
                client.request("GET", "v1/oversize")
            for path in (
                "//other/v1/route",
                "v1/../admin",
                "v1/%2e%2e/admin",
                "v1/a#token",
                "v1/a\\b",
                "https://elsewhere/v1/path",
            ):
                with pytest.raises(ValueError):
                    client.request("GET", path)
            with pytest.raises(ServiceTransportError):
                client.request("GET", "v1/jobs", body=b"bad")
            with pytest.raises(ServiceTransportError):
                client.request("POST", "v1/jobs", body=b"x" * 33)
            assert calls == ["/v1/redirect", "/v1/oversize"]
        finally:
            server.shutdown()
            thread.join(5)
            assert not thread.is_alive()
