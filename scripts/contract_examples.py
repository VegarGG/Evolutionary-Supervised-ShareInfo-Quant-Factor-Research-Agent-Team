"""Synthetic structural examples; hashes/signatures are placeholders, never evidence."""

from pathlib import Path

import yaml
from qfr_core.configuration import ConfigDocument
from qfr_core.contracts import access as access
from qfr_core.contracts import artifacts as a
from qfr_core.contracts import blackboard as b
from qfr_core.contracts import data as d
from qfr_core.contracts import delivery as x
from qfr_core.contracts import feedback as feedback
from qfr_core.contracts import intake as i
from qfr_core.contracts import jobs as j
from qfr_core.contracts import providers as p
from qfr_core.contracts import publication as pub
from qfr_core.contracts import reports as r

H = "0" * 64
AT = "2026-10-25T12:00:00Z"


def examples(root: Path):
    quality = dict(
        timing_grade="B",
        timing_basis="Documented availability convention",
        vintage_status="unknown",
        vintage_notes="Historical revisions unverified",
        membership_grade="D",
        membership_status="backfilled",
        membership_notes="Current membership mapped backward",
    )
    exposure = dict(
        history="previously_seen",
        inspected_periods=[dict(start="2020-01-01", end="2026-10-16")],
        training_tuning_history="Previously inspected history",
        provider_knowledge_exposure="unknown",
        quality=quality,
        licence_constraints=["Local authorized use only"],
        unknowns=["Index vintage"],
    )
    source = dict(
        asset_id="asset-example",
        reference=dict(
            transport="mounted_import", reference_id="declared-import", relative_path="example.json"
        ),
        sha256=H,
        bytes=0,
        media_type="application/json",
        provenance="Synthetic schema example",
        intended_use="documentation",
        licence="Synthetic",
        source_is_untrusted_data=True,
    )
    requirement = dict(
        table="prices",
        fields=["date", "code", "close"],
        universe="declared universe",
        frequency="daily",
        availability_rule=None,
        minimum_timing_grade=None,
        lookback=None,
        unresolved=["Data authorization"],
    )
    limits = dict(
        cpu_seconds=120,
        memory_bytes=4000000000,
        timeout_seconds=120,
        max_output_bytes=1024,
        network="none",
        read_only_root=True,
        non_root=True,
        dropped_capabilities="ALL",
    )
    execution = dict(
        runner="declared-python",
        image_digest="sha256:" + H,
        dependency_lock_sha256=H,
        interface="command",
        command=["runner"],
        function=None,
        input_schema_ref="inputs/1",
        output_schema_ref="outputs/1",
        seeds=[0],
        limits=limits,
        approved_sandbox_profile_ref="unresolved-sandbox",
    )
    job_config = dict(
        role_profile_refs=[],
        permitted_dataset_ids=[],
        permitted_provider_endpoints=[],
        authorized_spend_ref=None,
        authorized_cost_usd=None,
        max_wall_clock_seconds=None,
        max_generations=None,
        stop_pause_policy_ref="jobs/pilot_industry_v1.yaml",
        proposed_exit_gate_ref=None,
        human_checkpoint_policy_ref="owner-clarification",
    )
    bundle = dict(
        schema_version="1",
        bundle_id="input-example",
        input_kind="idea",
        objective="Clarify a research hypothesis",
        requested_deliverables=["research note"],
        source_assets=[source],
        definition=dict(
            kind="idea", hypothesis="A price hypothesis", unresolved_questions=["Required data"]
        ),
        data_refs=[],
        data_requirements=[requirement],
        baseline_refs=[],
        execution_contract=None,
        exposure_and_quality=exposure,
        job_config=job_config,
        protocol_proposal_ref=None,
        readiness="needs_input",
        unresolved_requirements=["Required data"],
    )
    gate = dict(
        schema_version="1",
        gate_id="gate-example",
        gate_type="research_delivery",
        required_deliverables=[
            dict(
                name="research note",
                schema_ref="ResearchNotePayload",
                required=True,
                evidence_refs_required=True,
            )
        ],
        protocol_refs=["pilot/1"],
        required_checks=["schema-valid"],
        reproducibility_criteria=["Declared evidence hashes"],
        evidence_release_requirements=["Released evidence only"],
        allowed_conclusions=["supported_negative", "empty_shortlist"],
        human_signoff_required=False,
        forward_evidence_required=False,
        independent_checker_required=True,
        frozen_at=AT,
        spec_hash=H,
    )
    brief = dict(
        schema_version="1",
        brief_id="brief-example",
        project_id="project-example",
        input_bundle_id="input-example",
        objective="Review evidence",
        universe_codes=[],
        universe_label_map_ref=None,
        benchmarks=["000905.SH"],
        primary_benchmark="000905.SH",
        decision_cycles=[
            dict(
                name="weekly",
                signal_date_rule="weekly snapshot",
                publication_rule="same snapshot",
                execution_rule="next trading close",
                review_rule=None,
            )
        ],
        selection_rule=dict(
            fraction=0.2, top_n=None, rounding="ceil", tie_break="industry name", weighting="equal"
        ),
        eligibility_rule_ref="pilot/eligibility",
        primary_metric="extreme_macro_recall",
        secondary_metrics=["rank_ic"],
        cost_levels_bps=[0, 10, 30],
        protocol_proposal_ref=None,
        exposure=exposure,
        baseline_artifact_ids=[],
        preservation_rules=["Keep accepted P1"],
        constraints=["No new data fetch"],
        success_criteria=["Evidence-backed conclusion"],
        budgets=dict(
            authorized_spend_ref=None,
            authorized_cost_usd=None,
            token_limit=None,
            concurrency_limit=None,
            max_wall_clock_seconds=None,
            max_generations=None,
            evaluator_quota_ref="pilot/quota",
        ),
        exit_gate=gate,
        role_profiles=[],
        human_checkpoints=[],
        frozen_config_hash=H,
    )
    job = dict(
        schema_version="1",
        job_id="job-example",
        project_id="project-example",
        idempotency_key="submit-example",
        payload_hash=H,
        input_bundle_id="input-example",
        brief_id="brief-example",
        config_hash=H,
        provider_profiles_ref="research/models.yaml",
        public_protocol_card_ref=None,
        authorized_spend_ref=None,
        exit_gate=gate,
        state="received",
        generation_id=None,
        evaluator_status_ref=None,
        checkpoint_refs=[],
        reason=None,
        receipt=None,
        created_at=AT,
        updated_at=AT,
    )
    pricing = dict(
        snapshot_ref=None,
        currency=None,
        input_per_million=None,
        output_per_million=None,
        cached_input_per_million=None,
    )
    effective = dict(
        status="unresolved",
        task_id="task-example",
        revision=1,
        provider_vendor="moonshot_kimi",
        endpoint_id="kimi_primary",
        exact_model_id=None,
        role_profile="supervisor",
        requested_settings={},
        effective_settings={},
        override_sources=["draft profile"],
        capability_test_revision=None,
        prompt_hash=H,
        config_hash=H,
        pricing_snapshot=pricing,
        budget_reservation_usd=None,
    )
    provenance = dict(
        program_id="program-example",
        generation_id=None,
        island_id=None,
        task_id=None,
        operator="human_seed",
        source_asset_ids=["asset-example"],
        source_hashes=[H],
        blackboard_refs=[],
        agent_runs=[],
        research_snapshot_id=None,
        qfr_core_version="0.1.0",
        exposure=exposure,
        dependency_lock_sha256=None,
    )
    factor = dict(
        kind="factor",
        expected_sign=1,
        horizon_days=1,
        fields_used=["close"],
        max_lookback_days=1,
        formulation="Previous observed close",
        mechanism_card=dict(
            event="Price observation",
            context="Declared market",
            qualities="Declared universe",
            direction="Pre-registered sign",
            output="Score",
        ),
    )
    artifact = dict(
        schema_version="1",
        artifact_version_id="artifact-example",
        artifact_id="lineage-example",
        family_id=None,
        content_hash=H,
        implementation_fingerprint=H,
        canonical_fingerprint=H,
        parent_version_ids=[],
        name="synthetic-factor",
        title="Synthetic contract example",
        kind="factor",
        implementation=dict(type="dsl", language="qfr-dsl/1", expression="close"),
        payload=factor,
        payload_files=[dict(asset_id="asset-example", sha256=H, media_type="application/json")],
        parameters={},
        data_requirements=[requirement],
        eligible_protocols=["pilot/1"],
        cycles=["weekly"],
        output_schema_ref="score/1",
        rationale=dict(
            hypothesis_id=None,
            summary="Synthetic example",
            mechanism="Schema only",
            falsification="Not a measured claim",
            change_summary=None,
        ),
        complexity=1,
        provenance=provenance,
        research_side_checks=dict(
            official=False,
            dsl_validation="not_run",
            static_analysis="not_run",
            development_prefix_check="not_run",
            evidence_refs=[],
            critic_verdict_id=None,
            review_rounds=0,
        ),
        created_at=AT,
        created_by="fixture-author",
    )
    missing = dict(value=None, missing_reason="not_measured")
    signature = dict(
        algorithm="Ed25519", key_id="synthetic-not-a-real-key", signature_hex="0" * 128
    )
    identity = dict(
        artifact_version_id="artifact-example",
        content_hash=H,
        protocol_version="pilot/1",
        dataset_version_id="dataset-example",
        evaluator_version="fixture",
    )
    scalar = dict(
        metric="extreme_macro_recall",
        sampling_unit="mature_matched_decision",
        period_count=0,
        cost_basis_ref="pilot/costs",
        baseline_version_id=None,
        measurement=missing,
        origin_artifact_version_id="artifact-example",
        attribution="current_version",
    )
    pilot = dict(
        type="pilot",
        scalar=scalar,
        hurdle_flags={
            k: "insufficient_data"
            for k in [
                "paired_primary",
                "incremental_contribution",
                "fold_majority",
                "placebo",
                "net_result",
                "turnover",
                "novelty",
                "uncertainty_stability",
                "coverage",
                "overall",
            ]
        },
        rank_bucket="withheld",
        quality_flags=["small_sample_warning"],
        minimum_detectable_effect=missing,
        not_for_selection=True,
    )
    report = dict(
        schema_version="1",
        report_id="report-example",
        identity=identity,
        family_id="family-example",
        program_id="program-example",
        release_policy_ref="pilot/policy",
        protocol_card_ref="pilot/card",
        profile="pilot_industry_v1",
        content=pilot,
        reason_codes=[],
        flags=[],
        released_at=AT,
        signature=signature,
    )
    version = dict(reference_id="evidence-example", sha256=H)
    receipt = dict(
        schema_version="1",
        receipt_id="receipt-example",
        job_id="job-example",
        gate_spec_hash=H,
        artifact_refs=[],
        dataset_refs=[version],
        protocol_refs=[version],
        config_refs=[version],
        released_report_refs=[version],
        checks=[
            dict(
                check_id="schema-valid",
                schema_ref="report/1",
                result="pass",
                evidence_refs=[version],
            )
        ],
        allowed_conclusions=["supported_negative"],
        conclusion="supported_negative",
        result="pass",
        independent_checker="delivery-checker",
        human_signoff_ref=None,
        created_at=AT,
        signature=signature,
    )
    export = dict(
        schema_version="1",
        export_id="export-example",
        job_id="job-example",
        receipt=dict(reference_id="receipt-example", sha256=H),
        artifact_refs=[],
        files=[
            dict(
                path="receipt.json",
                kind="delivery_receipt",
                reference_id="receipt-example",
                sha256=H,
                bytes=0,
            )
        ],
        created_at=AT,
        source_config_hash=H,
    )
    roots = [
        i.InputBundle.model_validate(bundle),
        j.ResearchBrief.model_validate(brief),
        j.JobRecord.model_validate(job),
        a.ArtifactManifest.model_validate(artifact),
        r.ReleasedReport.model_validate(report),
        x.DeliveryReceipt.model_validate(receipt),
        x.AdmittedDeliveryContext(
            schema_version="1",
            job=job,
            brief=brief,
            input_bundle=bundle,
            human_approval=None,
        ),
        x.HumanDeliveryApproval(
            approval_id="approval-example",
            gate_spec_hash=H,
            proposal_sha256=H,
            decision="approve",
            principal="synthetic-human",
            recorded_at=AT,
        ),
        x.DeliveryProposal(
            schema_version="1",
            proposal_id="proposal-example",
            job_id="job-example",
            conclusion="supported_negative",
            artifact_refs=[
                a.ArtifactReference(artifact_version_id="artifact-example", content_hash=H)
            ],
            released_report_refs=[version],
            deliverables=[
                x.DeliverableBinding(
                    name="research note",
                    artifact=a.ArtifactReference(
                        artifact_version_id="artifact-example", content_hash=H
                    ),
                )
            ],
            shortlist=[],
        ),
        x.ExportManifest.model_validate(export),
        p.EffectiveTaskConfiguration.model_validate(effective),
        p.ProviderProfiles.model_validate(
            yaml.safe_load((root / "configs/research/models.yaml").read_text())
        ),
        ConfigDocument.model_validate(
            yaml.safe_load((root / "configs/protocols/pilot_industry_v1.yaml").read_text())
        ),
    ]
    roots += [
        d.DatasetManifest.model_validate(
            dict(
                schema_version="1",
                dataset_version_id="dataset-example",
                manifest_sha256=H,
                as_of="2026-10-16",
                creator="fixture-author",
                parent_dataset_version_id=None,
                change_log=["Synthetic structural example"],
                exposure=exposure,
                tables=[
                    dict(
                        name="prices",
                        path="prices.parquet",
                        physical_sha256=H,
                        logical_sha256=H,
                        logical_hash_spec="sorted rows and schema/1",
                        rows=0,
                        columns=["date", "code", "close"],
                        date_range=dict(start="2020-01-02", end="2026-10-16"),
                        date_column="date",
                        grain=["date", "code"],
                        schema_ref="prices/1",
                        quality=quality,
                        licence_note="Synthetic",
                        source_description="Schema example",
                        source_asset_ids=[],
                    )
                ],
            )
        ),
        j.ReceiptReference(
            receipt_id="receipt-example",
            job_id="job-example",
            gate_spec_hash=H,
            result="fail",
            independent_checker="checker",
            receipt_sha256=H,
            signature_verified=False,
        ),
        p.ModelCapabilities(),
        p.TaskOverride(
            task_id="task-example", role_profile="supervisor", override_source="operator"
        ),
        i.ExecutionContract.model_validate(execution),
    ]
    definitions = [
        i.FactorDefinition(
            kind="factor",
            formula="close",
            representation="natural_language",
            output_schema_ref=None,
        ),
        i.ModelDefinition(
            kind="model",
            specification="Owner-supplied model",
            weight_asset_ids=[],
            preprocessing="Unresolved",
            fallback_logic="Unresolved",
            fit_interface=None,
            inference_interface=None,
            serialization=None,
        ),
        i.StrategyDefinition(
            kind="strategy",
            rules="Owner-supplied rules",
            position_state="Unresolved",
            cost_rules=None,
            rebalance_timing=None,
        ),
        i.BundleDefinition(
            kind="bundle",
            component_asset_ids=["asset-example"],
            inventory_ref="inventory-example",
            preservation_rules=["Preserve originals"],
        ),
    ]
    roots += definitions
    ref = dict(artifact_version_id="parent-example", content_hash=H)
    roots += [
        a.PythonImplementation(
            type="constrained_python",
            source_asset_id="asset-example",
            entrypoint="score",
            execution_contract=execution,
        ),
        a.CompositeImplementation(
            type="fixed_composite", components=[dict(artifact=ref, weight=1)], fitting=False
        ),
    ]
    payloads = [
        a.ModelPayload(
            kind="model",
            specification="Frozen imported model",
            weight_asset_ids=["asset-example"],
            preprocessing="Declared",
            fallback_logic="Declared",
            fit_interface=None,
            inference_interface="predict",
            serialization="declared safe format",
            training_dataset_refs=[],
        ),
        a.StrategyPayload(
            kind="strategy",
            signal_artifacts=[ref],
            position_state_rules="Declared",
            rebalance_timing="Declared",
            cost_policy_ref="pilot/costs",
            execution_prices_ref="dataset-example",
        ),
        a.ResearchNotePayload(
            kind="research_note",
            document_asset_id="asset-example",
            citation_refs=[],
            released_report_refs=[],
        ),
        a.DataProductPayload(
            kind="data_product",
            dataset_manifest_ref="dataset-example",
            output_schema_ref="dataset/1",
            deterministic_check_refs=["schema"],
        ),
    ]
    for payload in payloads:
        sample = dict(artifact, kind=payload.kind, payload=payload.model_dump())
        sample["implementation"] = (
            dict(type="document", asset_id="asset-example", format="json")
            if payload.kind in ("research_note", "data_product")
            else dict(
                type="declared_package_runner",
                package_asset_id="asset-example",
                execution_contract=execution,
            )
        )
        roots.append(a.ArtifactManifest.model_validate(sample))
    w1 = dict(
        type="w1",
        rank_ic_mean=missing,
        rank_ic_ir=missing,
        nw_t_bucket="unavailable",
        positive_rank_ic_date_share=missing,
        decay_profile={"1": missing},
        ls_net_sharpe=missing,
        monotonicity=missing,
        top_turnover=missing,
        rank_autocorrelation=missing,
        max_library_correlation=missing,
        library_artifact_version_id=None,
        yearly_rank_ic={"2026": missing},
        coverage_bucket="unavailable",
        size_neutral_rank_ic=missing,
        complexity=1,
    )
    import hashlib

    from qfr_core.contracts.signing import VerificationKey, VerificationPolicy

    # RFC 8032 public test vector; never a deployment trust grant.
    test_public = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
    roots.append(
        VerificationPolicy(
            revision=1,
            canonicalization="qfr-signed-json-v1",
            maximum_document_bytes=1048576,
            keys=[
                VerificationKey(
                    algorithm="Ed25519",
                    key_id="ed25519:" + hashlib.sha256(bytes.fromhex(test_public)).hexdigest(),
                    public_key_hex=test_public,
                    purposes=["released_report", "delivery_receipt"],
                )
            ],
        )
    )
    roots += [
        r.StockW1Release.model_validate(w1),
        r.StockW2Release(type="w2", decision="FAIL", ladder_status="withheld", scalar=None),
        r.StatusRelease(type="intake", status="queued"),
        r.AdvancementRelease(type="advancement", decision="NOT_ADVANCED"),
        r.SimulationRelease(
            type="sim",
            status="failed",
            rank_ic_bucket="unavailable",
            sharpe_bucket="unavailable",
            evidence_mode="replay",
        ),
        r.DecisionRelease(
            type="decision", decision="REJECTED", category="gate_failed", gate="quality"
        ),
        r.LibraryRelease(type="library", membership="baseline"),
        r.PlanningDetectability(
            metric="extreme_macro_recall",
            critical_t=2,
            period_source="released_scalar_origin_period_count",
            assumption="independent_mature_matched_decisions",
            admission_effect="none",
        ),
        r.PublicProtocolCard(
            schema_version="1",
            protocol_version="pilot/1",
            profile="pilot_industry_v1",
            universe="31 industries",
            label_definition="Publication to next execution close",
            metric_definitions={"extreme_macro_recall": "Mean top/bottom recall"},
            cost_policy_ref="pilot/costs",
            public_gate_descriptions=["Independent evidence required"],
            release_policy_ref="pilot/policy",
            exposure="previously_seen",
        ),
        b.BlackboardRecord(
            schema_version="1",
            record_id="note-example",
            project_id="project-example",
            kind="note",
            author_role="researcher",
            task_id=None,
            text="Synthetic interpretation",
            artifact_version_refs=[],
            released_report_refs=[],
            parent_record_refs=[],
            status="open",
            created_at=AT,
        ),
        b.AuditEvent(
            schema_version="1",
            event_id="event-example",
            principal="fixture-author",
            request_id="request-example",
            action="schema-example",
            entity_ref="input-example",
            evidence_refs=[],
            at=AT,
        ),
    ]
    roots.append(
        d.SnapshotManifest.model_validate(
            dict(
                schema_version="1",
                snapshot_id=H,
                profile="stock_daily_v1",
                zone="research",
                research_cutoff="2020-01-01",
                as_of="2020-01-01",
                source="synthetic example",
                release_tag=None,
                archive_sha256=None,
                build_code_version="schema-example",
                conventions={"prices": "adjusted"},
                exposure=exposure,
                tables=[
                    dict(
                        name="panel",
                        files=[
                            dict(path="panel/year=2020/part.parquet", physical_sha256=H, bytes=1)
                        ],
                        columns={"date": "Date", "instrument": "String", "close": "Float64"},
                        grain=["instrument", "date"],
                        date_column="date",
                        available_date_column=None,
                        rows=1,
                        logical_sha256=H,
                        logical_hash_spec="qfr-table/1:sorted-grain,sorted-columns,float-hex,null",
                        quality=quality,
                        licence_note="Synthetic",
                        source_hashes={},
                    )
                ],
            )
        )
    )
    definition = a.ArtifactDefinition.model_validate(
        {k: v for k, v in artifact.items() if k in a.ArtifactDefinition.model_fields}
    )
    roots += [
        pub.PublicationRequest(
            publish_key="synthetic-publication",
            profile="pilot_industry_v1",
            manifest=definition,
            files=[pub.EncodedPayload(asset_id="asset-example", data_base64="")],
            content_hash=None,
        ),
        pub.PublicationResponse(
            artifact=pub.PublishedArtifact(
                manifest=a.ArtifactManifest.model_validate(artifact),
                profile="pilot_industry_v1",
                version_no=1,
                published_seq=1,
                dsl_policy_hash=H,
                payload_digest=H,
            ),
            created=True,
        ),
        pub.RunnerPackage(
            format="qfr-json-runner/1",
            kind="model",
            entrypoint="runner.py:run",
            input_schema_ref="inputs/1",
            output_schema_ref="outputs/1",
            dependency_lock_sha256=H,
            fields_used=["close"],
            max_lookback_days=1,
            weight_files=["weights.json"],
        ),
    ]
    page = pub.ArtifactPage(
        items=[
            pub.PublishedArtifact(
                manifest=a.ArtifactManifest.model_validate(artifact),
                profile="pilot_industry_v1",
                version_no=1,
                published_seq=1,
                dsl_policy_hash=H,
                payload_digest=H,
            )
        ],
        next_cursor=1,
        has_more=False,
    )
    roots += [
        pub.RegistryClientConfiguration(
            revision=1,
            base_url="http://registry-api:8000/",
            token_ref="env:REGISTRY_READER_TOKEN",
            timeout_seconds=10,
            max_request_bytes=8388608,
            max_response_bytes=16777216,
        ),
        pub.RegistryAuthenticationConfiguration(
            revision=1,
            enabled=True,
            minimum_token_bytes=32,
            maximum_token_bytes=512,
            bindings=[
                pub.RegistryTokenBinding(
                    principal="fixture-publisher",
                    token_ref="env:REGISTRY_PUBLISHER_TOKEN",
                    roles=["publisher"],
                    programs=["program-example"],
                )
            ],
        ),
        pub.FamilyPage(
            family_id="family-example",
            program_id="program-example",
            kind="factor",
            name="synthetic-factor",
            created_by="fixture-author",
            created_at=AT,
            versions=page,
        ),
        pub.ArtifactLineage(
            root_version_id="artifact-example",
            depth=1,
            nodes=[
                pub.LineageNode(
                    artifact_version_id="artifact-example",
                    content_hash=H,
                    family_id="family-example",
                    kind="factor",
                    version_no=1,
                ),
                pub.LineageNode(
                    artifact_version_id="child-example",
                    content_hash=H,
                    family_id="family-example",
                    kind="factor",
                    version_no=2,
                ),
            ],
            edges=[
                pub.LineageEdge(
                    version_id="child-example",
                    parent_version_id="artifact-example",
                    relation="revision",
                )
            ],
            truncated_at_depth=False,
        ),
    ]
    from qfr_core.contracts.execution import (
        ReleasedNumericClaim,
        ResearchNoteDocument,
        RunnerInput,
        RunnerOutput,
        RunnerTable,
    )

    table = RunnerTable(columns=["value"], dtypes=["Float64"], rows=[[1.0], [None]])
    roots += [
        RunnerInput(schema_version="1", tables={"close": table}, seed=0),
        RunnerOutput(schema_version="1", kind="factor", tables={"scores": table}),
        ResearchNoteDocument(
            schema_version="1",
            title="Synthetic note",
            body="The structured claim cites a synthetic released report.",
            citation_refs=["report-example"],
            numeric_claims=[
                ReleasedNumericClaim(
                    report_id="report-example",
                    field_path=["content", "scalar", "measurement", "value"],
                    value=0.5,
                )
            ],
        ),
    ]
    roots += [
        b.ResearchProgram(
            schema_version="1",
            program_id="program-example",
            name="Synthetic research context",
            status="inactive",
            charter_revision=1,
            charter={"new_data_fetch": False, "paid_run_authorized": False},
            created_by="fixture-author",
            created_at=AT,
        ),
        b.ResearchQueueLease(
            schema_version="1",
            queue_entry_id="queue-example",
            program_id="program-example",
            research_job_id="job-example",
            queue="validation",
            worker="fixture-worker",
            fence=1,
            attempt=1,
            lease_until=AT,
            payload={"input_ref": "bundle-example"},
        ),
        r.WithheldRelease(type="withheld", reason="budget"),
        r.PublicReleasePolicyCard(
            schema_version="1",
            policy_ref="pilot-release-v1@1",
            policy_sha256=H,
            profile="pilot_industry_v1",
            fitness_profile="pilot_single_scalar_flags_v1",
            disclosure="scalar_plus_flags",
            ladder_step=0.011239912200318261,
            rounding={"primary": 0.011239912200318261},
            batch_hours=6,
            weekly_batch=None,
            advancement_delay_days=None,
            quotas={"lineage_versions_per_generation": 3},
            raw_series_released=False,
            confirmation_metrics_released=False,
            diagnostics="enum_codes_only",
            prior_best_origin_required=True,
        ),
    ]
    roots.extend(
        [
            access.ServiceAuthentication(
                revision=1,
                audience="feedback",
                minimum_token_bytes=32,
                maximum_token_bytes=4096,
                bindings=[
                    access.ServiceTokenBinding(
                        principal="example-reader",
                        token_ref="env:QFR_FEEDBACK_READER_TOKEN",
                        roles=["reader"],
                        programs=["example-program"],
                    )
                ],
            ),
            feedback.FeedbackReadPolicy(
                revision=1, max_page_size=100, max_page_bytes=1048576, statement_timeout_ms=5000
            ),
            feedback.ReportPage(schema_version="1", items=[], next_after_id=None, has_more=False),
            feedback.ArtifactFeedback(
                schema_version="1",
                artifact_version_id="00000000-0000-0000-0000-000000000001",
                latest_released=None,
                timeline=feedback.ReportPage(
                    schema_version="1", items=[], next_after_id=None, has_more=False
                ),
            ),
            feedback.PublicCards(schema_version="1", policies=[], protocols=[]),
        ]
    )
    roots.extend(
        [
            x.DeliveryCandidate(
                schema_version="1",
                context=next(
                    value for value in roots if isinstance(value, x.AdmittedDeliveryContext)
                ),
                proposal=next(value for value in roots if isinstance(value, x.DeliveryProposal)),
            ),
            access.PublicServiceClientConfiguration(
                revision=1,
                base_url="http://research-api:8000",
                token_ref="env:QFR_RESEARCH_READER_TOKEN",
                timeout_seconds=10,
                max_request_bytes=1048576,
                max_response_bytes=4194304,
            ),
        ]
    )
    research_manifest = next(value for value in roots if isinstance(value, d.SnapshotManifest))
    research_manifest = research_manifest.model_copy(
        update={
            "zone": "research",
            "research_cutoff": research_manifest.as_of,
        }
    )
    roots.append(
        d.ResearchDatasetRegistration(
            schema_version="1",
            registration_id=H,
            program_id="example-program",
            dataset_version_id=H,
            source_ref="example-source",
            research_manifest=research_manifest,
            research_manifest_sha256=H,
        )
    )
    from scripts.research_contract_examples import examples as research_examples

    roots.extend(research_examples(root, roots))
    return roots
