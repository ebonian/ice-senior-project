---
id: E006
family: H-timing (new — regime/timing policies on a fixed venue)
date: 2026-09-02
verdict: SUPPORTED
---

# E006 — A perfect-foresight timing policy on ETH/USDC 0.05% clears the target with modelable margin

## Pre-registration (write BEFORE running)

**Hypothesis** — On ETH/USDC 0.05% (the E003 control), an hour-level in/out
timing policy with **perfect foresight** (the oracle ceiling for any regime
model — Kaufman-ER-based, vol-based, or learned) earns enough after full frozen
costs that a realizable model capturing a plausible fraction of the ceiling
could reach the +$0.389/day target. E003 §11 and E005 established that
*always-in* fails at every width; timing is the one family-internal escape not
yet measured (E003 §8 "what this does not answer" / operator question 2026-09-02).

**The one variable** — the in/out timing dimension, vs. the named baseline
`always_in` (E003's arms). Frozen at E003 values: engine `gate1/engine/`
unmodified; data = E003's committed parquets + funding CSV (no new fetches);
window 2026-05-01→2026-08-28; cost model `gate1-2026-08-29`; envelope
`e003-2026-08-29` (central for the verdict); LP notional $1,015 constant;
lag1h_rh1h loop while held. Widths: ±0.2%, ±0.5%, ±2.0%, ±8.3%.

**Method — two-stage, one-sided-bound-first:**
1. **Upper-bound oracle (cheap, separable):** per-hour payoff computed as if
   freshly centered at each held hour's start (over-credits fees, never
   under-credits): `fees_h + funding_h − gamma_h`. Hour-selection with switch
   costs (enter = mint-path txs + swap + hedge open; exit = burn + collect +
   hedge close; frozen cost model) is then an O(N) two-state DP. This bounds
   EVERY timing policy from above.
2. **Exact simulation of the selected policy:** the streaks the DP chooses are
   re-simulated exactly (fresh mint at streak start, standard loop inside,
   burn+flatten at exit). This is the realistic oracle number.

**Sanity contracts (blocking):** switch-costs→∞ oracle must reproduce E003's
always-in results exactly; the oracle must weakly dominate both `always_in`
and `always_cash` by construction; accounting identity per run ≤ 1e-6.

