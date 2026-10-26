# Licensed local pilot fixtures

This directory contains metadata and derived golden evidence, not licensed raw inputs.
Set `QFR_PILOT_ROOT` to the directory containing the original
`P0_English_Delivery_20261022` and `P1_English_Delivery_20261022` folders. Originals remain
read-only source material. Tests never import the frozen runtime or execute replay/model code.

`appendix-a3-spec.json` transcribes the specified row counts, column counts and date ranges.
`manifests/` records each of the six run_snapshot inputs and the industry label map. The
appendix omits SHA-256 values and some complete column lists; these come from the original
files, verified against each package's SHA256SUMS.json. The label map has no date column;
its range is null. Compact financial report dates are normalized to ISO in metadata only.

`golden_evidence.json` preserves original CSV cell strings, row locations and source hashes:
primary-window results, 2026 summaries including bootstrap intervals, formal paired intervals,
fixed-neighbour values/ranges, year-exclusion results, calendar-shift diagnostics, ledger
counts and all 24 reference business CSV hashes per package. The original ledgers and CSVs
remain the exact replay oracle. This extraction neither evaluates a factor nor proves replay.

`just test` skips the 15 licensed-data checks explicitly when QFR_PILOT_ROOT is absent.
A configured but missing or mismatching source fails. To verify the extraction itself:

```sh
uv run --locked --all-packages python -m scripts.extract_pilot_evidence --check
```

The extractor refuses to overwrite differing expected evidence. A change needs original
source evidence and a decision log entry. All history remains previously seen; no holdout,
PIT-clean lineage or future performance claim follows from these fixtures.
