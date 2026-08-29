---
id: E002
family: "new: Gate-1-instrumentation"
date: 2026-08-29
verdict: RUNNING
---

# E002 — the backtest engine can reproduce our own trials per cost line

## Pre-registration (written before the run)

**Hypothesis** — extending `backtest_model_server` per the review's design (bot `analysis/strategy-review/04-backtest-design.md`) and replaying T4/T5's recorded positions (mode A, record-and-replay) against archived pool data reproduces each corrected cost line within tolerance.

**The one variable** — engine capability only. The trials' recorded actions are replayed as-is; nothing counterfactual is quoted from this experiment.

**Decision rule** (per cost line, both trials — tolerances from bot review 04 §6.1): crystallized IL within **±10%** · funding within **±$0.05** (exact method) · HPL fees within **±5%** · LP fees within **±15%**. All lines pass on T5 AND T4 → **SUPPORTED** — Gate 1 passes, the engine is trusted for counterfactuals, and E003 (cost-honest width race) unlocks. A line out of tolerance after the Phase-1 audit fixes → **REFUTED for that component**: iterate on that component only ("rebuild loop, keep LP engine" — bot synthesis §5); structurally irreproducible from recorded data → ESCALATE.

**Abort criteria** — trial-window (2026-05-12 → 15) pool data unavailable in B2 and via Arbitrum RPC, or trial recordings lack fields replay needs. Stop and report; never substitute synthetic data.

**Method** — T5 first (better instrumented), then T4. Calibration targets = regenerated `bot/analysis/trials/{5,4}/summary.json` + issue T's corrected-figures table (post-`15c23d2`, timezone-fixed). Cost model from measured values: ~$0.32/on-chain action, 3–4 txs per REBALANCE, HPL maker 1.44 bps / taker 4.32 bps, funding replayed from recorded HL data (closedPnl is net of fees). Runner: background agent, 2026-08-29. Report: `backtest_model_server/gate1/REPORT.md`.

## Result

_Pending._

## Verdict

RUNNING.

## Critique

_After results._

## What this changes

Gate 1 is the arbiter every later experiment cites. SUPPORTED → E003 (cost-honest width race — decides H-width and bot Gate 2, then the F-vs-pool-screening branch). REFUTED → fix the failing component before ANY counterfactual is quoted.