**Descriptive section (NOT part of the verdict; feeds E007's design):** for
held vs skipped hours, the distributions and separation power (AUC) of
*trailing* (causal) signals: realized vol (12/24/48h) and Kaufman Efficiency
Ratio (12/24/48h), plus their persistence (autocorrelation at 1–24h lags).
This answers "could a backward-looking regime filter have known", without
judging it — that is E007's pre-registration if E006 supports.

**Decision rule** (central envelope, best width):
- **REFUTED** — the STAGE-1 UPPER BOUND nets < **+$0.78/day** (2× target) at
  every width: no timing model, however good, can plausibly reach target here
  (a realizable model captures a fraction of a bound that is itself inflated).
  Timing closes on this pool; the venue decision proceeds on E005 alone.
- **SUPPORTED** — the STAGE-2 exact oracle nets ≥ **+$1.56/day** (4× target) at
  some width: a model capturing ≥25% of the realistic ceiling reaches target.
  Routes to E007: causal-signal test (Kaufman ER / vol filters) before any
  learned model.
- **INCONCLUSIVE** — between: the edge exists but demands a heroic capture
  fraction; escalate with the capture math to the operator.

**Abort criteria** — none needed (pure computation on local data); if stage-1
runtime projects > 4 h something is wrong with the approach — stop and review.

## Result

Run 2026-09-02 on E003's committed data (3,434,113 swaps, 119.00 days), engine
and constants frozen as pre-registered. Full report:
[`backtest_model_server/e006/REPORT.md`](../../backtest_model_server/e006/REPORT.md);
artifacts under `backtest_model_server/e006/out/`.

$/day over the full window, central envelope (opt/pess in the report):

| Arm | always_in (E003 lag1h) | stage-1 UB | stage-2 exact | held % | streaks | capture needed |
|---|---:|---:|---:|---:|---:|---:|
| ±0.2% (w4) | −14.731 | +8.845 | **+6.058** | 57.9% | 435 | **6.4%** |
| ±0.5% (w10) | −9.253 | +5.734 | **+3.718** | 67.5% | 292 | 10.5% |
| ±2.0% (w40) | −3.164 | +1.294 | +0.807 | 68.0% | 97 | 48% |
| ±8.3% (w160) | −0.844 | +0.135 | +0.065 | 49.2% | 20 | — |

- The REFUTED clause could not fire (stage-1 UB ≥ +$0.78/day at three widths);
  the SUPPORTED clause fired at w4 and w10 (stage-2 exact ≥ +$1.56/day). w4 is
  positive at every envelope point (+6.84/+6.06/+3.24) and in all four months.
- Width ordering inverts E003: narrow wins 75× under foresight. Inside held
  hours fees/gamma is **2.96** (vs 0.73 always-in, same loop): holding 58% of
  hours keeps 69% of fees and sheds 83% of gamma. 56.9% of w4 hours have
  positive freshly-centered payoff — E003's negative *average* hid a
  majority-positive hourly mix.
- Contracts (blocking, 71 checks): switch-cost→∞ reproduces E003's committed
  lag1h_rh1h always_in **float-exact** at all four arms and all three envelope
  points; DP dominates always_in and always_cash everywhere; worst accounting
  gap across all 844 simulated streaks 8.9e-15.
- Descriptive (NOT the verdict): the oracle holds the *quiet* hours (same-hour
  gamma AUC 0.90, intra-hour RV AUC 0.37) in short streaks (median 3h, p90 8h),
  uniformly across months (56–59%). But every pre-named TRAILING signal is
  near-powerless to find them: Kaufman ER AUC 0.476–0.526, trailing vol
  0.452–0.466, previous-hour RV 0.460. Mechanism: next-hour realized vol — the
  thing worth predicting — has ACF(1) of only 0.22; ER persists (ACF(1)
  0.77–0.94) but measures trend efficiency, which does not separate.

## Verdict

**SUPPORTED** — stage-2 exact oracle nets ≥ +$1.56/day at some width
(+$6.058/day at ±0.2%, +$3.718/day at ±0.5%, central). Per the pre-registered
route this stages **E007: the causal-signal test** — with the honest caveat
that this run's own descriptive section already shows the two named signal
families (Kaufman ER, trailing vol) separating at AUC ≤ 0.53.

## Critique

1. **Proxy or goal?** Goal: net $/day under the full frozen cost stack, same
   engine and arbiter as E003. But the number is a *ceiling*, not a P&L —
   stated as such everywhere; nothing here is quotable as live profitability.
2. **Would it survive Gate 2?** The machinery would (it reproduces E003
   float-exact, and E003's engine reproduced T5 per cost line). The *policy*
   cannot go to Gate 2 — it conditions on the future. Only an E007 causal
   filter could. One channel biases SUPPORTED: adverse selection/MEV is
   unmodelled, and the bias is larger than E003's because held hours are
   selected for fee-per-variance; the pessimistic point (+$3.24/day) does not
   cover that channel.
3. **Environment faithful enough?** Hedge execution stays a priced envelope
   (unsimulatable book), hedge ratio not varied, four months of one market.
   Verdict-relevant margins are wide (+$6.06 vs the $1.56 bar), monthly signs
   stable.
4. **Exactly one variable?** Yes — the in/out timing dimension vs E003's
   always_in, everything else bit-frozen (verified by contract).
5. **Symptom-fix of the previous iteration?** No — new family (H-timing),
   pre-registered before any number existed, measuring the ceiling E003 §8
   explicitly declined to answer.

## What this changes

- **Timing does not close on ETH/USDC 0.05%** — first positive number the
  strategy family has produced under full frozen costs. H-timing's ceiling:
  +$6.06/day exact at ±0.2%; target needs 6.4% capture.
- **E007 is staged** (causal-signal test, per the SUPPORTED route), but its
  pre-registration must confront §5 of the report: thresholding ER or trailing
  vol as-is should expect REFUTED; the predictive target is next-hour realized
  variance (ACF(1) ≈ 0.22). Candidate directions: intra-hour microstructure,
  time-of-day seasonality, cross-venue leads, or longer/smoother streaks at a
  lower ceiling.
- **The operator's three-way venue call (E005) gains a conditional fourth
  option**: stay on the control pool iff E007 clears ~6–10% capture at
  ±0.2–0.5%. No capital moves on an oracle number (bot ADR 0008).
