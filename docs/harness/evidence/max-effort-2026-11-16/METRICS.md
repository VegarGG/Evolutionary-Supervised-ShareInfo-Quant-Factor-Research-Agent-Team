# Per-run and per-agent measurements

All calls in this record request GLM 5.3 with maximum reasoning effort. CNY is conservative Coding Plan exposure, not an incremental subscription invoice. RPM/TPM are peak rolling 60-second dispatch totals, not token arrival speed; completion rates are retained in JSON. Unknown tokens are excluded rather than imputed as zero. Resource figures cover the shared guard/DSH/data process tree within each role activity window, not isolated per-agent allocations.

## unseen-glm53-max-adaptive-01

GLM 5.3 / max / 16384 output cap; states {'settled': 6}; 0 findings; 0 changed score/eligibility rows; finalized False; independent outcome `incomplete_output_token_cap`.

| Actor / native task | Requests | Tokens | Exposure CNY | Cache | Peak RPM / TPM | Peak shared RSS MiB | Shared mean / peak CPU cores |
| - | -: | -: | -: | -: | -: | -: | -: |
| reviewer-1: analyze | 1 | 25,630 | 0.532720 | 6.92% | 1 / 25,630 | 607.5 | 0.0425 / 0.0831 |
| supervisor: coordination and outcome summary | 5 | 54,451 | 0.478388 | 62.76% | 3 / 44,049 | 607.6 | 0.0270 / 0.0702 |

Shared run: 294.53 seconds, 146 samples; peak RSS 607.6 MiB; mean/peak sampled CPU 0.0385/0.0831 cores; minimum host available RAM 10.66 GiB; peak swap 0 bytes; minimum Work free space 336.06 GiB.

## unseen-glm53-max32-adaptive-01

GLM 5.3 / max / 32768 output cap; states {'settled': 15}; 4 findings; 0 changed score/eligibility rows; finalized True; independent outcome `rejected_prose_despite_native_review_pass`.

| Actor / native task | Requests | Tokens | Exposure CNY | Cache | Peak RPM / TPM | Peak shared RSS MiB | Shared mean / peak CPU cores |
| - | -: | -: | -: | -: | -: | -: | -: |
| author-2: design | 4 | 116,210 | 1.131580 | 62.66% | 3 / 74,921 | 416.3 | 0.0404 / 0.0956 |
| reviewer-1: analyze | 2 | 60,698 | 0.908624 | 26.54% | 1 / 30,759 | 491.5 | 0.0440 / 0.0950 |
| reviewer-3: review | 2 | 108,553 | 1.420904 | 33.06% | 1 / 55,819 | 432.0 | 0.0470 / 0.1039 |
| supervisor: coordination and outcome summary | 7 | 194,338 | 1.641044 | 72.04% | 2 / 103,115 | 480.3 | 0.0301 / 0.0870 |

Shared run: 826.23 seconds, 409 samples; peak RSS 491.5 MiB; mean/peak sampled CPU 0.0432/0.1039 cores; minimum host available RAM 10.25 GiB; peak swap 0 bytes; minimum Work free space 335.38 GiB.

## unseen-glm53-max32-fixed-02

GLM 5.3 / max / 32768 output cap; states {'settled': 13}; 4 findings; 0 changed score/eligibility rows; finalized False; independent outcome `incomplete_native_request_limit_after_submission`.

| Actor / native task | Requests | Tokens | Exposure CNY | Cache | Peak RPM / TPM | Peak shared RSS MiB | Shared mean / peak CPU cores |
| - | -: | -: | -: | -: | -: | -: | -: |
| author-2: design | 5 | 147,275 | 1.536340 | 70.99% | 3 / 98,554 | 437.5 | 0.0347 / 0.1039 |
| reviewer-1: analyze | 2 | 42,882 | 0.596816 | 33.07% | 1 / 21,816 | 593.1 | 0.0373 / 0.0880 |
| supervisor: coordination and outcome summary | 6 | 130,618 | 1.117084 | 68.68% | 3 / 107,722 | 619.2 | 0.0253 / 0.0612 |

Shared run: 492.45 seconds, 244 samples; peak RSS 619.2 MiB; mean/peak sampled CPU 0.0345/0.1281 cores; minimum host available RAM 10.21 GiB; peak swap 0 bytes; minimum Work free space 334.89 GiB.
