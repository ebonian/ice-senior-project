---
id: E004
family: "new: Gate-1-instrumentation"
date: 2026-08-29
verdict: RUNNING
---

# E004 — report 01's basket-delta derivation, not the engine's chain read, explains the E002 mismatch

## Pre-registration (written before the run)

**Hypothesis** — the LP basket delta line that failed E002 (outside ±10% on both trials, every pricing variant) fails because bot report 01 inverted position liquidity from 5-minute AUM snapshots, while the engine reads deposits from the chain's Mint events; the chain read is correct.

**The one variable** — the derivation only: re-derive report 01's basket delta by its own method but fed chain-read mint amounts (and the engine's by report 01's amounts), cycle by cycle, to locate exactly where the two diverge. E002's flagged cycle: T5's breakout cycle — Mint event says 0.250925 ETH deposited; report 01's +$9.96 implies ≈0.2316 ETH.

**Decision rule** — the discrepancy collapses to within ±10% when report 01's method is fed chain-read amounts → **SUPPORTED**: report 01's delta-luck figures (+$3.98 T5 / +$4.64 T4) get corrected and luck-stripped nets become quotable again. The chain read is shown wrong (Mint event inconsistent with wallet token flows / receipts) → **REFUTED**: engine bug — STOP and escalate; E002's IL line must be re-checked before any E003 result is trusted. Neither → INCONCLUSIVE with the cycle-level table of what remains.

**Abort criteria** — required raw inputs (AUM snapshots, trial CSVs, receipts) missing fields.

**Method** — work only in `backtest_model_server/gate1/diagnostics/basket_delta/`; `gate1/engine/` is read-only. Deliverable: cycle-by-cycle reconciliation table and either corrected delta-luck figures or the engine bug report. Runner: background agent, 2026-08-29.

## Result

_Pending._

## Verdict

RUNNING.

## Critique

_After results._

## What this changes

Whether the review's luck-stripped loss figures (−$13 to −$17/day) survive. SUPPORTED → correct report 01/synthesis numbers (bot repo, via main session). REFUTED → engine fix + E002/E003 re-check before anything downstream is quoted.
