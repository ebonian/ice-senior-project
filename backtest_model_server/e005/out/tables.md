## Eligibility / screen

| pool | family | fee | screen | median swaps/day | LP fee share |
|---|---|---:|---|---:|---:|
| weth_usdc_0p05 | control | 0.05% | RACED (control, e003 data) | 28857 | 0.7500 |
| weth_usdc_0p30 | F1 | 0.30% | RACED | 2055.0 | 0.8333 |
| wsteth_weth_0p01 | F3 | 0.01% | RACED | 171.0 | 0.7500 |
| weeth_weth_0p01 | F3 | 0.01% | INELIGIBLE-thin | 43.0 | 0.7500 |
| wbtc_weth_0p05 | F2 | 0.05% | NOT-FETCHED | — | 0.7500 |
| wbtc_weth_0p30 | F2 | 0.30% | NOT-FETCHED | — | 0.8333 |
| arb_weth_0p05 | F4 | 0.05% | NOT-FETCHED | — | 0.7500 |
| arb_weth_0p30 | F4 | 0.30% | NOT-FETCHED | — | 0.8333 |
| pendle_weth_0p05 | F4-discovered | 0.05% | NOT-FETCHED | — | 0.7500 |
| link_weth_0p05 | F4-discovered | 0.05% | NOT-FETCHED | — | 0.7500 |
| link_weth_0p05 | F4-shortlist | 0.05% | SAMPLED-NOT-CHOSEN | 1078 | — |
| link_weth_0p30 | F4-shortlist | 0.30% | SAMPLED-NOT-CHOSEN | 183 | — |
| link_usdc_0p05 | F4-shortlist | 0.05% | SAMPLED-NOT-CHOSEN | 0 | — |
| link_usdc_0p30 | F4-shortlist | 0.30% | SAMPLED-NOT-CHOSEN | 124 | — |
| uni_weth_0p05 | F4-shortlist | 0.05% | SAMPLED-NOT-CHOSEN | 57 | — |
| uni_weth_0p30 | F4-shortlist | 0.30% | SAMPLED-NOT-CHOSEN | 312 | — |
| uni_usdc_0p05 | F4-shortlist | 0.05% | SAMPLED-NOT-CHOSEN | 0 | — |
| uni_usdc_0p30 | F4-shortlist | 0.30% | SAMPLED-NOT-CHOSEN | 359 | — |
| gmx_weth_0p05 | F4-shortlist | 0.05% | SAMPLED-NOT-CHOSEN | 2 | — |
| gmx_weth_0p30 | F4-shortlist | 0.30% | SAMPLED-NOT-CHOSEN | 222 | — |
| gmx_usdc_0p05 | F4-shortlist | 0.05% | SAMPLED-NOT-CHOSEN | 0 | — |
| gmx_usdc_0p30 | F4-shortlist | 0.30% | SAMPLED-NOT-CHOSEN | 197 | — |
| pendle_weth_0p05 | F4-shortlist | 0.05% | SAMPLED-NOT-CHOSEN | 2933 | — |
| pendle_weth_0p30 | F4-shortlist | 0.30% | SAMPLED-NOT-CHOSEN | 724 | — |
| pendle_usdc_0p05 | F4-shortlist | 0.05% | SAMPLED-NOT-CHOSEN | 0 | — |
| pendle_usdc_0p30 | F4-shortlist | 0.30% | SAMPLED-NOT-CHOSEN | 707 | — |
| crv_weth_0p05 | F4-shortlist | 0.05% | SAMPLED-NOT-CHOSEN | 0 | — |
| crv_weth_0p30 | F4-shortlist | 0.30% | SAMPLED-NOT-CHOSEN | 384 | — |
| crv_usdc_0p05 | F4-shortlist | 0.05% | SAMPLED-NOT-CHOSEN | 0 | — |
| crv_usdc_0p30 | F4-shortlist | 0.30% | SAMPLED-NOT-CHOSEN | 41 | — |
| aave_weth_0p05 | F4-shortlist | 0.05% | SAMPLED-NOT-CHOSEN | 121 | — |
| aave_weth_0p30 | F4-shortlist | 0.30% | SAMPLED-NOT-CHOSEN | 225 | — |
| aave_usdc_0p05 | F4-shortlist | 0.05% | SAMPLED-NOT-CHOSEN | 0 | — |
| aave_usdc_0p30 | F4-shortlist | 0.30% | SAMPLED-NOT-CHOSEN | 338 | — |
| ldo_weth_0p05 | F4-shortlist | 0.05% | SAMPLED-NOT-CHOSEN | 0 | — |
| ldo_weth_0p30 | F4-shortlist | 0.30% | SAMPLED-NOT-CHOSEN | 156 | — |
| ldo_usdc_0p05 | F4-shortlist | 0.05% | SAMPLED-NOT-CHOSEN | 0 | — |
| ldo_usdc_0p30 | F4-shortlist | 0.30% | SAMPLED-NOT-CHOSEN | 147 | — |

