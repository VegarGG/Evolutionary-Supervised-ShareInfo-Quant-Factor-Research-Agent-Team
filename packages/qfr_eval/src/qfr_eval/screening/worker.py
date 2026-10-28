"""One evaluator-owned pull job, with fenced atomic completion and no trigger API."""

import base64
import hashlib
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal
from uuid import UUID, uuid4

import polars as pl
from psycopg import Connection
from qfr_core.contracts.artifacts import (
    DocumentImplementation,
    PackageImplementation,
    PythonImplementation,
    ResearchNotePayload,
)
from qfr_core.contracts.enums import ArtifactKind, ReasonCode
from qfr_core.contracts.execution import RunnerInput
from qfr_core.contracts.publication import PublishedArtifact
from qfr_core.data_layer.snapshots import Snapshot
from qfr_core.registry_client import RegistryTransportError
from qfr_core.runner_tables import pack_table, unpack_table

from qfr_eval.artifact_store import EvidenceStore
from qfr_eval.backtest.prefix import slice_inputs
from qfr_eval.execution_bundle import ArtifactExecutionBundle
from qfr_eval.protocols.models import FrozenProtocol
from qfr_eval.records import RuntimeIdentity
from qfr_eval.runtime import initialize_worker_thread, verify_runtime
from qfr_eval.sandbox.runner import ExecutionResult, SandboxRunner, SandboxUnavailable
from qfr_eval.scheduler.dedup import digest, verify_publication
from qfr_eval.scheduler.intake import IntakeScheduler, transition
from qfr_eval.screening.adapters import OutputAdapter
from qfr_eval.screening.documents import ReleasedEvidence
from qfr_eval.screening.execution import PreparedExecution, StaticFailure, prepare_execution
from qfr_eval.screening.models import KindAdapterProfile, ScreeningExecutionPolicy
from qfr_eval.screening.persistence import finish_duplicate, lock_semantics, persist_screening
from qfr_eval.screening.pilot import PilotOutputError
from qfr_eval.screening.plugins import PLUGINS, failed_outcome
from qfr_eval.screening.records import ScreeningReceipt, ScreeningRequest


class LeaseLost(RuntimeError):
    pass


class LeaseKeeper:
    """Renew operational ownership; this is never a research completion timer."""

    def __init__(
        self,
        connect: Callable[[], Connection],
        job_id: UUID,
        fence: int,
        worker: str,
        policy: ScreeningExecutionPolicy,
    ) -> None:
        self.connect, self.job_id, self.fence = connect, job_id, fence
        self.worker, self.policy = worker, policy
        self.stop = threading.Event()
        self.lost = threading.Event()
        self.thread = threading.Thread(target=self._run, name="screening-lease", daemon=True)

    def renew(self) -> None:
        with self.connect() as conn, conn.transaction():
            row = conn.execute(
                "UPDATE eval.jobs SET lease_until=clock_timestamp()+make_interval(secs=>%s),"
                "created_by=%s,request_id=%s WHERE id=%s AND state='running' AND locked_by=%s "
                "AND fence=%s AND lease_until>clock_timestamp() RETURNING id",
                [
                    self.policy.worker_lease_seconds,
                    self.worker,
                    uuid4(),
                    self.job_id,
                    self.worker,
                    self.fence,
                ],
            ).fetchone()
            if row is None:
                raise LeaseLost("screening lease lost; no official completion")

    def _run(self) -> None:
        while not self.stop.wait(self.policy.lease_renewal_seconds):
            try:
                self.renew()
            except Exception:
                # Never release raw database/network errors or continue after
                # uncertain ownership. The durable lease remains reclaimable.
                self.lost.set()
                return

    def __enter__(self) -> "LeaseKeeper":
        self.renew()
        self.thread.start()
        return self

    def ensure(self) -> None:
        if self.lost.is_set():
            raise LeaseLost("screening lease renewal failed; completion is withheld")

    def __exit__(self, *args: object) -> None:
        self.stop.set()
        self.thread.join(timeout=self.policy.lease_renewal_seconds)
        if self.thread.is_alive():
            raise LeaseLost("lease renewal shutdown remains uncertain")


