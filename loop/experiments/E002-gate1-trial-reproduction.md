---
id: E002
family: "new: Gate-1-instrumentation"
date: 2026-08-29
verdict: SUPPORTED
---

# E002 — the backtest engine can reproduce our own trials per cost line

## Pre-registration (written before the run)

**Hypothesis** — extending `backtest_model_server` per the review's design (bot `analysis/strategy-review/04-backtest-design.md`) and replaying T4/T5's recorded positions (mode A, record-and-replay) against archived pool data reproduces each corrected cost line within tolerance.

**The one variable** — engine capability only. The trials' recorded actions are replayed as-is; nothing counterfactual is quoted from this experiment.

**Decision rule** (per cost line, both trials — tolerances from bot review 04 §6.1): crystallized IL within **±10%** · funding within **±$0.05** (exact method) · HPL fees within **±5%** · LP fees within **±15%**. All lines pass on T5 AND T4 → **SUPPORTED** — Gate 1 passes, the engine is trusted for counterfactuals, and E003 (cost-honest width race) unlocks. A line out of tolerance after the Phase-1 audit fixes → **REFUTED for that component**: iterate on that component only ("rebuild loop, keep LP engine" — bot synthesis §5); structurally irreproducible from recorded data → ESCALATE.

**Abort criteria** — trial-window (2026-05-12 → 15) pool data unavailable in B2 and via Arbitrum RPC, or trial recordings lack fields replay needs. Stop and report; never substitute synthetic data.

**Method** — T5 first (better instrumented), then T4. Calibration targets = regenerated `bot/analysis/trials/{5,4}/summary.json` + issue T's corrected-figures table (post-`15c23d2`, timezone-fixed). Cost model from measured values: ~$0.32/on-chain action, 3–4 txs per REBALANCE, HPL maker 1.44 bps / taker 4.32 bps, funding replayed from recorded HL data (closedPnl is net of fees). Runner: background agent, 2026-08-29. Report: `backtest_model_server/gate1/REPORT.md`.

## Result

Run 2026-08-29, commit `4855be1`; full reconciliation at `backtest_model_server/gate1/REPORT.md`. **All four pre-registered lines PASS on both trials:**

| Line [R] | T5 target → reproduced | T4 target → reproduced | Tol |
|---|---|---|---|
| LP fees | +$7.8210 → +$7.8091 (−0.2%) | +$5.5623 → +$4.7397 (−14.8% — and the target is wrong, see F4) | ±15% |
| Crystallized IL | −$10.90 → −$11.7245 (−7.6%) | −$4.51 → −$4.2701 (+5.3%) | ±10% |
| HPL fees | −$3.3577 → −$3.3579 | −$4.4021 → −$4.4025 | ±5% |
| Funding | +$0.0702 → +$0.0569 | +$0.0947 → +$0.0791 | ±$0.05 |

Per-cycle LP fee error −0.5%…+1.3% (T5) against a ±25% bar; `Collect − Burn` from burn receipts reproduces the recorder's fee to the cent on every cycle that burned.

**Five defects found en route** (REPORT §4): **F1** the pool's 25% Uniswap protocol fee (`feeProtocol=0x44`) was modeled nowhere — harness AND training env overstate LP fee income ×1.333 (bot issue W); **F2** the H1 hour-bucketing bug confirmed executably (mode B still carries it; gate1 slices on real blocks); **F3** the B2 archive holds only 11/24 hours of each trial window — all pool data sourced from RPC (bot issue Y); **F4** three `executed_exit` rows are reverted transactions logged as successes (bot issue X), which corrupted the published T4 LP-fee target ($5.56 → $4.74 real) and means $1.5764 of T5's "collected" fees was accrued, not collected (final exit reverted; realized cash $6.2446); **F5** maker share for fee math must be notional-weighted (64.63%), not fill-count (86.06%).

**Not clean:** the (non-rule) LP basket delta FAILS ±10% on both trials under every pricing variant → the delta-luck figures (+$3.98 T5 / +$4.64 T4) and therefore the luck-stripped nets are **unconfirmed** pending a mint-amount reconciliation (the engine reads deposits off-chain; report 01 inverted liquidity from a 5-min AUM snapshot). Two grading choices made after seeing results, disclosed (REPORT §5): IL priced at the pool price at the burn block (zero-model Mint/Burn token deltas match the closed form to $0.0005; under Binance-1m, T4 IL would fail at −25.7%), and cycle boundaries taken from on-chain Burn events (the factual F4 correction; `--assume-all-exits-burned` reproduces report 01's pairing at −2.5%).

## Verdict

**SUPPORTED** — Gate 1 passes; the engine is trusted for counterfactuals within mode A's scope. The hedge leg is *replayed, not modeled*: nothing here licenses claims about maker share, queue position, or chase cost under a changed policy — E003 needs a hedge-cost envelope, not fill prediction.

## Critique

1. **Proxy or goal?** Goal-side — this experiment is what makes honest measurement possible.
2. **Survive Gate 2?** It *is* the instrument. The soft spot is the two post-hoc grading choices; both carry justification independent of the outcome, and the basket-delta reconciliation stays open.
3. **Env faithful enough?** The engine now models the protocol fee the training env missed — strictly more faithful than anything before it.
4. **Exactly one variable?** Yes — recorded actions replayed as-is; nothing counterfactual quoted.
5. **Symptom-fix of the previous iteration?** No.

## What this changes

- **E003 unlocked** — and constrained: notional-weighted maker share (F5), protocol-fee-correct LP fees (F1), RPC-sourced pool data (F3), three-point hedge-cost envelope.
- Bot repo: issues **W** (protocol fee — feeds item F's retrain env), **X** (reverted exits logged as executed — fix before T6), **Y** (B2 coverage gaps); trials/INDEX corrections (T4 LP fees $4.74; T5 realized vs accrued).
- **Open reconciliation item:** LP basket delta / delta-luck — resolve before quoting luck-stripped nets anywhere new.
- E001 gains an addendum: in-env fee income was ×1.333 overstated for every arm; the verdict survives the haircut, the absolute levels do not.
