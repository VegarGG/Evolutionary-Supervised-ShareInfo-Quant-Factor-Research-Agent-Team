# Per-run and per-agent measurements

CNY means conservative exposure under Coding Plan Pro, not a subscription invoice. RPM/TPM are peak rolling 60-second dispatch totals; completion-based rates are retained in JSON. Unknown tokens are excluded, not imputed as zero. Cache percentages for incomplete attempts below describe only settled calls. Resources describe the shared guard/DSH/data tree during each activity window, not isolated role allocations.

## unseen-fixed-01

Model: glm-5.3-flash; states: {'settled': 18}; candidate change: 162 rows; finalization: False.

| Actor / actual task | Requests | Known tokens | Exposure CNY | Reserved CNY | Cache, known input | Peak RPM / TPM | Peak RSS MiB | Mean / peak CPU cores |
| - | -: | -: | -: | -: | -: | -: | -: | -: |
| author-2: design | 5 | 79,149 | 0.192222 | 0.000000 | 58.95% | 3 / 53,526 | 605.9 | 0.0350 / 0.0892 |
| reviewer-1: analyze | 4 | 46,518 | 0.116658 | 0.000000 | 50.80% | 3 / 36,603 | 611.0 | 0.0330 / 0.0726 |
| reviewer-3: review | 4 | 83,046 | 0.197760 | 0.000000 | 49.13% | 3 / 64,721 | 570.3 | 0.0258 / 0.0657 |
| supervisor: Coordinate; stop after failed review | 5 | 76,142 | 0.160636 | 0.000000 | 56.42% | 2 / 32,908 | 608.2 | 0.0277 / 0.0647 |

Shared run: 400.98 s; 199 samples; peak RSS 611.0 MiB; mean/peak sampled CPU 0.0308/0.0892 cores; minimum host available RAM 10.31 GiB; swap peak 0 bytes; minimum Work free space 336.37 GiB.

## unseen-glm53-fixed-01

Model: glm-5.3; states: {'settled': 14}; candidate change: 0 rows; finalization: True.

| Actor / actual task | Requests | Known tokens | Exposure CNY | Reserved CNY | Cache, known input | Peak RPM / TPM | Peak RSS MiB | Mean / peak CPU cores |
| - | -: | -: | -: | -: | -: | -: | -: | -: |
| author-2: design | 3 | 40,128 | 0.346544 | 0.000000 | 64.24% | 3 / 40,128 | 587.7 | 0.0227 / 0.0515 |
| reviewer-1: analyze | 2 | 19,755 | 0.177660 | 0.000000 | 49.77% | 2 / 19,755 | 634.6 | 0.0467 / 0.1071 |
| reviewer-3: review | 3 | 50,956 | 0.431588 | 0.000000 | 66.11% | 3 / 50,956 | 635.2 | 0.0224 / 0.0500 |
| supervisor: Coordinate and finalize reviewed retention | 6 | 103,456 | 0.844488 | 0.000000 | 68.79% | 3 / 61,633 | 627.0 | 0.0184 / 0.0649 |

Shared run: 163.06 s; 81 samples; peak RSS 635.2 MiB; mean/peak sampled CPU 0.0271/0.1071 cores; minimum host available RAM 10.32 GiB; swap peak 0 bytes; minimum Work free space 336.35 GiB.

## unseen-glm53-adaptive-02

Model: glm-5.3; states: {'settled': 17}; candidate change: 0 rows; finalization: True.

| Actor / actual task | Requests | Known tokens | Exposure CNY | Reserved CNY | Cache, known input | Peak RPM / TPM | Peak RSS MiB | Mean / peak CPU cores |
| - | -: | -: | -: | -: | -: | -: | -: | -: |
| author-2: design | 4 | 60,521 | 0.539308 | 0.000000 | 71.35% | 4 / 60,521 | 563.9 | 0.0353 / 0.1094 |
| reviewer-1: analyze | 3 | 33,946 | 0.327588 | 0.000000 | 65.76% | 3 / 33,946 | 594.3 | 0.0355 / 0.0655 |
| reviewer-3: review | 2 | 37,246 | 0.316048 | 0.000000 | 51.07% | 2 / 37,246 | 571.7 | 0.0336 / 0.0722 |
| supervisor: Coordinate and finalize reviewed retention | 8 | 162,308 | 1.336764 | 0.000000 | 77.65% | 4 / 117,597 | 604.8 | 0.0238 / 0.1052 |

Shared run: 209.46 s; 104 samples; peak RSS 604.8 MiB; mean/peak sampled CPU 0.0336/0.1810 cores; minimum host available RAM 7.64 GiB; swap peak 0 bytes; minimum Work free space 336.35 GiB.

## unseen-glm53-adaptive-03

Model: glm-5.3; states: {'settled': 9, 'unknown': 1}; candidate change: 0 rows; finalization: False.

| Actor / actual task | Requests | Known tokens | Exposure CNY | Reserved CNY | Cache, known input | Peak RPM / TPM | Peak RSS MiB | Mean / peak CPU cores |
| - | -: | -: | -: | -: | -: | -: | -: | -: |
| author-2: design | 3 | 41,173 | 0.348284 | 0.000000 | 65.07% | 3 / 41,173 | 554.9 | 0.0154 / 0.0333 |
| reviewer-1: analyze | 2 | 20,915 | 0.198080 | 0.000000 | 52.19% | 2 / 20,915 | 585.3 | 0.0253 / 0.0950 |
| supervisor: Coordinate analysis/design; timeout before review | 5 | 42,917 | 0.357276 | 8.847360 | 54.57% | 2 / 33,362 | 599.5 | 0.0081 / 0.0698 |

Shared run: 1037.82 s; 515 samples; peak RSS 599.5 MiB; mean/peak sampled CPU 0.0097/0.0950 cores; minimum host available RAM 10.20 GiB; swap peak 0 bytes; minimum Work free space 336.30 GiB.
