---
id: E007
family: H-timing
date: 2026-09-02
verdict: REFUTED
---

# E007 — A pre-named causal signal captures enough of the timing ceiling to clear the target

## Pre-registration (write BEFORE running)

**Hypothesis** — At least one of the six pre-named causal signals from
[memo M001](../../discovery/memos/M001-short-horizon-vol-signals.md) §5, turned into an
hour-boundary in/out rule with ≤2 tuned parameters, nets **≥ +$0.389/day
central** (the 10%-APR target; 6.4% of E006's +$6.06/day ceiling at ±0.2%,
12.4% of the 6h-coarse ceiling) on ETH/USDC 0.05% through E006's stage-2
exact simulator — including on a held-out month the tuning never saw.

**The one variable** — the in/out gating signal. The policy family is fixed:
signal → threshold rule → in/out decision at hour boundaries, evaluated
exactly as E006 stage 2 evaluates the oracle (fresh mint at streak start,
lag1h_rh1h loop in-streak, burn+flatten at exit, cash outside). Baselines:
`always_in` (E003 lag1h_rh1h committed) and `always_cash` ($0). Everything
else frozen at E003/E006 values: engine `gate1/engine/` and `e003/` untouched,
committed parquets + funding CSV, window 2026-05-01→2026-08-28, cost model
`gate1-2026-08-29`, envelope `e003-2026-08-29` (central for the verdict), LP
notional $1,015. **Widths ±0.2% (w4) and ±0.5% (w10) only** (M001 §6: wider
arms' ceilings are too thin to matter).

**Pre-named candidates** (M001 §5 — the memo's ranked list, frozen; testing
order = table order; every candidate tested is reported, no silent drops):

| # | Signal at boundary t (causal) | Rule | Tuned params (grid) |
|---|---|---|---|
| C1 | EWMA, half-life λ, of past hours' freshly-centered stage-1 payoff (`fees+funding−gamma`, known at each hour's close; last term is hour t−1's) | enter iff ≥ θ | λ ∈ {2,4,8,16,24}h; θ ∈ tune-window deciles P10..P90 |
| C2 | EWMA_λ of log intra-hour swap-stream RV (hours t−1, t−2, …) | enter iff ≤ θ | λ ∈ {2,4,8,16,24}h; θ ∈ deciles |
| C3 | dow×hod cell mean of stage-1 hourly payoff, estimated on the tune window only, shrunk to the global tune-window mean with weight κ: `(n·cell + κ·global)/(n+κ)` | enter iff ≥ θ | κ ∈ {0,8,32}; θ ∈ deciles |
| C4 | Binance ETHUSDT 1m-kline realized vol over the last N minutes before t (sum of squared 1m log closes) | enter iff ≤ θ | N ∈ {15,30,60}; θ ∈ deciles |
| C5 | C2 with per-hour RV replaced by realized bipower variation (swap-to-swap, jump-robust) | enter iff ≤ θ | λ ∈ {2,4,8,16,24}h; θ ∈ deciles |
| C6 | C1 AND C3, with λ and κ inherited from C1/C3's tuned values (not re-tuned) | enter iff C1 ≥ θ₁ and C3 ≥ θ₂ | θ₁, θ₂ ∈ deciles |

M001 §4 pre-emptively cut DVOL (30-day horizon vs a dead 24h-grain ceiling)
and funding-rate dynamics (no hour-scale mechanism). C4's trade-count twin is
also not tested — parameter discipline; it goes to E008 if C4 shows life.

**Overfitting guards** — candidates pre-named above; ≤2 tuned parameters per
candidate, grids pre-registered above; tuning uses **2026-05-01→2026-07-31
only** (tuning objective: stage-2 exact net $/day, central point, on the tune
window); **2026-08 is held out untouched until final judgment** — no August
number is computed before every candidate's parameters are frozen; every
candidate is reported; C6 is its own pre-named candidate with its budget
stated. Signal *values* in August may use trailing pre-August data (EWMAs are
causal); signal *parameters* may not. Threshold grids are deciles of each
signal on the tune window (P10–P90 — 9 values), fixed before any outcome is
seen.

**Decision rule** (stage-2 exact, central envelope, best of w4/w10):

- **SUPPORTED** — some pre-named candidate, parameters frozen from the tune
  window, satisfies ALL of:
  (a) full-window (2026-05-01→08-28) net **≥ +$0.389/day**;
  (b) held-out August (2026-08-01→08-28) net **> $0/day**;
  (c) monthly central net positive in **≥ 3 of 4** months.
- **REFUTED** — no pre-named candidate's full-window central net exceeds
  **$0/day**: the causal-signal route on this pool is closed at these
  families; the operator's venue decision proceeds on E005 + E006 alone.
- **INCONCLUSIVE** — anything between (e.g. positive full-window but below
  target, or target met but August negative): report the best candidate's
  full numbers and state exactly what would disambiguate (more data, one
  named refinement, or a lower-capture venue variant).

Any SUPPORTED verdict must restate the E006-inherited caveat: **adverse
selection/MEV is unmodelled**, the bias is upward and larger for hour-picked
positions than for always-in (E006 §7); no capital moves on this number
(bot ADR 0008).

**Sanity contracts (blocking, in `e007/tests/`)**:

1. `always_in` through E007's evaluator (signal ≡ enter) reproduces E003's
   committed lag1h_rh1h `always_in` float-exact at w4 and w10, all three
   envelope points (the E006 §6 contract, re-asserted on this code path).
2. `always_cash` nets exactly $0 with zero streaks.
3. Accounting identity per simulated streak ≤ 1e-6 (engine ledger gap).
4. Causality: for a sample of boundaries, each signal recomputed from data
   truncated at the boundary equals the full-series value (no lookahead).
5. Tuning isolation: the tuning routine receives only rows with
   `hour < 2026-08-01`; asserted in code.

**Abort criteria** — if total attended runtime projects beyond ~6h, cut
candidates from the bottom of the ranking (C6 first, then C5, then C4) and
say so in the report. If the Binance fetch fails or is rate-limited beyond
one retry pass, C4 is recorded as NOT TESTED (fetch failure) — not silently
dropped. Any signal redefinition mid-run is a new experiment (E008), not an
edit here.

**Method** — new code under `backtest_model_server/e007/` only (`gate1/`,
`e003/`, `e005/`, `e006/` untouched); reuses `e006/exact.py`'s
`simulate_streak` (which wraps E003's `run_arm`) for all policy evaluation;
per-streak simulation results cached on disk keyed (width, start, end) —
identical streaks across thresholds share one simulation; cache is an
optimization only (contract 1 runs uncached). Binance 1m klines for the
window are fetched once, reduced to (open_time, close, n_trades), and
committed under `e007/data/` (gzipped CSV) with the fetch script. Artifacts
land in `e007/out/`: per-candidate tuning tables, final per-candidate
results JSON, report tables. No RNG anywhere; results are a pure function of
committed inputs. Descriptive add-on (not the verdict): each tuned signal's
AUC for E006's oracle-held hours, full window.

## Result

Run 2026-09-02 on E003's committed data plus the committed Binance 1m
reduction; engine, cost model, envelope frozen as pre-registered; all 27
blocking contracts pass. Full report:
[`backtest_model_server/e007/REPORT.md`](../../backtest_model_server/e007/REPORT.md);
artifacts under `backtest_model_server/e007/out/`.

Every one of the six pre-named candidates, tuned on 2026-05→07 per the
registered grids, is **negative** over the full window at both arms, at all
three envelope points, and on held-out August. $/day central, full window /
held-out August:

| Cand (tuned) | w4 full | w4 Aug | w10 full | w10 Aug | months+ (best arm) | AUC |
|---|---:|---:|---:|---:|---:|---:|
| C1 payoff-EWMA (λ=24h) | −1.192 | −0.806 | −0.858 | −0.967 | 0/4 | 0.54–0.56 |
| C2 log-RV-EWMA (λ=4h) | −1.093 | −2.953 | −0.600 | −1.647 | 0/4 | 0.54–0.57 |
| C3 seasonal dow×hod (κ=0) | −0.792 | −2.369 | −1.010 | −2.112 | 2/4 | **0.59–0.62** |
| C4 Binance 60m RV | −1.359 | −2.499 | −1.178 | −1.777 | 0/4 | 0.56–0.60 |
| C5 bipower-EWMA (λ=4h) | −1.000 | −2.716 | −0.560 | −1.530 | 0/4 | 0.55–0.58 |
| C6 C1∧C3 | −0.140 | −0.196 | **−0.074** | −0.127 | 0/4 | 0.59 |

- **0 of 540 tune-window configurations were positive** — every candidate's
  optimum sat at its grid's most conservative decile, reaching for
  `always_cash`. The REFUTED clause would have fired on the tune window alone.
- Sanity: `always_in` reproduces E003 float-exact; `always_cash` = $0; the
  E006 oracle mask through the same evaluator returns +$6.058/day (w4) and
  +$3.718/day (w10) — the machinery rewards a good mask when given one.
- Mechanism (report §2): two clean failure modes. C1/C2/C5 hold 4–5h streaks
  but select at AUC 0.54–0.57 (wrong hours, smoothly). C3 selects genuinely
  good hours — mean stage-1 payoff +$0.42/h, 72% oracle-overlap, AUC 0.616,
  clear of E006's falsified 0.45–0.53 band — but as 272 median-1-hour
  fragments whose ~$0.76 round-trip switch costs and stage-2 accounting erase
  the edge. The oracle's value is *contiguity* (hours chosen jointly with
  switch costs), which no per-hour threshold rule can buy.

## Verdict

**REFUTED** — the pre-registered clause fired: no pre-named candidate's
full-window central net exceeds $0/day (best: C6 at ±0.5%, −$0.074/day).
The E006 ceiling stands; the M001 candidate set does not capture it through
the fixed threshold-rule family.

## Critique

1. **Proxy or goal?** Goal — net $/day through the same stage-2 exact
   simulator and frozen cost stack as E003/E006; tuning objective and verdict
   metric were the same quantity.
2. **Would it survive Gate 2?** The negative results would (costs there are
   the same or worse — adverse selection/MEV would deepen every number). No
   positive claim is being made that needs Gate 2.
3. **Environment faithful enough?** For a refutation, yes: every unmodelled
   channel (MEV, adverse selection) points further negative. Four months of
   one market remains the window caveat, but all four months agree.
4. **Exactly one variable?** Yes — the gating signal; policy family, engine,
   data, costs, envelope, capital all bit-frozen (verified by contract).
5. **Symptom-fix of the previous iteration?** No — E007 was E006's
   pre-registered SUPPORTED route, its candidates pre-named in M001 before
   any outcome was seen.

## What this changes

- **The conditional fourth venue option dies as specified.** E006 offered:
  stay on ETH/USDC 0.05% iff E007 finds a realizable filter clearing ~6–10%
  capture. It did not — the operator's venue decision reverts to E005's
  three-way call (accept 5–7% carry venue / re-screen elsewhere / judge the
  family). The loop remains ESCALATED on that question; nothing here
  un-blocks G2.
- **H-timing after E006+E007+M001**: ceiling +$6.06/day real; daily-scale
  gating dead even with foresight (M001 §2); hour-scale threshold rules dead
  as a family (this run); the one measured-but-untested residual is
  streak-aware rules (hysteresis/dwell/DP-on-forecast) on a C3-quality
  selector — a new policy family, E008-sized, only worth staging if the
  operator keeps the venue alive.
- **Recorded for successors**: the dow×hod calendar at AUC 0.62 is the best
  causal selector measured on this pool; selection quality and contiguity
  trade off in this family; tune and judge on stage-2 exact only.