@dataclass(frozen=True)
class InputSlices:
    snapshot_id: str
    # Evaluator-only source: cutoffs are chosen below, never by a research call.
    read: Callable[[PublishedArtifact, date, int], RunnerInput]

    @classmethod
    def from_snapshot(cls, snapshot: Snapshot) -> "InputSlices":
        if snapshot.manifest.zone != "full":
            raise ValueError("official screening requires a verified full-zone snapshot")

        def read(artifact: PublishedArtifact, cutoff: date, seed: int) -> RunnerInput:
            names = {"prices": "prices_daily"}
            if (
                artifact.profile == "pilot_industry_v1"
                and artifact.manifest.kind == ArtifactKind.MODEL
            ):
                names.update(features="features", universe="universe")
            tables = slice_inputs(
                {target: snapshot.read(source) for target, source in names.items()}, cutoff
            )
            return RunnerInput(
                schema_version="1", seed=seed, tables={k: pack_table(v) for k, v in tables.items()}
            )

        return cls(snapshot.manifest.snapshot_id, read)


@dataclass(frozen=True)
class WorkerResult:
    status: Literal["idle", "deferred", "duplicate", "recorded"]
    reason: Literal[
        "NO_JOB", "BACKEND_UNAVAILABLE", "INPUT_UNAVAILABLE", "DUPLICATE_OF", "SCREEN_COMPLETE"
    ]
    intake_id: UUID | None = None
    receipt: ScreeningReceipt | None = None