## Per-pool per-arm (lag1h_rh1h, central envelope, $/day)

| pool | arm | ±% | fees | gamma | f/g | worst-mo f/g | on-chain | HPL | funding | net central | breakeven× | pool share | rec |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| weeth_weth_0p01 | arm_0.1pct | 0.10 | +0.065 | -0.163 | **0.396** | 0.150 | -0.075 | -0.009 | +0.204 | **+0.022** | 0.66× | 21.824% | 26 |
| weeth_weth_0p01 | arm_0.2pct | 0.20 | +0.055 | -0.087 | **0.628** | 0.198 | -0.025 | -0.008 | +0.214 | **+0.148** | -1.71× | 16.772% | 6 |
| weeth_weth_0p01 | arm_0.5pct | 0.50 | +0.042 | -0.072 | **0.584** | 0.147 | -0.019 | -0.008 | +0.207 | **+0.151** | -2.62× | 12.348% | 3 |
| weeth_weth_0p01 | arm_2pct | 2.00 | +0.022 | +0.038 | **0.568** | 0.357 | -0.010 | -0.006 | +0.178 | **+0.222** | -9.30× | 6.313% | 0 |
| weeth_weth_0p01 | arm_8.3pct | 8.30 | +0.010 | +0.049 | **0.197** | 0.116 | -0.010 | -0.006 | +0.178 | **+0.221** | -21.79× | 2.839% | 0 |
| weth_usdc_0p05 | arm_0.1pct | 0.10 | +25.962 | -34.628 | **0.750** | 0.685 | -5.161 | -2.717 | +0.064 | **-16.481** | 1.63× | 0.704% | 2115 |
| weth_usdc_0p05 | arm_0.2pct | 0.20 | +22.730 | -31.266 | **0.727** | 0.690 | -3.887 | -2.391 | +0.083 | **-14.731** | 1.65× | 0.358% | 1551 |
| weth_usdc_0p05 | arm_0.5pct | 0.50 | +15.767 | -21.305 | **0.740** | 0.704 | -1.813 | -1.995 | +0.093 | **-9.253** | 1.59× | 0.149% | 715 |
| weth_usdc_0p05 | arm_2pct | 2.02 | +5.967 | -8.179 | **0.730** | 0.680 | -0.302 | -0.744 | +0.094 | **-3.164** | 1.53× | 0.039% | 119 |
| weth_usdc_0p05 | arm_8.3pct | 8.33 | +1.723 | -2.440 | **0.706** | 0.606 | -0.032 | -0.193 | +0.099 | **-0.844** | 1.49× | 0.010% | 11 |
| weth_usdc_0p30 | arm_0.1pct_0.2pct_0.5pct | 0.60 | +14.997 | -17.444 | **0.860** | 0.792 | -1.554 | -1.334 | +0.079 | **-5.255** | 1.35× | 0.838% | 618 |
| weth_usdc_0p30 | arm_2pct | 1.82 | +7.446 | -8.610 | **0.865** | 0.787 | -0.378 | -0.664 | +0.091 | **-2.115** | 1.28× | 0.289% | 146 |
| weth_usdc_0p30 | arm_8.3pct | 8.11 | +2.031 | -2.369 | **0.857** | 0.770 | -0.032 | -0.172 | +0.083 | **-0.458** | 1.23× | 0.069% | 11 |
| wsteth_weth_0p01 | arm_0.1pct | 0.10 | +0.057 | +0.002 | **36.184** | 1.092 | -0.036 | -0.009 | +0.210 | **+0.223** | -2.94× | 0.279% | 10 |
| wsteth_weth_0p01 | arm_0.2pct | 0.20 | +0.068 | +0.005 | **13.975** | 0.744 | -0.024 | -0.008 | +0.207 | **+0.248** | -2.63× | 0.329% | 5 |
| wsteth_weth_0p01 | arm_0.5pct | 0.50 | +0.059 | +0.023 | **2.611** | 0.270 | -0.014 | -0.008 | +0.212 | **+0.271** | -3.62× | 0.270% | 1 |
| wsteth_weth_0p01 | arm_2pct | 2.00 | +0.036 | +0.033 | **1.077** | 0.048 | -0.010 | -0.006 | +0.178 | **+0.231** | -5.45× | 0.163% | 0 |
| wsteth_weth_0p01 | arm_8.3pct | 8.30 | +0.025 | +0.041 | **0.622** | 0.011 | -0.010 | -0.006 | +0.178 | **+0.228** | -7.98× | 0.114% | 0 |

