# Per-run and per-agent measurements

All calls in this record request GLM 5.3 with maximum reasoning effort. CNY is conservative Coding Plan exposure, not an incremental subscription invoice. RPM/TPM are peak rolling 60-second dispatch totals, not token arrival speed; completion rates are retained in JSON. Unknown tokens are excluded rather than imputed as zero. Resource figures cover the shared guard/DSH/data process tree within each role activity window, not isolated per-agent allocations.

## typed-evidence-fixed-01

GLM 5.3 / max / 32768 output cap; states {'settled': 13}; 4 findings; 0 changed score/eligibility rows; finalized False; independent outcome `incomplete_harness_false_positive`.

| Actor / native task | Requests | Tokens | Exposure CNY | Cache | Peak RPM / TPM | Peak shared RSS MiB | Shared mean / peak CPU cores |
| - | -: | -: | -: | -: | -: | -: | -: |
| author-2: design | 6 | 265,765 | 2.700720 | 79.25% | 3 / 142,731 | 664.9 | 0.0331 / 0.0855 |
| reviewer-1: analyze | 2 | 59,213 | 0.833784 | 29.82% | 1 / 29,690 | 594.8 | 0.0380 / 0.0782 |
| supervisor: coordination; stopped before finalization | 5 | 63,333 | 0.539844 | 67.87% | 2 / 30,561 | 633.9 | 0.0311 / 0.1036 |

Shared run: 746.03 seconds, 370 samples; peak RSS 664.9 MiB; mean/peak sampled CPU 0.0349/0.1036 cores; minimum host available RAM 10.63 GiB; peak swap 1127677952 bytes; minimum Work free space 334.65 GiB.

## typed-repair-fixed-03

GLM 5.3 / max / 32768 output cap; states {'settled': 17}; 4 findings; 0 changed score/eligibility rows; finalized True; independent outcome `pass_with_limits`.

| Actor / native task | Requests | Tokens | Exposure CNY | Cache | Peak RPM / TPM | Peak shared RSS MiB | Shared mean / peak CPU cores |
| - | -: | -: | -: | -: | -: | -: | -: |
| author-2: design | 3 | 115,539 | 1.307292 | 55.18% | 1 / 44,910 | 290.6 | 0.0380 / 0.0865 |
| reviewer-1: analyze | 2 | 57,640 | 0.806880 | 32.36% | 1 / 28,962 | 589.4 | 0.0364 / 0.0940 |
| reviewer-3: review | 3 | 117,615 | 1.082680 | 61.55% | 2 / 87,970 | 333.4 | 0.0374 / 0.0791 |
| supervisor: coordination and native finalization | 9 | 201,525 | 1.661300 | 79.51% | 3 / 81,779 | 611.7 | 0.0290 / 0.0781 |

Shared run: 787.01 seconds, 390 samples; peak RSS 611.7 MiB; mean/peak sampled CPU 0.0367/0.1126 cores; minimum host available RAM 6.08 GiB; peak swap 3134324736 bytes; minimum Work free space 334.63 GiB.

## typed-repair-adaptive-04

GLM 5.3 / max / 32768 output cap; states {'settled': 4}; 4 findings; 0 changed score/eligibility rows; finalized False; independent outcome `incomplete_local_sublimit`.

| Actor / native task | Requests | Tokens | Exposure CNY | Cache | Peak RPM / TPM | Peak shared RSS MiB | Shared mean / peak CPU cores |
| - | -: | -: | -: | -: | -: | -: | -: |
| reviewer-1: analyze | 2 | 47,840 | 0.627100 | 37.37% | 1 / 24,156 | 581.1 | 0.0484 / 0.1061 |
| supervisor: coordination; stopped before finalization | 2 | 14,629 | 0.167932 | 29.66% | 2 / 14,629 | 611.6 | 0.0512 / 0.1040 |

Shared run: 221.05 seconds, 110 samples; peak RSS 611.6 MiB; mean/peak sampled CPU 0.0494/0.1061 cores; minimum host available RAM 10.20 GiB; peak swap 3125936128 bytes; minimum Work free space 334.63 GiB.

## typed-completion-adaptive-05

GLM 5.3 / max / 32768 output cap; states {'settled': 18}; 3 findings; 171 changed score/eligibility rows; finalized True; independent outcome `needs_definition_clarification`.

| Actor / native task | Requests | Tokens | Exposure CNY | Cache | Peak RPM / TPM | Peak shared RSS MiB | Shared mean / peak CPU cores |
| - | -: | -: | -: | -: | -: | -: | -: |
| author-2: design | 3 | 84,538 | 0.875864 | 60.94% | 2 / 61,195 | 644.0 | 0.0436 / 0.0965 |
| reviewer-1: analyze | 4 | 119,299 | 1.193472 | 70.29% | 3 / 97,515 | 616.5 | 0.0451 / 0.1122 |
| reviewer-3: review | 3 | 128,196 | 1.226828 | 60.84% | 2 / 95,338 | 684.0 | 0.0432 / 0.0982 |
| supervisor: coordination and native finalization | 8 | 184,518 | 1.609304 | 77.94% | 2 / 74,418 | 640.8 | 0.0370 / 0.1214 |

Shared run: 635.72 seconds, 315 samples; peak RSS 684.0 MiB; mean/peak sampled CPU 0.0425/0.1214 cores; minimum host available RAM 9.66 GiB; peak swap 3125936128 bytes; minimum Work free space 334.61 GiB.
