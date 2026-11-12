# Measured live pilot results

Generated 2026-11-11T12:36:15.543028+00:00 from `/Volumes/Work/Evolutionary Supervised ShareInfo Quant Factor Research Agent Team/qrs-live-deepseek-2026-11-11/private/exports/20261111T123213Z-pilot-final`.

Each row is one actual persisted execution, including failed attempts. Sequence-zero seed bookkeeping and focused paid replays are excluded. Calls include any recorded provider probes attributed to that generation. Budget charges use conservative peak cache-miss prices; they are not invoices.

| Job / generation | Execution outcome | Tasks done / failed | Real calls | Tokens | Cache hits | Peak in flight | Peak RPM | Peak dispatch TPM | Charge CNY | Published factors / notes |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| J-0001 / 1 | FAIL | 0 / 1 | 5 | 7,019 | 14.75% | 1 | 5 | 7,019 | 0.122673 | 0 / 0 |
| J-0002 / 1 | PASS | 1 / 0 | 25 | 135,832 | 83.00% | 1 | 11 | 83,573 | 1.111097 | 1 / 0 |
| J-0003 / 1 | PARTIAL | 2 / 1 | 24 | 122,524 | 81.55% | 1 | 12 | 76,157 | 1.004142 | 0 / 0 |
| J-0003 / 2 | PARTIAL | 2 / 1 | 11 | 61,427 | 82.63% | 1 | 8 | 34,558 | 0.724955 | 0 / 0 |
| J-0003 / 3 | PARTIAL | 1 / 2 | 46 | 341,136 | 85.99% | 1 | 12 | 100,670 | 2.005612 | 1 / 0 |
| J-0004 / 1 | PARTIAL | 2 / 1 | 79 | 677,190 | 79.83% | 1 | 15 | 145,894 | 4.562710 | 0 / 0 |
| J-0004 / 2 | PASS | 3 / 0 | 32 | 275,559 | 79.16% | 1 | 9 | 72,386 | 2.878928 | 1 / 0 |
| J-0004 / 3 | PARTIAL | 2 / 1 | 41 | 420,451 | 73.87% | 1 | 12 | 120,126 | 3.294537 | 0 / 1 |
| J-0005 / 1 | PARTIAL | 2 / 1 | 51 | 388,074 | 66.10% | 2 | 13 | 132,485 | 2.392807 | 0 / 0 |
| J-0005 / 2 | PASS | 6 / 0 | 77 | 682,117 | 74.52% | 2 | 14 | 131,837 | 4.665120 | 0 / 0 |
| J-0005 / 3 | PASS | 3 / 0 | 63 | 666,984 | 67.56% | 2 | 17 | 171,534 | 3.942337 | 1 / 0 |
| J-0005 / 4 | RECOVERED | 4 / 0 | 43 | 574,144 | 58.92% | 2 | 18 | 179,935 | 5.291568 | 1 / 1 |
| J-0005 / 5 | PASS | 4 / 0 | 93 | 957,603 | 68.46% | 2 | 17 | 183,056 | 5.734833 | 0 / 1 |
| J-0006 / 1 | PASS | 4 / 0 | 95 | 841,149 | 70.18% | 3 | 32 | 289,044 | 4.522813 | 1 / 0 |
| J-0006 / 2 | PASS | 4 / 0 | 83 | 838,595 | 67.95% | 3 | 23 | 242,719 | 5.269176 | 3 / 1 |
| J-0006 / 3 | PASS | 4 / 0 | 105 | 1,099,129 | 60.93% | 3 | 23 | 206,228 | 8.587342 | 1 / 1 |

PASS here means completed software execution without failed tasks or roles. It does not mean a candidate passed scientific gates. RECOVERED preserves the publication-stage failure and subsequent zero-call retry. Historical failures and request overruns remain in GENERATIONS.json.

| Job / generation | Persisted span min | Samples | Simultaneous container memory peak GiB | Host CPU median / maximum | Host swap peak GiB |
|---|---:|---:|---:|---:|---:|
| J-0001 / 1 | 0.67 | 8 | 1.487 | 2.89% / 3.48% | 0.000 |
| J-0002 / 1 | 4.34 | 52 | 1.560 | 3.38% / 7.76% | 0.000 |
| J-0003 / 1 | 4.55 | 54 | 1.559 | 3.30% / 14.79% | 0.000 |
| J-0003 / 2 | 3.11 | 37 | 1.510 | 4.26% / 7.32% | 0.000 |
| J-0003 / 3 | 6.59 | 79 | 1.549 | 3.25% / 11.95% | 0.000 |
| J-0004 / 1 | 15.89 | 190 | 1.593 | 3.62% / 8.95% | 0.000 |
| J-0004 / 2 | 11.39 | 136 | 1.566 | 4.46% / 41.86% | 0.000 |
| J-0004 / 3 | 11.97 | 144 | 1.558 | 3.98% / 16.85% | 0.000 |
| J-0005 / 1 | 10.90 | 131 | 1.573 | 6.03% / 19.87% | 0.000 |
| J-0005 / 2 | 16.40 | 197 | 1.589 | 3.32% / 10.94% | 0.000 |
| J-0005 / 3 | 9.46 | 113 | 1.598 | 3.57% / 11.65% | 0.000 |
| J-0005 / 4 | 26.86 | 322 | 1.545 | 4.27% / 20.95% | 0.000 |
| J-0005 / 5 | 17.14 | 205 | 1.566 | 3.17% / 9.94% | 0.000 |
| J-0006 / 1 | 10.10 | 121 | 1.592 | 3.93% / 34.41% | 0.000 |
| J-0006 / 2 | 13.76 | 165 | 1.596 | 3.39% / 8.92% | 0.000 |
| J-0006 / 3 | 29.08 | 349 | 1.634 | 3.53% / 10.76% | 0.000 |

The J-0005 generation 4 span includes an offline repair pause; its active first-attempt window is separately recorded in private/rung3/generation4-publication-retry/ATTEMPT.json. Five-second samples can miss short spikes. Host CPU includes unrelated activity; container totals include only this campaign. These are not whole-VM sizing tests.

Per-request latency, completion-attributed TPM, role/model totals, minute bins, cgroup counters, disk I/O and storage observations are retained in METRICS.json and the raw evidence.
