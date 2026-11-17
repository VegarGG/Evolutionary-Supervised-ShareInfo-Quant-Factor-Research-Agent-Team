# Per-run and per-agent measurements

All calls in this record request GLM 5.3 with maximum reasoning effort. CNY is conservative Coding Plan exposure, not an incremental subscription invoice. RPM/TPM are peak rolling 60-second dispatch totals, not token arrival speed; completion rates are retained in JSON. Unknown tokens are excluded rather than imputed as zero. Resource figures cover the shared guard/DSH/data process tree within each role activity window, not isolated per-agent allocations.

## semantic-guards-fixed-01

GLM 5.3 / max / 32768 output cap; states {'settled': 17}; 4 findings; 0 changed score/eligibility rows; finalized True; independent outcome `needs_semantic_clarification`.

| Actor / native task | Requests | Tokens | Exposure CNY | Cache | Peak RPM / TPM | Peak shared RSS MiB | Shared mean / peak CPU cores |
| - | -: | -: | -: | -: | -: | -: | -: |
| author-2: design | 3 | 82,694 | 0.894212 | 59.44% | 1 / 30,547 | 629.1 | 0.0262 / 0.0907 |
| reviewer-1: analyze | 2 | 38,372 | 0.475176 | 38.45% | 1 / 19,322 | 602.4 | 0.0401 / 0.1100 |
| reviewer-3: review | 2 | 74,457 | 0.869756 | 41.09% | 1 / 37,301 | 642.5 | 0.0253 / 0.0678 |
| supervisor: coordination and outcome summary | 10 | 245,352 | 2.013776 | 81.69% | 3 / 120,695 | 636.5 | 0.0199 / 0.0949 |

Shared run: 691.31 seconds, 343 samples; peak RSS 642.5 MiB; mean/peak sampled CPU 0.0280/0.1100 cores; minimum host available RAM 10.93 GiB; peak swap 0 bytes; minimum Work free space 334.73 GiB.

## semantic-guards-adaptive-02

GLM 5.3 / max / 32768 output cap; states {'settled': 19}; 4 findings; 171 changed score/eligibility rows; finalized True; independent outcome `pass_with_limits`.

| Actor / native task | Requests | Tokens | Exposure CNY | Cache | Peak RPM / TPM | Peak shared RSS MiB | Shared mean / peak CPU cores |
| - | -: | -: | -: | -: | -: | -: | -: |
| author-2: design | 3 | 97,024 | 1.011212 | 58.69% | 2 / 73,578 | 391.3 | 0.0389 / 0.0909 |
| reviewer-1: analyze | 2 | 54,156 | 0.756608 | 32.85% | 1 / 27,307 | 583.6 | 0.0405 / 0.2106 |
| reviewer-3: review | 4 | 142,994 | 1.339132 | 68.02% | 3 / 98,815 | 477.9 | 0.0407 / 0.1034 |
| supervisor: coordination and outcome summary | 10 | 267,761 | 2.253928 | 82.39% | 3 / 131,299 | 610.0 | 0.0249 / 0.1060 |

Shared run: 736.10 seconds, 365 samples; peak RSS 610.0 MiB; mean/peak sampled CPU 0.0368/0.2106 cores; minimum host available RAM 10.36 GiB; peak swap 0 bytes; minimum Work free space 334.71 GiB.
