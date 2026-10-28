# Independent research delivery

The Stage 4 checker is an evaluator-owned operation. Research submits immutable
references and a proposed conclusion to its own API; it cannot submit trusted
check results, provide a receipt, invoke evaluation or choose signing keys. The
explicit evaluator-owner `delivery-check` CLI independently reads the admitted
job and proposal over authenticated HTTP. Idle startup does not run the command.
The Research API route and completion/export integration follow in P4.9.

`configs/delivery/pilot_research_delivery_v1.json` is a versioned checker profile
for this P0/P1 verification only. It binds release policy revision 2 without
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

The checker independently reads Registry manifests and payloads, verifies their
canonical publication hashes, program and file checksums, and checks every
required deliverable. Every declared executable artifact, including a retained
Ladder origin, needs a matching signed public report. Every required protocol
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
claim about untested candidates. All scope measurements must have adequate data,
resolved hurdle outcomes and required replay evidence. A positive proposal must
name a nonempty shortlist of passing versions. Negative conclusions must be
permitted by the brief; missing reports, insufficient data or failed required
checks cannot pass. Optional human sign-off is bound to the exact proposal and
gate. Investment promotion remains separate.

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
