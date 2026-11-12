# Preserved QFR deployment evidence

The harness direction supersedes earlier pending development PRs; it does not
erase their source or test history. [PRs 14–19](SUPERSEDED_PRS.json) were closed at
the owner's instruction on 12 November 2026 without merging or deleting branches.
Main remains the baseline of the harness worktree, not the full late-phase deployed
code. The live experiment's final source was
`6de2fad3570b25d80d3fbceda64e16b02635e34b` in a separate checkout.

The [archive manifest](evidence/legacy-2026-11-11/MANIFEST.json) identifies eleven
byte-preserved public summaries. Full private captures remain in the original
Work-volume campaign directories. Some links within the frozen reports refer to
those omitted files; their absence from this public subset is not a claim that
they never existed. Original reports are not silently rewritten to describe the
new harness.

- [Actual DeepSeek deployment report](evidence/legacy-2026-11-11/qrs-live-deepseek-2026-11-11--REPORT.md):
  16 real execution generations (1 failed, 8 passed, 6 partial, 1 recovered),
  884 cumulative API calls and 56.256735 CNY. The last three executions were clean.
  Generation counts are not model-call counts, and synthetic orchestration loops
  are not real inference generations.
- [Scientific outcomes](evidence/legacy-2026-11-11/qrs-live-deepseek-2026-11-11--SCIENTIFIC_RESULTS.json):
  ten factor publications and five notes; six W1 passes and one W2 pass; one
  Incubating artifact. SC1/SC2 acceptance and the J6 five-W1-factor delivery were
  not satisfied. Software execution did not establish scientific acceptance.
- [Phase 3 resource record](evidence/legacy-2026-11-11/qrs-review-2026-11-10--RESOURCE_RECOMMENDATION.md):
  synthetic pilot on a native ARM64 Docker VM with 18 vCPUs and 7.75 GiB RAM;
  one evaluator at a time, normally one vCPU. The configured 8-vCPU/200-GiB minimum
  was not a measured whole-VM 8-vCPU capacity result.
- [Remediation record](evidence/legacy-2026-11-11/qrs-remediation-2026-11-10--REMEDIATION_REPORT.md):
  actual CN ingest covered 2,029 instruments, 9,339,616 rows and 6,505 dates,
  with one vCPU and a 3 GiB memory cap, no observed OOM, but memory reclaim/max
  events and little demonstrated headroom. Full-CN evaluator replays needed a
  tested 4.5 GiB cap (4.41 GiB largest measured peak); the configured worker cap
  was 6 GiB. The production two-worker/research/maintenance peak remained unmeasured.
  That workload must not be sized from the small new prototype's RSS alone.

[Carry-forward accounting](CARRY_FORWARD.json) preserves the original cost-source
hash and includes all prior spending in the same 200 CNY cap. A framework change
does not renew the budget or convert previous scientific failures into passes.
