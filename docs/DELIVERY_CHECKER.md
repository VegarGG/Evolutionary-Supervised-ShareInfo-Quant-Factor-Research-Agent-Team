# Independent research delivery

The Stage 4 checker is an evaluator-owned operation. Research submits immutable
references and a proposed conclusion to its own API; it cannot submit trusted
check results, provide a receipt, invoke evaluation or choose signing keys. The
explicit evaluator-owner `delivery-check` CLI independently reads the admitted
job and proposal over authenticated HTTP. Idle startup does not run the command.
The Research API completion/export integration verifies the actual receipt independently; see [RESEARCH_API.md](RESEARCH_API.md).

`configs/delivery/pilot_research_delivery_v3.json` supports admission-frozen
candidate/reference roles for this P0/P1 verification only. It requires exit-gate
schema version 2. Legacy checker v1/v2 retains version-1 gate semantics; version 2
added complete input and admission hashes, which v3 also signs. Old profiles,
serialized gates and immutable receipts remain unchanged. The new profile binds
the same release policy revision 2 without
changing the measurement protocol, query allowance, windows, Ladder or admission
thresholds. Its operational limits are 64 declared artifacts, 64 reports and
100 MiB of payload bytes per check. Unknown gate requirements fail explicitly;
this profile does not implement investment promotion or a data-blocked conclusion.
Missing data remains an incomplete job rather than successful delivery.

The admitted brief must freeze all eight named checks, the exact-results/series
replay criterion, verified released evidence, protocol references and permitted
conclusions. At least one required evidence-backed research note is mandatory.
Frozen config and admission hashes bind the original bundle and brief; altered
intent, a paused/budget-blocked job or an unresolved input cannot pass.

For a version-2 gate, `assessment_scope` declares nonempty
`assessed_artifact_refs` and separate `reference_artifact_refs`, with exact
Registry version IDs and content hashes. Freeze these before admitting/running
the job. Roles must be unique and disjoint; reference-only entries must be
original declared baselines, and no baseline may be omitted. The union must
equal all executable artifacts in the eventual delivery. Admission verifies
actual Registry identities and executable kinds. A changed role or hash is
different intent, not an idempotent retry or an exclusion applied after results.

The P0/P1 preservation demonstration can predeclare P0 as the assessed candidate
and P1 as its reference, while retaining both as registered baselines. This is
about P0 relative to the already frozen P1 comparator; it makes no claim that P1
passes an improvement hurdle against itself. P1 self-comparison has identically
zero paired deltas, for which the approved bootstrap correctly reports insufficient
uncertainty. That status remains unchanged and visible. It cannot support candidate
selection or a positive conclusion. No confirmation outcomes are needed to
establish this mathematical distinction.

The checker independently reads Registry manifests and payloads, verifies their
canonical publication hashes, program and file checksums, and checks every
required deliverable. Every declared executable artifact, including a preserved
reference and a retained Ladder origin, needs a matching signed public report. Every required protocol
must be represented. Note citations must name the exact proposed reports.
The receipt links the exact artifact versions, content-addressed dataset IDs,
public protocol cards, frozen configuration/brief/proposal hashes and report
hashes. The full private protocol is never exported.

For each report, the checker verifies actual committed publication, the private
signed measurement wrapper and original evidence files. It also requires the
append-only evaluator `reproduction_match` audit for that official record and
results hash. The existing reproduction operation writes that audit only after
exact results, series, fingerprint, cluster and Registry execution-byte checks.
Checking a delivery does not create another measurement, trial or query and
does not reinterpret a saved output as an actual replay.

A supported negative or empty shortlist means the **declared scope does not
meet the frozen research hurdle**. It is not proof of no economic effect or a
claim about untested candidates. All assessed candidates must have adequate data,
estimated uncertainty, resolved hurdle outcomes and required replay evidence.
Reference-only artifacts still require complete measurements, nonempty periods,
valid scalar data, passing coverage, no failure reasons, signed released reports
and exact replay. Their self-comparison uncertainty/hurdle cannot establish a
candidate conclusion and is not reclassified as a pass. Missing reference evidence
still fails delivery. A positive proposal must name a nonempty shortlist of passing
assessed versions; references cannot enter it. Negative conclusions must be
permitted by the brief; missing reports, insufficient data or failed required
checks cannot pass. Optional human sign-off is bound to the exact proposal and
gate. Investment promotion remains separate.

Use `configs/research/api_v2.json` to trust the exact new checker hash alongside
the preserved v2 checker. Research completion, MCP job verification and offline
export reject a checker/gate-version mismatch even with a valid signature.
Exports retain the complete frozen scope and all reference reports; they never
strip unfavorable or insufficient baseline flags. Legacy API configuration stays
available for existing jobs, and no previous signed artifact is rewritten.

Each attempt and signed receipt commit atomically with audit attribution.
Concurrent retries of the same program/job/proposal return the original receipt;
conflicting content is rejected. A failed attempt is immutable. Corrected evidence
requires a new proposal ID and retains the earlier failed receipt. Research
completion must independently verify the signature and exact job/gate binding in
P4.9; a queue completion, caller flag or database reference alone is insufficient.

`GET /v1/delivery-receipts/{id}` returns signed public receipts through a
program-scoped, read-only Feedback view. Private attempts, original receipts,
measurement values and evidence files receive no new research grant. Client
requests are bounded, credentials are redacted from representations, and HTTP
redirects cannot forward bearer tokens.

Focused tests use real PostgreSQL and ephemeral Ed25519 keys with explicitly
synthetic measurements, HTTP fixtures and replay audit fixtures. They verify
implementation boundaries; the final Mac run must supply actual pilot execution,
exact replay, elapsed release batches, job completion and export evidence.
