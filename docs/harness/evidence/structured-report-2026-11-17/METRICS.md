# Per-run and per-agent measurements

All calls in this record request GLM 5.3 with maximum reasoning effort. CNY is conservative Coding Plan exposure, not an incremental subscription invoice. RPM/TPM are peak rolling 60-second dispatch totals, not token arrival speed; completion rates are retained in JSON. Unknown tokens are excluded rather than imputed as zero. Resource figures cover the shared guard/DSH/data process tree within each role activity window, not isolated per-agent allocations.

## structured-report-fixed-01

GLM 5.3 / max / 32768 output cap; states {'settled': 22}; 4 findings; 171 changed score/eligibility rows; finalized True; independent outcome `pass_with_limits`.

| Actor / native task | Requests | Tokens | Exposure CNY | Cache | Peak RPM / TPM | Peak shared RSS MiB | Shared mean / peak CPU cores |
| - | -: | -: | -: | -: | -: | -: | -: |
| author-2: design | 5 | 131,527 | 1.321176 | 76.21% | 2 / 59,037 | 612.8 | 0.0387 / 0.1176 |
| reviewer-1: analyze | 3 | 77,196 | 0.823168 | 57.58% | 2 / 58,284 | 568.6 | 0.0516 / 0.1112 |
| reviewer-3: review | 4 | 175,683 | 1.863664 | 71.26% | 2 / 90,622 | 642.0 | 0.0374 / 0.1071 |
| supervisor: coordination and outcome summary | 10 | 251,456 | 2.110928 | 82.49% | 4 / 154,610 | 624.0 | 0.0320 / 0.1387 |

Shared run: 828.65 seconds, 410 samples; peak RSS 642.0 MiB; mean/peak sampled CPU 0.0398/0.1387 cores; minimum host available RAM 15.92 GiB; peak swap 0 bytes; minimum Work free space 334.80 GiB.

## structured-report-adaptive-02

GLM 5.3 / max / 32768 output cap; states {'settled': 9}; 0 findings; 0 changed score/eligibility rows; finalized False; independent outcome `incomplete_no_candidate`.

| Actor / native task | Requests | Tokens | Exposure CNY | Cache | Peak RPM / TPM | Peak shared RSS MiB | Shared mean / peak CPU cores |
| - | -: | -: | -: | -: | -: | -: | -: |
| reviewer-1: analyze | 6 | 257,879 | 2.816052 | 76.31% | 2 / 110,502 | 680.6 | 0.0458 / 0.1388 |
| supervisor: coordination and outcome summary | 3 | 29,490 | 0.316460 | 52.53% | 2 / 14,902 | 680.8 | 0.0467 / 0.1412 |

Shared run: 578.53 seconds, 286 samples; peak RSS 680.8 MiB; mean/peak sampled CPU 0.0460/0.1412 cores; minimum host available RAM 15.60 GiB; peak swap 0 bytes; minimum Work free space 334.78 GiB.

## task-bound-fixed-01

GLM 5.3 / max / 32768 output cap; states {'settled': 25}; 4 findings; 0 changed score/eligibility rows; finalized True; independent outcome `needs_semantic_clarification`.

| Actor / native task | Requests | Tokens | Exposure CNY | Cache | Peak RPM / TPM | Peak shared RSS MiB | Shared mean / peak CPU cores |
| - | -: | -: | -: | -: | -: | -: | -: |
| author-2: design | 4 | 113,236 | 1.159988 | 70.03% | 2 / 63,302 | 632.7 | 0.0476 / 0.0850 |
| reviewer-1: analyze | 7 | 274,165 | 2.760000 | 79.48% | 3 / 148,894 | 605.0 | 0.0401 / 0.0981 |
| reviewer-3: review | 4 | 145,608 | 1.311204 | 71.64% | 3 / 116,294 | 698.6 | 0.0395 / 0.0941 |
| supervisor: coordination and outcome summary | 10 | 246,877 | 2.056396 | 81.82% | 3 / 120,479 | 728.3 | 0.0369 / 0.1404 |

Shared run: 832.63 seconds, 412 samples; peak RSS 728.3 MiB; mean/peak sampled CPU 0.0416/0.1404 cores; minimum host available RAM 12.69 GiB; peak swap 0 bytes; minimum Work free space 334.75 GiB.

## task-bound-adaptive-02

GLM 5.3 / max / 32768 output cap; states {'settled': 18}; 4 findings; 171 changed score/eligibility rows; finalized True; independent outcome `pass_with_limits`.

| Actor / native task | Requests | Tokens | Exposure CNY | Cache | Peak RPM / TPM | Peak shared RSS MiB | Shared mean / peak CPU cores |
| - | -: | -: | -: | -: | -: | -: | -: |
| author-2: design | 4 | 113,740 | 1.133820 | 71.27% | 3 / 90,745 | 601.3 | 0.0476 / 0.1537 |
| reviewer-1: analyze | 2 | 55,024 | 0.766212 | 32.89% | 1 / 27,700 | 584.8 | 0.0529 / 0.1120 |
| reviewer-3: review | 3 | 120,460 | 1.156740 | 61.51% | 2 / 88,311 | 628.1 | 0.0472 / 0.0979 |
| supervisor: coordination and outcome summary | 9 | 210,057 | 1.759376 | 80.61% | 3 / 112,756 | 629.2 | 0.0402 / 0.1099 |

Shared run: 570.71 seconds, 282 samples; peak RSS 629.2 MiB; mean/peak sampled CPU 0.0485/0.1537 cores; minimum host available RAM 15.49 GiB; peak swap 0 bytes; minimum Work free space 334.74 GiB.
