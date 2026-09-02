---
id: E008
family: H-timing (streak-aware sub-family)
date: 2026-09-03
verdict: RUNNING
---

# E008 — A streak-aware rule buys the contiguity that threshold rules cannot

## Pre-registration (write BEFORE running)

**Hypothesis** — At least one of the six pre-named streak-aware candidates
from [memo M002](../../discovery/memos/M002-buying-contiguity-with-streak-rules.md)
§3 (S1 calendar hysteresis, S2 blend hysteresis, S3 minimum dwell, S4 exit
debounce, S5 DP over the calendar forecast, S6 receding-horizon DP), with
parameters frozen on the tune window, nets **≥ +$0.389/day central**
full-window AND **> $0/day central** on held-out August on ETH/USDC 0.05%
through E006's stage-2 exact simulator. This is discovery card
[B1](../../discovery/BACKLOG.md)'s claim, staged by the operator 2026-09-03.

**The one variable** — the policy *family*: per-hour threshold rule (E007,
REFUTED) → streak-aware rule (hysteresis / dwell / DP-over-forecast) built
on the same selectors E007 already measured (the dow×hod calendar C3 and
the payoff EWMA C1). Baselines: `always_in` (E003 committed lag1h_rh1h) and
`always_cash` ($0). Everything else frozen at E003/E006/E007 values:

- **Data/window identical to E007**: E003's committed parquets + funding
  CSV, 2026-05-01 → 2026-08-28 (119.00 days). No candidate needs the
  Binance reduction (M002 excludes C4-family selectors); it stays committed
  and untouched.
- **Cost model** `gate1-2026-08-29` unmodified; **envelope**
  `e003-2026-08-29` (total bps: optimistic 1.984 / central 3.359 /
  pessimistic 8.320); LP notional $1,015; lag1h_rh1h loop in-streak.
- **Widths ±0.2% (w4) and ±0.5% (w10) only** (M001 §6).
- Engine `gate1/`, `e003/`, `e005/`, `e006/`, `e007/` untouched; new code
  under `backtest_model_server/e008/` only, reusing e006/e007 machinery by
  import.

**Pre-named candidates** — M002 §3's ranked table, frozen there before this
file existed: mechanisms, selector constructions, parameter grids (202
configs/arm), NaN⇒out, initial state out, tie-break = first config in the
enumeration order. The memo is append-only from this point. No candidate may
be redefined mid-run — any redefinition is a new experiment.

**Overfitting guards** — candidates and grids pre-named in M002; **tuning
uses 2026-05-01 → 2026-07-31 ONLY** (objective: stage-2 exact net $/day,
central, on the tune window); **2026-08 is untouched until every parameter
of every candidate×arm is frozen on disk** (`out/tune_*.json`); the final
phase refuses to run until all 12 candidate×arm parameter sets exist;
blocking tests enforce tuning isolation (E007 pattern). Signal *values* in
August may use trailing pre-August data (EWMAs are causal); signal
*parameters* and calendar cells may not. S5's final phase runs the frozen-
parameter DP over the full window's hour grid — every input to that DP
(calendar cells, cost constants, κ, c) derives from tune-window data only,
so the August portion of its plan is causal by construction.

**Decision rule** (stage-2 exact simulation only, both arms evaluated, all
three envelope points reported, **central decides**, best of w4/w10 per
candidate):

- **SUPPORTED** — some pre-named candidate nets **≥ +$0.389/day central
  full-window** (2026-05-01→08-28) AND **> $0/day central on held-out
  August** (2026-08-01→08-28).
- **REFUTED** — no pre-named candidate exceeds **$0/day central
  full-window**; OR every candidate clearing that bar fails held-out August
  (**≤ $0/day central**).
- **INCONCLUSIVE** — anything else (e.g. positive full-window but below
  target with positive August): report the best candidate's full numbers
  and state exactly what would disambiguate.

Any SUPPORTED or INCONCLUSIVE-positive number restates the K9 caveat: fee
credit assumes full liquidity share of every in-range swap; adverse
selection/MEV is unmodelled; every positive is an upper bound; no capital
moves on these numbers (bot ADR 0008).

**Operator pre-commitment (2026-09-03, bot ADR 0009): on REFUTED, the venue
moves to the wstETH/WETH 0.01% funding-carry path (discovery card B2); no
further experiments on ETH/USDC 0.05% either way.**

**Sanity contracts (blocking, in `e008/tests/test_e008_contracts.py`; all
must pass before any result is quoted):**

1. **Reproduction** — the `always_in` mask through E008's evaluator equals
   E003's committed lag1h_rh1h results float-exact at w4 and w10, all three
   envelope points (net, LP fees, recenter counts).
2. **Zero** — `always_cash` nets exactly $0 with zero streaks.
3. **Oracle** — the E006 oracle mask (`held_central`) through E008's
   evaluator returns +$6.058/day (w4) and +$3.718/day (w10) central.
4. **Causality** — every candidate's decision at hour t is computable from
   data ≤ t: recompute from truncated data and assert exact equality at
   sampled boundaries (S2/S6 state-dependent paths recomputed step-by-step);
   S1/S3/S4/S5 masks additionally proven invariant to scrambled August
   payoffs. For S5/S6 the optimization is asserted to consume only forecast
   values, never realized payoffs.
5. **Tuning isolation** — the tuner raises on any held-out row; the final
   phase refuses to run until all 12 candidate×arm parameter sets are
   frozen on disk.
6. **Determinism** — no RNG; fixed, ordered grids and tie-breaks; results
   are a pure function of committed inputs.
7. **Accounting identity** — per simulated streak ledger gap ≤ 1e-6,
   asserted on every use (cached or not).

**Abort criteria** — any blocking contract failure stops the run until
fixed (fixes to *machinery* are allowed; changes to candidates, grids, or
this file's clauses are not). Compute blowout > 10× the E007-scale estimate
(~15 min cold) ⇒ cut candidates from the bottom of M002's ranking (S6
first, then S4, S3) and say so in the report. Session/foreground discipline:
all phases checkpoint to `e008/out/*.json` and are resumable.

**Method** — `backtest_model_server/e008/`: `streak_rules.py` (the six
policies), `run_e008.py` (tune / final phases, E007's runner pattern),
`tests/test_e008_contracts.py` (blocking), artifacts in `e008/out/`
(per-config tune grids `tune_<cand>_w<W>.json`, frozen finals
`final_<cand>_w<W>.json`, combined `final_w<W>.json`). Per-streak exact
simulations cached via e007's `StreakCache` mechanism (separate cache files
under `e008/out/`, git-ignored, rederivable; contract 1 runs uncached).
Descriptive add-ons (not the verdict): held %, streak count, median streak
length, oriented AUC vs E006 oracle-held.

## Result

_(pending)_

## Verdict

RUNNING

## Critique

_(pending)_

## What this changes

_(pending)_
