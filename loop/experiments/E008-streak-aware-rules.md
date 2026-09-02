---
id: E008
family: H-timing (streak-aware sub-family)
date: 2026-09-03
verdict: REFUTED
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

Run 2026-09-03 on E003's committed data; engine, cost model, envelope frozen
as pre-registered; all 38 blocking contracts pass (re-run after the final
phase). Full report:
[`backtest_model_server/e008/REPORT.md`](../../backtest_model_server/e008/REPORT.md);
artifacts under `backtest_model_server/e008/out/`.

Every one of the six pre-named candidates, tuned on 2026-05→07 per the M002
grids, is **negative** over the full window at both arms, at all three
envelope points, and on held-out August. $/day central, full window /
held-out August (best arm details in the report):

| Cand (tuned) | w4 full | w4 Aug | w10 full | w10 Aug | months+ (best arm) | AUC |
|---|---:|---:|---:|---:|---:|---:|
| S1 calendar hysteresis (P90/P50) | −1.036 | −2.682 | −1.097 | −2.414 | 1/4 | 0.59–0.62 |
| S2 blend hysteresis (0.9/0.5) | −0.181 | −0.240 | −0.116 | −0.193 | 0/4 | 0.59 |
| S3 min dwell (P90, D=2) | −2.208 | −3.474 | −2.330 | −3.221 | 0/4 | 0.59–0.62 |
| S4 exit debounce (P90, M=2) | −2.481 | −3.468 | −2.483 | −3.312 | 0/4 | 0.59–0.62 |
| S5 DP on calendar (κ=8, c=0.5) | −0.090 | −0.628 | **−0.025** | −0.458 | 2/4 | 0.59–0.62 |
| S6 receding-horizon DP (λ=24) | −2.069 | −3.698 | −1.599 | −2.565 | 0/4 | 0.61–0.62 |

- **3 of 404 tune configurations were positive** (the program's first after
  E007's 0/540) — all three are S5's shrunk-calendar DP holding 0.6–3.0% of
  hours in median-1h streaks; all three fail held-out August by 4–9× their
  tune gain.
- Sanity: `always_in` reproduces E003 float-exact (uncached); `always_cash`
  = $0; the E006 oracle mask through the same evaluator returns +$6.058/day
  (w4) and +$3.718/day (w10).
- Mechanism (report §2): **the contiguity gradient is negative everywhere.**
  S1's bridge knob: −$0.55/d at lo=P50 → −$6.58/d at lo=P10, monotone. S3's
  dwell knob: −$1.84/d at D=2 → −$9.51/d at D=12, monotone. S5, which
  prices every bridge against a round trip, *refuses* contiguity — 7 of 12
  configs choose the empty mask, and its positive tune cells are singleton
  holds. S6 held real streaks (median 3–6h) at −$1.6 to −$2.1/day.
  Selection quality survives out of window (AUC 0.59–0.62) but no point on
  the selectivity↔contiguity frontier clears the $0.77–0.85 round trip plus
  honest stage-2 accounting.

## Verdict

**REFUTED** — the pre-registered clause fired: no pre-named candidate's
full-window central net exceeds $0/day (best: S5 at ±0.5%, −$0.025/day;
also negative at every envelope point and on held-out August). Streak-aware
rules do buy contiguity; on this pool it is not worth buying.

**The operator pre-commitment (2026-09-03, bot ADR 0009) executes: the
venue moves to the wstETH/WETH 0.01% funding-carry path (discovery card
B2); no further experiments on ETH/USDC 0.05% either way.**

## Critique

1. **Proxy or goal?** Goal — net $/day through the same stage-2 exact
   simulator and frozen cost stack as E003/E006/E007; the tuning objective
   and the verdict metric were the same quantity.
2. **Would it survive Gate 2?** The negative results would — every
   unmodelled channel (adverse selection, MEV) points further negative. No
   positive claim exists to need Gate 2.
3. **Environment faithful enough?** For a refutation, yes. Four months of
   one market remains the window caveat; all four months and both arms
   agree on the sign.
4. **Exactly one variable?** Yes — the policy family (threshold → streak-
   aware), on selectors, data, costs, engine, and capital all bit-frozen
   (verified by contract; selectors inherited from E007's tuned values or
   re-tuned only within pre-registered grids).
5. **Symptom-fix of the previous iteration?** No — E008 tested E007 §6's
   pre-named residual under an operator decision with the exit
   pre-committed; candidates were memo-ranked (M002) before any outcome.

## What this changes

- **H-timing closes on ETH/USDC 0.05%.** E006's ceiling stands as a
  measurement; E007 killed per-hour thresholds; E008 kills the streak-aware
  family across hysteresis, dwell, debounce, and forecast-DP mechanisms.
  No further experiments on this pool (operator pre-commitment).
- **The venue call is resolved**: discovery card B1 → REFUTED, card B2
  (wstETH/WETH 0.01% funding-carry) → ACTIVATED. Its stated prerequisites
  bind: funding-persistence validation, per-venue perp cost calibration,
  and the K8 margin/liquidation design pass on the bot side **before any
  capital**. Escalated to the operator per loop PROTOCOL §7 — B2 work is
  not started by this iteration, and bot-repo propagation (tracker /
  ADR 0009 companion) is the operator's next session.
- **Recorded for successors**: the calendar selector is real (AUC 0.59–0.62,
  two experiments, both arms) — the cost structure, not the signal, is what
  fails here. On a venue with ~10× cheaper switches, test S5 → S1 → S2
  first. Constraint registry updated (K11).
