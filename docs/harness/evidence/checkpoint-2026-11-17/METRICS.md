# Per-run and per-agent measurements

All calls in this record request GLM 5.3 with maximum reasoning effort. CNY is conservative Coding Plan exposure, not an incremental subscription invoice. RPM/TPM are peak rolling 60-second dispatch totals, not token arrival speed; completion rates are retained in JSON. Unknown tokens are excluded rather than imputed as zero. Resource figures cover the shared guard/DSH/data process tree within each role activity window, not isolated per-agent allocations.

## checkpoint-glm53-max-fixed-01

GLM 5.3 / max / 32768 output cap; states {'settled': 19}; 4 findings; 171 changed score/eligibility rows; finalized False; independent outcome `incomplete_native_review`.

| Actor / native task | Requests | Tokens | Exposure CNY | Cache | Peak RPM / TPM | Peak shared RSS MiB | Shared mean / peak CPU cores |
| - | -: | -: | -: | -: | -: | -: | -: |
| author-2: design | 4 | 88,311 | 0.959608 | 64.21% | 2 / 46,446 | 611.6 | 0.0350 / 0.0916 |
| reviewer-1: analyze | 2 | 54,803 | 0.784824 | 29.03% | 1 / 27,626 | 596.7 | 0.0389 / 0.0956 |
| reviewer-3: review | 6 | 139,169 | 1.265172 | 76.61% | 6 / 139,169 | 609.3 | 0.0333 / 0.0919 |
| supervisor: coordination and outcome summary | 7 | 120,210 | 1.021760 | 75.57% | 2 / 48,088 | 632.0 | 0.0279 / 0.1056 |

Shared run: 677.86 seconds, 336 samples; peak RSS 632.0 MiB; mean/peak sampled CPU 0.0354/0.1056 cores; minimum host available RAM 9.83 GiB; peak swap 0 bytes; minimum Work free space 334.86 GiB.

## checkpoint-delivery-fixed-01

GLM 5.3 / max / 32768 output cap; states {'settled': 18}; 4 findings; 171 changed score/eligibility rows; finalized True; independent outcome `exploratory_candidate_pass_with_limits`.

| Actor / native task | Requests | Tokens | Exposure CNY | Cache | Peak RPM / TPM | Peak shared RSS MiB | Shared mean / peak CPU cores |
| - | -: | -: | -: | -: | -: | -: | -: |
| author-2: design | 3 | 72,469 | 0.809312 | 59.08% | 1 / 26,601 | 608.0 | 0.0330 / 0.0581 |
| reviewer-1: analyze | 2 | 54,235 | 0.770760 | 31.32% | 1 / 27,226 | 591.0 | 0.0400 / 0.0939 |
| reviewer-3: review | 3 | 127,981 | 1.449928 | 58.49% | 2 / 91,437 | 686.9 | 0.0439 / 0.1295 |
| supervisor: coordination and outcome summary | 10 | 258,019 | 2.135432 | 82.70% | 3 / 127,934 | 635.6 | 0.0283 / 0.0781 |

Shared run: 862.28 seconds, 426 samples; peak RSS 686.9 MiB; mean/peak sampled CPU 0.0386/0.1295 cores; minimum host available RAM 9.62 GiB; peak swap 0 bytes; minimum Work free space 334.83 GiB.

## checkpoint-delivery-adaptive-02

GLM 5.3 / max / 32768 output cap; states {'settled': 20}; 4 findings; 171 changed score/eligibility rows; finalized True; independent outcome `needs_wording_revision`.

| Actor / native task | Requests | Tokens | Exposure CNY | Cache | Peak RPM / TPM | Peak shared RSS MiB | Shared mean / peak CPU cores |
| - | -: | -: | -: | -: | -: | -: | -: |
| author-2: design | 3 | 88,081 | 1.040328 | 56.46% | 1 / 32,982 | 610.5 | 0.0373 / 0.1082 |
| reviewer-1: analyze | 3 | 83,917 | 1.022316 | 58.15% | 2 / 58,537 | 597.8 | 0.0364 / 0.0883 |
| reviewer-3: review | 3 | 114,004 | 1.184612 | 59.11% | 1 / 42,638 | 662.1 | 0.0416 / 0.1120 |
| supervisor: coordination and outcome summary | 11 | 321,923 | 2.727224 | 84.29% | 3 / 143,084 | 652.8 | 0.0314 / 0.0817 |

Shared run: 884.03 seconds, 438 samples; peak RSS 662.1 MiB; mean/peak sampled CPU 0.0370/0.1120 cores; minimum host available RAM 9.74 GiB; peak swap 0 bytes; minimum Work free space 334.80 GiB.
