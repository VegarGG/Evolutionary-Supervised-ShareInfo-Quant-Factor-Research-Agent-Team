# Evolutionary Supervised ShareInfo Quant Factor Research Agent Team

Hybrid v1 multi-agent quantitative research and factor evolution: supervisor–worker coordination, a shared research blackboard, evolutionary candidate development and a strictly independent, deterministic evaluator. Delivered as a Docker Compose bundle for `linux/amd64` and `linux/arm64`, driven through a standard MCP front door by a host agent such as Codex, with online Kimi, GLM and DeepSeek as the mandatory research-side LLM providers.

**Status:** aligned development plan, revision 2.0 (October 26, 2026). The system is not implemented.

## Start here

1. [Development kickoff prompt](docs/DEVELOPMENT_KICKOFF_PROMPT.md): the prompt that starts Stage 0 and the template for every later stage.
2. [Aligned development plan](docs/HYBRID_V1_DEVELOPMENT_PLAN.md): product definition, operating model, architecture, contracts, interfaces, research and evaluation planes, technology, repository layout, the nine development stages with entry conditions and exit gates, verification and risks.
3. [Requirements and reconciliation contract](docs/PLAN_ALIGNMENT.md): the owner's requirements R1–R6, conflict resolutions, provider/intake/MCP/lifecycle/Docker contracts and the acceptance checklist AC-01–AC-14. It governs when documents disagree.
4. [Local implementation reference](docs/LOCAL_IMPLEMENTATION_REFERENCE.md): detailed DSL, metrics, database, API, invariant, test and default specifications; its daily-stock values belong to the named `stock_daily_v1` profile.

## Supporting material

- [Pilot case: P0/P1 industry rotation](docs/appendix-a-pilot-case-industry-rotation.md), the first preservation and reproduction fixture, labelled previously inspected history.
- [Research notes](docs/appendix-b-research-notes.md), historical sources; Claude-specific recommendations are superseded and marked.
- [Illustrative provider configuration](docs/examples/llm-profiles.example.json); exact endpoints, model identifiers, settings and spending are deployment configuration.
- [Source provenance](docs/alignment-source-manifest.json) and [documentation validation](docs/plan-alignment-validation.json) from the alignment revision.

No licensed sample data or credentials are included in this repository.
