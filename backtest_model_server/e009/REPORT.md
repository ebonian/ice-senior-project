# E009 — the funding-persistence test: SUPPORTED. The carry is a property of the market, not of E005's window — but it is compressing

**Verdict (mechanical, [`out/results.json`](out/results.json) §decision):
SUPPORTED.** The central estimator — trailing-12-month expected package net
at E005's frozen package — is **+$0.186/day**, above the pre-registered
+$0.15/day bar, and every pre-registered downside bound holds over the full
HL hourly era: worst rolling-30d **−$0.086/day** (bound −$0.50), longest
negative-carry run **11 days** (bound 21), zero disjoint runs ≥ 14 days,
trailing-12m negative-day fraction **13.2%** (bound 35%), Binance
cross-venue sign agreement **83.3%** (guard 60%). Verdict clauses and
thresholds are exactly those pre-registered in
[`E009-funding-persistence.md`](../../loop/experiments/E009-funding-persistence.md)
from the [M003](../../discovery/memos/M003-eth-funding-persistence.md)
pre-named estimator set; nothing was added or reweighted after seeing data.

The honest headline behind the verdict: **E005's +$0.2095/day funding leg is
representative, and lean.** The long history was *richer* (full-era mean
+$0.408/day), the recent regime is poorer (trailing-12m carry +$0.173/day),
and the half-year trend is compression toward Hyperliquid's structural
interest floor — at which ~half of all hours already sit.

All figures at the frozen package: $1,015 flat short notional, carry =
Σ rate_h × $1,015, package net = carry + E005's non-funding residual
+$0.0138/day. Data: HL `fundingHistory` ETH, hourly era 2023-07-01 →
2026-09-02 (27,833 rows, 3 missing hours); Binance ETHUSDT 8h funding
2020-03 → 2026-09 (descriptive proxy); committed under [`data/`](data/).

## 1 — The pre-named tests

### A · Central estimator (decides SUPPORTED/REFUTED)

| Window | carry $/day | package $/day | APR on $1,420 |
|---|---:|---:|---:|
| Trailing 12m (2025-09-03→2026-09-02) — **central** | +0.173 | **+0.186** | 4.79% |
| E005 window (2026-05-01→08-28), committed replay | +0.210 | +0.223 | 5.74% |
| Full HL hourly era (2023-07-01→2026-09-02, 1,160 d) | +0.394 | +0.408 | 10.49% |

### B · Regime dependence

Half-year package $/day: 2023H2 **+0.615** · 2024H1 **+0.766** · 2024H2
**+0.490** · 2025H1 **+0.184** · 2025H2 **+0.318** · 2026H1 **+0.122** ·
2026H2-to-date **+0.269**. The compression from the 2024 bull to 2025–26 is
the dominant structure; 2026H1 alone would have missed the SUPPORTED bar.

ETH-trend conditioning (trailing-30d Binance return sign, no lookahead):
up-regime **+$0.624/day**, down-regime **+$0.204/day**, down-share 51.5% of
days. **The carry stays positive in down-trends on average** — the
persistence-friendly half of the regime story; the compression trend is the
unfriendly half.

### C · Worst stretches (carry the REFUTED bounds)

| Statistic | Value | Bound | Where |
|---|---:|---:|---|
| Worst rolling-30d package net | **−$0.086/day** | ≥ −$0.50 | window starting 2025-03-30 |
| Worst rolling-90d package net | **+$0.052/day** | (reported) | window starting 2026-01-31 |
| Longest negative-carry run | **11 days** | ≤ 21 | — |
| Disjoint runs ≥ 14 days | **0** | < 2 | — |

Even the worst 90-day stretch in 38 months stayed net positive.

### D · Mean-reversion structure

Daily carry AR(1) φ = **0.807**, half-life **3.2 days**; negative runs die
fast (top lengths 11, 8, 5, 5, 5). Negative-hour fraction 13.8% full-era,
ranging 3.6%–28.2% by quarter (worst: 2025Q2 27.9%, 2026Q2 28.2%). This is
the OU-with-jumps picture from the literature (M003 §2.2): funding
mean-reverts in days, not quarters.

### E · The structural pin (the mechanism finding)

**49.4% of all hourly-era hours — 52.6% in the trailing 12m — print exactly
1.25e-5/h**, HL's clamped interest component (0.01%/8h). The pin contributes
**38.1% of all carry**. Zero hours ever hit the ±4%/h cap. A fully pinned
market pays this package $0.318/day; the trailing-12m actual ($0.186) sits
at 59% of that, dragged by negative-premium hours. So the carry's floor is
substantially **an HL protocol parameter, not market sentiment** — durable
against sentiment, exposed to a one-line governance change (unhedgeable;
monitorable).

