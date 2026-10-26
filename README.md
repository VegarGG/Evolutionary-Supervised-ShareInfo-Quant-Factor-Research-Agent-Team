# Evolutionary Supervised ShareInfo Quant Factor Research Agent Team

Hybrid v1 multi-agent quantitative research and factor evolution, with a shared research blackboard and strictly independent evaluation.

**Status:** Stage 0 foundation implemented (October 25, 2026). The workspace, contracts, configuration, database boundaries, local fixture checks and CI/image build definitions are present. Factor computation, evaluation, MCP handlers and LLM execution are not implemented. This is not production acceptance.

See [Stage 0 setup and validation](docs/STAGE_0.md), [recorded decisions](docs/decisions.md), [public contracts](contracts/README.md) and [licensed fixture instructions](fixtures/pilot/README.md).

- Start with [requirements and plan reconciliation](docs/PLAN_ALIGNMENT.md): preserved architecture, Docker/MCP, on-demand jobs, generic inputs, configurable online providers and acceptance gates.
- Follow the [primary development plan](docs/HYBRID_V1_DEVELOPMENT_PLAN.md) for delivery order and phase acceptance.
- Use the [aligned local technical reference](docs/LOCAL_IMPLEMENTATION_REFERENCE.md) for detailed services, DSL, data models, evaluation, evolution and tests. Its daily-stock defaults are a named profile, separate from the industry pilot.
- Inspect the [illustrative provider/role configuration](docs/examples/llm-profiles.example.json); exact endpoint/model IDs, supported settings and spending require deployment configuration.
- Preserve the [P0/P1 pilot](docs/appendix-a-pilot-case-industry-rotation.md); [research notes](docs/appendix-b-research-notes.md) retain historical sources with superseded provider assumptions marked.
- Review [source provenance](docs/alignment-source-manifest.json) and [documentation validation](docs/plan-alignment-validation.json). These checks do not establish runtime, live-provider or native-hardware acceptance.

No licensed sample data or credentials are included in this repository.