## Monthly fees/gamma (best arm per pool)

| pool | best arm | 2026-05 | 2026-06 | 2026-07 | 2026-08 | full |
|---|---|---:|---:|---:|---:|---:|
| weeth_weth_0p01 | arm_0.2pct | 0.198 | 6.773 | 1.923 | 1.774 | **0.628** |
| weth_usdc_0p05 | arm_0.1pct | 0.731 | 0.685 | 0.856 | 0.773 | **0.750** |
| weth_usdc_0p30 | arm_2pct | 0.827 | 0.787 | 1.146 | 0.815 | **0.865** |
| wsteth_weth_0p01 | arm_0.1pct | 1.337 | 7.974 | 1.092 | 2.655 | **36.184** |

## Volume persistence (gate e)

| pool | 05 | 06 | 07 | 08 | worst/peak raw | worst/peak per-day | pass |
|---|---:|---:|---:|---:|---:|---:|---|
| weeth_weth_0p01 | 1,274 | 2,419 | 1,442 | 1,178 | 0.49 | 0.51 | PASS |
| weth_usdc_0p05 | 575,631 | 1,405,733 | 783,198 | 669,551 | 0.41 | 0.40 | PASS |
| weth_usdc_0p30 | 50,798 | 127,774 | 71,453 | 56,829 | 0.40 | 0.38 | PASS |
| wsteth_weth_0p01 | 5,518 | 7,189 | 5,925 | 4,493 | 0.62 | 0.69 | PASS |

## Verdict: **INCONCLUSIVE**  (max eligible fees/gamma 36.184)

- watchlist: wsteth_weth_0p01 arm_0.1pct f/g 36.184, failed ['c_net_ge_target']
- watchlist: wsteth_weth_0p01 arm_0.2pct f/g 13.975, failed ['b_monthly_fg_gt_1', 'c_net_ge_target']
- watchlist: wsteth_weth_0p01 arm_0.5pct f/g 2.611, failed ['b_monthly_fg_gt_1', 'c_net_ge_target']
- watchlist: wsteth_weth_0p01 arm_2pct f/g 1.077, failed ['a_fg_ge_1p5', 'b_monthly_fg_gt_1', 'c_net_ge_target']
