---
id: E003
family: H-width
date: 2026-08-29
verdict: RUNNING
---

# E003 — some always-in width clears the profit target under honest costs

## Pre-registration (written before the run)

**Hypothesis** — on ETH/USDC 0.05% (Arbitrum), at $1,420 capital, at least one fixed-width always-in / recenter-on-OOR rule nets **≥ +$0.39/day** (the 10%-APR floor of the operator target) under the central hedge-cost envelope, measured with the Gate-1-trusted engine over a multi-month window.

**The one variable** — width only. Policy held fixed: always in position, recenter when price exits the range, never EXIT, no dwell/hysteresis (that is H-frequency, a later experiment). Arms: W4, W6, W10, W20 (E001's arms) plus wider — W40, W80, W160 or the nearest the engine supports (state the ±% mapping from code) — and always-cash as the zero line. No DQN arm (E001 settled it).

**Decision rule** —
- **SUPPORTED** — any arm's central-envelope net ≥ +$0.39/day over the full window AND positive in a majority of monthly sub-windows → H-width answered; item F's retrain proceeds with "beat this arm through this engine" as its acceptance bar.
- **REFUTED** — no arm ≥ $0/day even under the optimistic envelope → the pool is structurally unprofitable for this strategy at this size → H-pool screening / structural conversation, not retraining.
- **INCONCLUSIVE** — anything between (profitable somewhere but below target, or envelope-dependent sign) → report the width/PnL frontier; operator decides (accept lower APR, screen pools, capital scale).

**Costs (frozen — `cost_model.py` version `gate1-2026-08-29`)** — protocol-fee-correct LP fees (E002 F1); on-chain $0.32/action × 3–4 tx per REBALANCE; HPL fees on a three-point hedge envelope — optimistic / central (64.63% **notional-weighted** maker share, E002 F5) / pessimistic (all-taker + chase allowance); funding replayed from recorded HL history. Changing any constant after seeing results invalidates the run (design §6.3 guard 2).

**Data** — RPC-sourced swaps only (issue Y: B2 has silent gaps; E001's `_data` swaps CSV was B2-built — do NOT reuse without a coverage check). Run the coverage diagnostic on every window used and publish the coverage table; no window enters the race below full coverage. Target ≥ 4 distinct months including the May 2026 trial period.

**Abort criteria** — multi-month RPC data unobtainable, or the build would require modifying `gate1/engine/` in ways that invalidate E002's reconciliation (extend via new modules instead; if impossible, stop and report).

## Result

_Pending._

## Verdict

RUNNING.

## Critique

_After results._

## What this changes

The H-width verdict and bot Gate 2's first half. SUPPORTED → item F retrain unblocks with a concrete bar. REFUTED → H-pool screening. Either way: the width/PnL frontier under honest costs replaces every in-env width claim (E001 addendum applies).
