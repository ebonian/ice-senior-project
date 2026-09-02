# E006 tables

Window 2026-05-01 → 2026-08-28 (119.00 days, 3,434,113 swaps). Cost model `gate1-2026-08-29`, envelope `e003-2026-08-29`. Target +$0.389/day.

## Frontier — oracle $/day by width (central envelope)

| Arm | ±% | stage-1 UB opt | **stage-1 UB central** | stage-1 UB pess | **stage-2 exact central** | exact opt | exact pess | held % | streaks | capture needed |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| w4 | ±0.200% | +9.193 | **+8.845** | +7.839 | **+6.058** | +6.840 | +3.235 | 57.9% | 435 | 6% |
| w10 | ±0.501% | +6.031 | **+5.734** | +4.832 | **+3.718** | +4.378 | +1.338 | 67.5% | 292 | 10% |
| w40 | ±2.020% | +1.409 | **+1.294** | +0.989 | **+0.807** | +1.052 | -0.074 | 68.0% | 97 | 48% |
| w160 | ±8.328% | +0.161 | **+0.135** | +0.078 | **+0.065** | +0.116 | -0.121 | 49.2% | 20 | 600% |

`capture needed` = target ÷ stage-2 exact oracle: the fraction of the realistic ceiling a causal model must capture to reach +$0.389/day.

## Stage-1 payoff decomposition (all hours, $ over the window)

| Arm | Σ fees | Σ funding | Σ gamma | Σ payoff | UB central $ | stage-2 exact $ | retention |
|---|---:|---:|---:|---:|---:|---:|---:|
| w4 | +2787 | +8.89 | -3741 | -945 | +1052.61 | +720.92 | 68.5% |
| w10 | +1999 | +10.72 | -2729 | -719 | +682.29 | +442.46 | 64.8% |
| w40 | +767 | +11.63 | -1073 | -294 | +154.02 | +96.09 | 62.4% |
| w160 | +209 | +11.86 | -293 | -72 | +16.06 | +7.71 | 48.0% |

## Descriptive — NOT part of the verdict (best arm w4)

Held 1654/2856 hours (57.9%) in 435 streaks — mean 3.8h, median 3h, p90 8h, max 46h.

| Month | hours | held | held % |
|---|---:|---:|---:|
| 2026-05 | 744 | 435 | 58.5% |
| 2026-06 | 720 | 403 | 56.0% |
| 2026-07 | 744 | 436 | 58.6% |
| 2026-08 | 648 | 380 | 58.6% |

### Trailing (causal) signals vs oracle membership

| Signal | AUC | held p50 | skipped p50 | held mean | skipped mean |
|---|---:|---:|---:|---:|---:|
| rv_12h | 0.452 | 0.003913 | 0.004246 | 0.004601 | 0.005056 |
| er_12h | 0.526 | 0.2556 | 0.24 | 0.2953 | 0.2774 |
| rv_24h | 0.456 | 0.004338 | 0.004514 | 0.004784 | 0.005223 |
| er_24h | 0.501 | 0.1734 | 0.1777 | 0.2114 | 0.209 |
| rv_48h | 0.466 | 0.004452 | 0.004862 | 0.004987 | 0.005255 |
| er_48h | 0.476 | 0.1255 | 0.1384 | 0.156 | 0.1632 |
| rv_prev_1h | 0.460 | 0.000956 | 0.001046 | 0.001333 | 0.001454 |

### Persistence — autocorrelation, lags 1/3/6/12/24h

| Series | lag 1 | lag 3 | lag 6 | lag 12 | lag 24 |
|---|---:|---:|---:|---:|---:|
| rv_intra_hour | 0.222 | 0.106 | 0.119 | 0.101 | 0.084 |
| er_12h | 0.767 | 0.451 | 0.174 | 0.004 | -0.009 |
| er_24h | 0.881 | 0.712 | 0.533 | 0.289 | 0.038 |
| er_48h | 0.943 | 0.848 | 0.739 | 0.536 | 0.220 |

## Verdict (pre-registered rule)

**SUPPORTED** — stage-2 exact oracle reaches $+6.058/day at w4 (>= +$1.56/day).