### F · Cross-venue corroboration (descriptive)

HL vs Binance on 3,479 overlapping 8h sums: sign agreement **83.3%**,
Pearson r **0.672** — the carry is market-wide, not HL-idiosyncratic.
Binance's longer archive (2020-03→) at the same frozen notional: full-period
package +$0.376/day, longest negative run 15 days, **worst rolling-30d
−$0.582/day starting 2022-08-26** — the Merge episode. That stretch would
have **breached bound C1**. It sits outside HL's existence, which is
precisely the pre-stated coverage limit: *HL's history contains no full bear
market* (E009 prereg §Data). The bounds are certified for the observed era,
not for a 2022 replay.

### L · LP-leg sketch (companion, non-deciding)

[`out/lp_leg_sketch.json`](out/lp_leg_sketch.json). Volume-proxy fees
(month volume × 0.01% × 0.75 LP share × E005's implied 0.279% share),
validated against E005's four committed fee cells first — the proxy lands
within **0.75×–1.64×** of the fee-engine truth (share and in-range drift),
so it is an order-of-magnitude instrument only. Extension, Jan–Apr 2026:
volumes $15.8M / $13.7M / $12.4M / $44.5M per month (vs $7–11M measured
May–Aug), proxy fees $2.6–$9.3/month vs committed $1.0–$3.1. **The fee flow
looks stable-to-better going back — nothing suggests the +$0.0138/day
residual is a lucky-window artifact — but a proxy with ±60% monthly error
cannot upgrade that to a measurement.**

## 2 — Validation

- **V1 (data identity):** all **2,856/2,856** hours of E005's committed
  funding CSV present in the fresh fetch, max |Δrate| = **0.0** — today's
  API serves bit-for-bit the history E005 recorded.
- **V2 (figure reproduction):** flat-notional recompute over the E005 window
  = **$0.20054/day** vs committed replay **$0.20952/day** = **−4.28%**,
  within the ±5% gate and equal to the calibration disclosed *before* the
  run (M003 §1: the gap is the replay's marked-notional re-mint
  bookkeeping).
- **Coverage census:** 3 missing hours in 27,836 (0.01%); worst 90-day span
  0.09%. **Deviation (documented):** HL's 2023-05-12→06-30 records are an
  8h-interval/transition era (records at 00/08/16 UTC); the hourly-era
  analysis coverage starts **2023-07-01**. The fetched CSV keeps the early
  rows untouched; only mechanism-level hourly statistics required the trim.
- **No-lookahead:** 931 truncated rolling-30d windows and the regime labels
  reproduce their full-series values exactly.
- **Determinism:** `analyze.run()` twice → byte-identical JSON.
- Full log: `test_e009_contracts.py`, 6/6 PASS.

## 3 — Reproducing

```bash
nix develop .#gate1 -c python backtest_model_server/e009/fetch.py    # cached; delete data/ to re-fetch
nix develop .#gate1 -c python backtest_model_server/e009/test_e009_contracts.py
nix develop .#gate1 -c python backtest_model_server/e009/analyze.py
nix develop .#gate1 -c python backtest_model_server/e009/lp_leg_sketch.py  # companion L, resumable
```

Fetch boundaries are frozen (END 2026-09-03T00:00Z), all data committed
(~2.7 MB), analysis is pure-stdlib deterministic Python.

## 4 — What this does not answer

1. **A 2022-style bear regime.** The one clean historical episode that
   breaks bound C1 (Merge, −$0.58/day for a month, shorts paying) predates
   HL. The K8 margin/liquidation design should budget for sustained
   ≥ −$0.60/day carry reversal as its stress case, from the Binance record.
2. **Where compression stops.** Half-year means fell 6× from 2024H1 to
   2026H1. The equilibrium literature (M003 §2.3) says carry compresses
   toward financing cost as capital crowds in; the pin decomposition says
   ~$0.30/day is HL's parameter floor *if premiums stay neutral*. Whether
   next year's central lands at $0.12 or $0.27 is genuinely open; this
   experiment certifies the past, not the trend's asymptote.
3. **The rest of B2's prerequisites.** Per-venue perp cost calibration and
   the bot-side K8 margin/liquidation pass are untouched. The LP-leg
   residual is sketched, not measured, outside E005's window.
4. **HL governance risk.** 38% of carry rides one protocol constant
   (interest 0.00125%/h) and the funding-interval convention — both changed
   once already (the 2023-06 8h→1h transition this run had to trim around).