class ScreeningWorker:
    def __init__(
        self,
        scheduler: IntakeScheduler,
        protocol: FrozenProtocol,
        runtime: RuntimeIdentity,
        inputs: InputSlices,
        store: EvidenceStore,
        execution_policy: ScreeningExecutionPolicy,
        adapter_profiles: dict[str, KindAdapterProfile],
        sandbox: SandboxRunner | None,
        *,
        worker: str,
        released: ReleasedEvidence,
    ) -> None:
        initialize_worker_thread(runtime)
        campaign = scheduler.campaign
        if (
            campaign.runtime_hash != digest(runtime.model_dump(mode="json"))
            or campaign.protocol_hash != protocol.sha256
            or campaign.protocol_ref != protocol.protocol_id
            or campaign.snapshot_id != inputs.snapshot_id
        ):
            raise ValueError("worker does not match its frozen campaign")
        self.scheduler, self.protocol, self.runtime = scheduler, protocol, runtime
        self.inputs, self.store, self.policy = inputs, store, execution_policy
        self.profiles, self.sandbox, self.worker, self.released = (
            adapter_profiles,
            sandbox,
            worker,
            released,
        )

    def _defer(
        self, job: dict[str, Any], reason: Literal["BACKEND_UNAVAILABLE", "INPUT_UNAVAILABLE"]
    ) -> WorkerResult:
        identity = UUID(job["payload"]["intake_id"])
        with self.scheduler.connect() as conn, conn.transaction():
            row = conn.execute(
                "UPDATE eval.jobs SET state='queued',locked_by=NULL,lease_until=NULL,"
                "run_after=clock_timestamp()+make_interval(secs=>%s),created_by=%s,request_id=%s "
                "WHERE id=%s AND state='running' AND locked_by=%s AND fence=%s "
                "AND lease_until>clock_timestamp() RETURNING id",
                [
                    self.scheduler.policy.poll_interval_seconds,
                    self.worker,
                    uuid4(),
                    job["id"],
                    self.worker,
                    job["fence"],
                ],
            ).fetchone()
            if row is None:
                raise LeaseLost("cannot defer stale screening ownership")
            transition(
                conn, identity, "queued", reason=reason, principal=self.worker, request_id=uuid4()
            )
        return WorkerResult("deferred", reason, identity)

    def run_once(self) -> WorkerResult:
        verify_runtime(self.runtime)
        job = self.scheduler.claim(
            worker=self.worker, lease_seconds=self.policy.worker_lease_seconds, request_id=uuid4()
        )
        if job is None:
            return WorkerResult("idle", "NO_JOB")
        with LeaseKeeper(
            self.scheduler.connect, job["id"], job["fence"], self.worker, self.policy
        ) as lease:
            return self._run_claimed(job, lease)

    def _run_claimed(self, job: dict[str, Any], lease: LeaseKeeper) -> WorkerResult:
        intake = job["intake"]
        identity = UUID(job["payload"]["intake_id"])
        artifact = PublishedArtifact.model_validate(intake["payload"]["artifact"])
        verify_publication(artifact, self.scheduler.dsl_configs)
        manifest = artifact.manifest
        if manifest.family_id is None:
            raise ValueError("published artifact lacks server-assigned family")
        profile = self.profiles.get(artifact.profile)
        if profile is None:
            return self._defer(job, "INPUT_UNAVAILABLE")
        adapter = OutputAdapter(artifact, profile, self.protocol)
        plugin = PLUGINS[manifest.kind]
        assets = {}
        try:
            for item in manifest.payload_files:
                data = self.scheduler.client.payload(artifact, item.asset_id)
                if hashlib.sha256(data).hexdigest() != item.sha256:
                    raise ValueError("payload hash mismatch")
                assets[item.asset_id] = data
            development = self.inputs.read(
                artifact,
                self.protocol.windows["development"].end,
                self.protocol.diagnostics.root_seed,
            )
        except (RegistryTransportError, OSError, KeyError):
            return self._defer(job, "INPUT_UNAVAILABLE")
        # A trusted provider still must honor the requested slice. Never mount
        # confirmation or future availability rows due to a provider mistake.
        self._verify_cutoff(development, self.protocol.windows["development"].end)
        backend = None
        prepared: PreparedExecution | None = None
        first = None
        document = None
        behavior = None
        probes = None
        reason = plugin.eligibility(artifact, profile)
        outcome = failed_outcome(artifact, reason) if reason else None
        if outcome is None:
            if isinstance(manifest.implementation, DocumentImplementation):
                document = assets[manifest.implementation.asset_id]
            else:
                try:
                    universe = tuple(
                        sorted(
                            unpack_table(development.tables["prices"])["code"].unique().to_list()
                        )
                    )
                    prepared = prepare_execution(
                        artifact,
                        assets,
                        self.policy,
                        self.scheduler.dsl_configs.get(artifact.profile),
                        self.sandbox,
                        anonymous_universe=universe,
                    )
                    if prepared.mode == "sandbox":
                        assert self.sandbox is not None
                        backend = self.sandbox.readiness()
                        if backend.status != "ready":
                            raise SandboxUnavailable("required runtime unavailable")
                    first = prepared.execute(development)
                    lease.ensure()
                    if first.code == "failed:backend_unavailable":
                        raise SandboxUnavailable("runtime became unavailable")
                    if first.output is not None:
                        try:
                            coverage = adapter.quality(first.output, development)
                            if coverage.status != "passed":
                                outcome = failed_outcome(
                                    artifact, coverage.reason_codes[0], first=first
                                ).model_copy(update={"coverage": coverage})
                            else:
                                behavior = adapter.behavior(
                                    first.output, development, intake["semantic_scope_sha256"]
                                )
                        except (
                            PilotOutputError,
                            ValueError,
                            TypeError,
                            pl.exceptions.PolarsError,
                        ) as exc:
                            code = (
                                exc.code
                                if isinstance(exc, PilotOutputError)
                                else ReasonCode.DECLARATION_MISMATCH
                            )
                            outcome = failed_outcome(artifact, code, first=first)
                except SandboxUnavailable:
                    return self._defer(job, "BACKEND_UNAVAILABLE")
                except StaticFailure as exc:
                    outcome = failed_outcome(artifact, exc.code)
        with self.scheduler.connect() as conn, conn.transaction():
            # Serialize compatible candidates across campaigns. No validation
            # input or metric is requested before this duplicate decision.
            lock_semantics(conn, intake["semantic_scope_sha256"])
            lease.ensure()
            if behavior is not None:
                duplicate = self.scheduler.behavior_duplicate(conn, identity, behavior, self.store)
                if duplicate is not None:
                    finish_duplicate(
                        conn,
                        self.scheduler,
                        intake_id=identity,
                        duplicate_of=duplicate,
                        job_id=job["id"],
                        worker=self.worker,
                        fence=job["fence"],
                        request_id=uuid4(),
                    )
                    return WorkerResult("duplicate", "DUPLICATE_OF", identity)
            if outcome is None:
                released = self.released
                if isinstance(manifest.payload, ResearchNotePayload):
                    released = ReleasedEvidence.from_database(
                        conn,
                        manifest.provenance.program_id,
                        list(
                            set(manifest.payload.released_report_refs)
                            | set(manifest.payload.citation_refs)
                        ),
                        granularities=self.released.granularities,
                        citation_refs=self.released.citation_refs,
                    )
                if prepared is not None and behavior is not None:
                    probes = self.inputs.read(
                        artifact,
                        self.protocol.windows["validation"].end,
                        self.protocol.diagnostics.root_seed,
                    )
                    self._verify_cutoff(probes, self.protocol.windows["validation"].end)
                    execute = prepared.execute

                    def fenced_execute(value: RunnerInput) -> ExecutionResult:
                        lease.ensure()
                        result = execute(value)
                        if result.code == "failed:backend_unavailable":
                            raise SandboxUnavailable("runtime became unavailable")
                        return result

                    prepared = PreparedExecution(prepared.mode, fenced_execute)
                outcome, output = plugin.run(
                    "screening",
                    artifact,
                    adapter=adapter,
                    execution_policy=self.policy,
                    development=development,
                    probes=probes,
                    prepared=prepared,
                    first=first,
                    document=document,
                    released=released,
                )
            else:
                output = first.output if first else None
            if outcome.causality and outcome.causality.code == "failed:backend_unavailable":
                # No success, record, feedback slot or trial for an unavailable backend.
                return self._defer(job, "BACKEND_UNAVAILABLE")
            implementation = manifest.implementation
            image = (
                implementation.execution_contract.image_digest.removeprefix("sha256:")
                if isinstance(implementation, (PackageImplementation, PythonImplementation))
                else None
            )
            request = ScreeningRequest(
                schema_version="1",
                stage="screening",
                window="development",
                intake_id=identity,
                campaign_id=self.scheduler.campaign.campaign_id,
                artifact_version_id=UUID(manifest.artifact_version_id),
                content_hash=manifest.content_hash,
                program_id=manifest.provenance.program_id,
                family_id=manifest.family_id,
                protocol_id=self.protocol.protocol_id,
                protocol_version=self.protocol.version,
                protocol_hash=self.protocol.sha256,
                snapshot_id=self.inputs.snapshot_id,
                screening_policy_hash=self.scheduler.screening.sha256,
                execution_policy_hash=digest(self.policy.model_dump(mode="json")),
                adapter_profile_hash=digest(profile.model_dump(mode="json")),
                development_input_sha256=digest(development.model_dump(mode="json")),
                probe_input_sha256=digest(probes.model_dump(mode="json")) if probes else None,
                runtime=self.runtime,
                runner_image_digest=image,
                generation_id=self.scheduler.campaign.server_generation_id,
            )
            bundle = None
            if outcome.status == "passed" and prepared is not None:
                bundle = ArtifactExecutionBundle(
                    schema_version="1",
                    artifact=artifact,
                    payloads_base64={
                        k: base64.b64encode(v).decode("ascii") for k, v in assets.items()
                    },
                    execution_policy=self.policy,
                    adapter_profile=profile,
                    dsl_config=self.scheduler.dsl_configs.get(artifact.profile),
                    sandbox_profile=self.sandbox.profile if backend and self.sandbox else None,
                    screening_backend=backend,
                )
            lease.ensure()
            _, receipt = persist_screening(
                conn,
                self.scheduler,
                request,
                outcome,
                self.store,
                execution_policy=self.policy,
                adapter_profile=profile,
                development_input=development,
                probe_input=probes,
                output=output,
                behavior=behavior if outcome.status == "passed" else None,
                execution_bundle=bundle,
                job_id=job["id"],
                worker=self.worker,
                fence=job["fence"],
                request_id=uuid4(),
            )
            return WorkerResult("recorded", "SCREEN_COMPLETE", identity, receipt)

    @staticmethod
    def _verify_cutoff(request: RunnerInput, cutoff: date) -> None:
        for table in request.tables.values():
            frame = unpack_table(table)
            for column in ("date", "available_date"):
                if column in frame.columns and (
                    frame.schema[column] != pl.Date
                    or frame[column].null_count()
                    or (frame[column] > cutoff).any()
                ):
                    raise ValueError("input provider exceeded its authorized temporal slice")
