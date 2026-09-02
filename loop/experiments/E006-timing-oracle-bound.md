---
id: E006
family: H-timing (new — regime/timing policies on a fixed venue)
date: 2026-09-02
verdict: RUNNING
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

_(pending)_

## Verdict

RUNNING

## Critique

_(pending)_

## What this changes

_(pending — SUPPORTED stages E007; REFUTED finishes the ETH/USDC 0.05% story
with no asterisk and sharpens the three-way venue call.)_
