# Evolutionary Supervised ShareInfo Quant Factor Research Agent Team

Hybrid v1 multi-agent quantitative research and factor evolution: supervisor–worker coordination, a shared research blackboard, evolutionary candidate development and a strictly independent, deterministic evaluator. Deployment targets are **macOS on Apple Silicon (ARM64), first on the Mac Studio with its existing Docker Desktop**, and **Linux AMD64**. The Compose bundle uses `linux/arm64` containers on Apple and `linux/amd64` containers on Linux AMD64; a Linux container build or test is not Apple host acceptance. A standard MCP front door connects a host agent such as Codex, with online Kimi, GLM and DeepSeek as the mandatory research-side LLM providers.

**Status:** foundation, data snapshots, DSL, metrics and the independent pilot evaluator are implemented. The evaluator supports frozen protocols, audited private records, deterministic replay and trial clustering; see [Stage 2 operations](docs/STAGE_2.md). Stage 3 implements the Registry and owner-approved Docker-native sandbox. The latest Mac report passes actual sandbox and registered P0/P1 tests; [acceptance reconciliation](docs/STAGE_3_ACCEPTANCE.md) still requires deployment evidence before Stage 3 is green. Feedback release, MCP orchestration and autonomous research remain later stages. Neither deployment target is production-accepted. Docker application services remain idle stubs until their stages implement scheduling.

DeepSeek v4.1 Flash is the first model to integrate at the provider stage. Exact official endpoint/model identifiers and explicit live-call authorization are required there; no model integration or paid calls are part of Stage 2.

The [current Stage 3 acceptance review](docs/STAGE_3_ACCEPTANCE.md) records the
790-pass, zero-skip native Mac report and the remaining Compose recovery, socket
boundary and image-evidence checks. It is **not yet merge-ready**. The
[earlier draft checkpoint](docs/STAGE_3_CHECKPOINT.md) retains its historical scope.

## Start here

1. [Development kickoff prompt](docs/DEVELOPMENT_KICKOFF_PROMPT.md): the prompt that starts Stage 0 and the template for every later stage.
2. [Aligned development plan](docs/HYBRID_V1_DEVELOPMENT_PLAN.md): product definition, operating model, architecture, contracts, interfaces, research and evaluation planes, technology, repository layout, the nine development stages with entry conditions and exit gates, verification and risks.
3. [Requirements and reconciliation contract](docs/PLAN_ALIGNMENT.md): the owner's requirements R1–R6, conflict resolutions, provider/intake/MCP/lifecycle/Docker contracts and the acceptance checklist AC-01–AC-14. It governs when documents disagree.
4. [Local implementation reference](docs/LOCAL_IMPLEMENTATION_REFERENCE.md): detailed DSL, metrics, database, API, invariant, test and default specifications; its daily-stock values belong to the named `stock_daily_v1` profile.

## Supporting material

- [Deployment targets and acceptance matrix](docs/DEPLOYMENT_TARGETS.md): Apple-first release scope, later native Linux AMD64 validation, and host/container evidence requirements.
- [Pilot case: P0/P1 industry rotation](docs/appendix-a-pilot-case-industry-rotation.md), the first preservation and reproduction fixture, labelled previously inspected history.
- [Research notes](docs/appendix-b-research-notes.md), historical sources; Claude-specific recommendations are superseded and marked.
- [Illustrative provider configuration](docs/examples/llm-profiles.example.json); exact endpoints, model identifiers, settings and spending are deployment configuration.
- [Source provenance](docs/alignment-source-manifest.json) and [documentation validation](docs/plan-alignment-validation.json) from the alignment revision.

No licensed sample data or credentials are included in this repository.

## License and use

Copyright 2026 Ziwei Huang. This is source-available software under the unchanged
[PolyForm Noncommercial License 1.0.0](LICENSE), with a separate
[additional permission](ADDITIONAL-PERMISSION.md) for individuals researching and
trading their own funds in personal accounts, including for personal financial
gain. It is not offered as OSI-approved open-source software. The additional
permission does not cover running a business, work for employers or clients,
managing others' money, or paid products, signals, advice, or services; it does
not withdraw broader rights already granted by the PolyForm license.

For uses outside the public license and additional permission:
Commercial use requires a separate written license from Ziwei Huang.
Separately authorized companies may use the software within their written
license's scope. These grants cover only rights Ziwei Huang owns or is authorized
to license; [third-party materials retain their own licenses](THIRD-PARTY-NOTICES.md).

This system was originally developed for research purposes only; it provides no guarantee of investment performance, and, to the extent permitted by law, Ziwei Huang accepts no liability for gains, losses, or other consequences arising from its use.
