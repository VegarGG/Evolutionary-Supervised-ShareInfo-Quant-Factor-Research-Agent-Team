# Immutable registry publication

The registry is the only artifact writer. A human or importer prepares a
`PublicationRequest` and submits it over authenticated HTTP, for example:

```sh
python -m qfr_registry.cli request.json --client-config client.json
```

`RegistryClientConfiguration` names a base URL, an environment-variable token
reference, timeout and request/response byte limits. No credential is embedded in
the request or configuration. Redirects are rejected, remote error bodies are not
echoed, and retries are explicit. Reusing an unchanged publication key returns
the same version; changing its content fails. The committed authentication config
remains disabled. Tests use ephemeral credentials; no real token deployment is
implied by these examples.

`qfr_registry.seeds` builds deterministic requests and never imports their code.
Callers must supply a complete execution contract with an immutable image digest,
the current dependency-lock hash and the declared `qfr-json-runner/1` interface.
Publication verifies declarations; it does not prove runtime readiness or approve
an image. Evaluator admission performs those independent checks.

P0/P1 seed preparation verifies every original file against its pinned package
manifest. It packages the QFR port of the original frozen business rules and JSON
configuration, retaining source-manifest hashes and previously-seen labels.
Original data, logs and source documents stay local. The adapter is not described
as a byte-for-byte copy of the uploaded Python runtime. P0/P1 retain the complete
available input prefix, including quarterly state: their runner lookback is
explicitly null (full prefix), not an invented 250-day truncation. Evaluation
compares the published adapter with the original and Stage 2 results.

Standalone factor, frozen model, strategy and data-product packages preserve
their semantic kinds; a document stays a research note. A mixed import publishes
individual immutable versions, preserving references and receipts. It does not
claim a cross-request transaction: an interrupted import resumes through each
request's idempotency key. Strategy references require the exact version/hash in
the same authorized program. Negative fixtures are opaque source at publication;
only the validated sandbox may execute them.

The data-only `RunnerInput/1` and `RunnerOutput/1` interfaces serialize typed scalar
tables as JSON. Dates, nulls, column/row order and integer types are explicit;
pickle, Python objects and non-finite JSON numbers are not accepted. No private
protocol, evaluator module, credential or dataset path is supplied to a runner.
The runner receives only the authorized input slice.
