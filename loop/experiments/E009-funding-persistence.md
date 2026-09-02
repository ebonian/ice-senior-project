---
id: E009
family: new: H-carry
date: 2026-09-03
verdict: RUNNING
---

# E009 — The wstETH package's funding carry is representative, not a one-window artifact

## Pre-registration (write BEFORE running)

**Hypothesis** — The +$0.2095/day funding-carry leg that E005 measured for the
wstETH/WETH 0.01% + HL ETH-short package over 2026-05-01→08-28 is
representative of the rate's longer history: the long-window expected package
net stays ≥ +$0.15/day central, and no historical stretch violates the
downside bounds below. This is a **measurement** experiment on pre-named
estimators ([M003 §3](../../discovery/memos/M003-eth-funding-persistence.md),
tests A–F + L) — no policy, no tuning, no selection.

**The one variable** — the funding-history window: E005's 119 days → the
longest available HL ETH-PERP history. Everything else frozen at E005's
committed package: flat **$1,015** short notional, carry_$ = Σ rate_h × 1015
over the window ÷ window days; package net = carry + the frozen non-funding
residual **+$0.0138/day** (E005 `out/wsteth_weth_0p01/lag1h_rh1h/results.json`
arm_0.1pct central: net $0.223333/day, funding $0.209519/day). No
reinterpretation of the cost model; no new cost lines.

**Data (coverage stated honestly)** — HL `fundingHistory` for ETH reaches
back to **2023-05-12T00:00Z** (probed 2026-09-03, coverage timestamps only —
disclosed in M003 §1) and is current through fetch time: ~40 months of hourly
rows, comfortably past the ≥ 12-month target, so no proxy is needed for the
verdict. Pre-named descriptive supplements (non-deciding): Binance
USDT-margined ETHUSDT 8h funding from 2020-03 (covers Mar-2020 / May-2021 /
Sep-2022 episodes HL cannot see) and Binance ETH/USDT daily klines for regime
classification. Known coverage limit, stated up front: **HL's history
contains no full bear market** (starts mid-2023); the 2022-style
sustained-negative regime is observable only through the Binance proxy and
cannot enter the verdict clauses.

**Validity gate (blocking contract — STOP on failure, report, do not
proceed to the verdict):**

- **V1 (data identity).** Join the freshly fetched HL series to E005's
  committed `e005/data/funding/hl_funding_eth_hourly.csv` on the hour:
  ≥ 99.9% of the 2,856 committed hours must be present with
  max |Δrate| ≤ 1e-12.
- **V2 (figure reproduction).** Recompute the funding-carry leg over
  2026-05-01T00:00→2026-08-28T00:00 UTC from the fresh data as
  Σ rate_h × $1,015 ÷ 119.0; it must land within **±5%** of E005's committed
  **$0.209519/day**. Calibration disclosed before running (M003 §1): on the
  committed CSV this flat-notional recompute gives $0.20055/day (−4.28%) —
  the gap is the replay's marked-notional re-mint bookkeeping. The gate
  therefore primarily verifies that today's API returns the same history
  E005 recorded and that the frozen flat-notional model stays inside
  tolerance; a fresh-data value outside ±5% means the API's history has
  been revised or the model is wrong → STOP.

**Definitions (fixed now):** daily carry = Σ of that UTC day's hourly
accruals (rate_h × 1015); daily package net = daily carry + $0.0138;
a negative-carry run = maximal streak of consecutive UTC days with package
net < 0; rolling-30d (90d) series = mean daily package net over every fully
contained 30- (90-) consecutive-day window, step 1 day, using only data
inside the window (no-lookahead contract-tested); trailing-12m = the 365
UTC days ending at the last complete UTC day fetched; **central estimator =
trailing-12m mean daily package net** (M003 test A). Full-history and
regime-conditional means (tests B), stretch statistics (C), run-length and
AR(1) structure (D), clamp-pin decomposition (E, pin = |rate − 1.25e-5| ≤
1e-9), and Binance cross-venue context (F) are computed exactly as pre-named
in M003 §3.

**Decision rule** —

- **SUPPORTED**: central (trailing-12m) expected package net ≥ **+$0.15/day**
  AND all downside bounds hold over the full HL coverage:
  (C1) worst rolling-30d package net ≥ **−$0.50/day**;
  (C2) longest negative-carry run ≤ **21 days**;
  (D1) fewer than 2 disjoint negative-carry runs ≥ 14 days;
  (D2) trailing-12m negative-package-day fraction ≤ **35%**.
- **REFUTED**: central < **+$0.10/day**, OR C1 violated, OR C2 violated.
- **INCONCLUSIVE**: anything else (central in [0.10, 0.15), or only D1/D2
  fail, or the cross-venue guard fires: HL-vs-Binance funding sign agreement
  < 60% on the 8h-aggregated overlap caps the verdict at INCONCLUSIVE —
  a venue-trust question the HL-only series cannot settle). Report what
  would disambiguate.
- Tests B and E cannot change the verdict; they are the mechanism report
  (regime dependence; structural pin vs premium share). Test F and companion
  L (LP-leg sketch) are descriptive context.

**Abort criteria** —

- HL fetch incomplete: > 2% of expected hours missing in any 90-day span of
  claimed coverage → report as data failure, do not judge.
- Validity gate V1/V2 failure → STOP and report the discrepancy.
- Disk: < 500 MB free at any checkpoint → stop fetching, keep partial
  committed artifacts, report. (Total expected data ≈ 2–3 MB of CSV; this
  should never fire.)
- Companion L only: if extending the wstETH/WETH swap history (target
  2026-01→04 via the e005 fetch machinery) projects > 45 min of wall time or
  any disk risk, drop L to its fallback — the four committed E005 monthly
  cells — and say so. L's failure cannot abort E009.

**Method** — artifacts under `backtest_model_server/e009/`: `fetch.py`
(recipe: HL `fundingHistory` paginated at 500 rows, Binance `fundingRate` +
daily klines; all committed as CSVs), `analyze.py` (all tests A–F from the
committed CSVs only; deterministic, no RNG), `test_e009_contracts.py`
(V1, V2, coverage/gap census, no-lookahead in rolling stats, determinism:
byte-identical `out/results.json` on re-run), checkpointed JSONs under
`out/`. Python via `nix develop .#gate1`. Everything foreground,
resumable.

## Result

_(pending)_

## Verdict

RUNNING

## Critique

_(pending)_

## What this changes

_(pending)_
