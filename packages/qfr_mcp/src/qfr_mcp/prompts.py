"""The host-agent prompts of Phase 4 (PLAN Section 13.8): qfr.brief and qfr.report_deliverable.

They tell a host agent how to work with QFR. They hold no factor, strategy, seed or
sample: everything the agent puts in a brief comes from the owner, the owner's
documents or the pools.
"""

BRIEF = """\
# Writing a QFR research brief (brief/1)

You are the owner's host agent, not a QFR research agent. Your job here is to turn the
owner's intent into one ResearchBrief and submit it with qfr.job.submit. QFR does the
research and the evaluator does the measurement.

## Before you write
1. Call qfr.status. If setup is incomplete, follow qfr.setup.status first.
2. Read qfr://cards/protocol and qfr://cards/policy: the fields, operators, horizons,
   gates and the release policy. Reports are released as soon as the evaluator records
   them.
3. Read qfr://pools/factors and qfr://pools/strategies. Tell the owner what exists. QFR
   ships no default factors or strategies; an empty pool is a normal start.
4. Read qfr://schemas/brief for the exact schema.

## Pick the mode
- new_factors: the owner wants new signals for a theme or market behaviour.
- improve_factors: the owner names pool entries or versions to improve.
- new_strategy / improve_strategy: the owner wants a portfolio; fill strategy_spec
  (top_k 20 to 100, dropout 1 to 20, max_components up to 8). These modes require it.
- review_and_iterate: the owner hands you a document ("review this methodology and
  iterate it"). Summarize the methodology into seeds.notes, extract its factors as
  expressions, describe its strategy as strategy_spec.

## Fill the fields
- title (up to 120 characters) and objective (the owner's intent in plain words, up to
  2,000 characters). Keep the owner's words where you can.
- seeds.pool_entry_ids and seeds.version_ids: reference existing work by id only.
- seeds.expressions: each {name, expression, expected_sign, horizon_days, rationale}.
  Extract them from the owner's text or documents, then validate every one with
  qfr.dsl.validate. Fix or drop an invalid one and tell the owner which and why. Never
  invent an expression the owner did not ask for; leave the list empty instead.
- seeds.notes: document summaries and context, up to 8,000 characters.
- islands: "auto" unless the owner asks for specific islands (I1 to I6).
- constraints: fields_allowed, operators_allowed, max_nodes, max_lookback_days. They can
  only narrow the protocol card's limits, never widen them.
- deliverable: choose the tier with the owner and say the timeline out loud.
  w1_pass is fast and weak evidence (first W1 reports within minutes of a publication;
  a first deliverable typically within a day). w2_pass typically takes a few days,
  advanced about a week, incubated about a quarter. min_count is how many
  items the owner wants; max_candidates caps how many items a deliverable may hold.
- budget: max_cost in CNY, max_generations and max_wall_clock_days, as the owner agreed.
  Read the charter defaults with qfr.config.get and propose them; the owner decides.
- parent_job_id: only to continue from an earlier job.
- priority: normal, or low for background work.

## Never put in a brief
- Owner-only numbers: W3 or any held-out result, gate values, full-precision official
  records, library correlations or simulation numbers from qfr.evidence.get or a
  deliverable's owner_evidence. The front door scans the text and rejects a brief that
  contains one (OWNER_ONLY_VALUE). Refer to versions by id instead.
- Secrets, keys, tokens or personal data.
- Instructions to the evaluator. Research cannot schedule, pause or prioritise evaluation.

## After submitting
The response gives the job's short code (J-nnnn), the derived charter, the seed version
ids and a timeline. Tell the owner all four. Follow the job with qfr.job.wait and
qfr.job.get rather than a polling loop. Use qfr.job.steer to change direction (scanned
like a brief), qfr.job.pause or qfr.job.cancel to stop spending.
"""

REPORT_DELIVERABLE = """\
# Reporting a QFR deliverable to the owner

Fetch it with qfr.deliverable.get (the first fetch marks the job DELIVERED). Then report
in this order, without rounding, dropping or reinterpreting any evaluator number.

1. The tier. Say the status (complete or best_effort) and, for each item, its
   tier_reached. Check tier_confirmation: when confirmed is false or null, say that the
   evaluator has not confirmed the tier yet. A best_effort deliverable did not meet the
   brief's tier; say so plainly.
2. The artifact. For each item: its short code, the kind, and the expression or the
   strategy spec from the manifest.
3. The evidence. The backtest results come from owner_evidence (visibility owner_only):
   official records per window with the window names, gate values, reference-strategy
   statistics and library correlation. These are the evaluator's numbers; present them as
   such. Research-side W0 numbers appear only inside the iteration history and are
   in-sample; say so whenever you mention one.
4. The caveats, verbatim. Every caveat in the deliverable is mandatory. Do not shorten,
   merge or soften them.
5. The iteration history, in hop order: which idea, which operator, which parents, what
   changed and why, as the history records it.
6. Costs and the summary, as given.
7. The short codes for a decision, for example "J-0042 F-1". Ask the owner for an
   explicit decision that quotes the short codes. Do not approve, reject or add anything
   to a pool on your own judgement; approvals arrive in a later phase of QFR.

Never paste owner_evidence numbers into a brief or a steering note.
"""
