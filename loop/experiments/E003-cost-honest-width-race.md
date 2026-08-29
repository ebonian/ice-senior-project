---
id: E003
family: H-width
date: 2026-08-29
verdict: REFUTED
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

Run 2026-08-29, commit `0dd3603`; full report at `backtest_model_server/e003/REPORT.md`. Data: 3,434,113 RPC swaps, 2026-05-01 → 08-28 (119 days), **100% hourly coverage** across all four months, four independent coverage gates passed; provenance check: swap-for-swap identical to gate1's independent T5 pull, all 8 T5 cycle fees reproduced at 0.00e+00 relative error. Issue Y measured en route: B2 holds only 18–47% of the chain's swaps on the trial week.

The frontier ($/day, central envelope, LP notional constant at $1,015):

| Arm | ±% | recenters | optimistic | central | pessimistic |
|---|---:|---:|---:|---:|---:|
| W4 | ±0.20% | 13,967 | −46.39 | −49.13 | −59.03 |
| W6 | ±0.30% | 7,191 | −28.98 | −30.53 | −36.12 |
| W10 | ±0.50% | 2,941 | −16.94 | −17.90 | −21.34 |
| W20 | ±1.01% | 853 | −9.04 | −9.60 | −11.59 |
| W40 | ±2.02% | 243 | −4.67 | −4.99 | −6.15 |
| W80 | ±4.08% | 51 | −1.89 | −2.05 | −2.61 |
| W160 | ±8.33% | 13 | −0.81 | **−0.89** | −1.17 |
| always_cash | — | 0 | 0.00 | 0.00 | 0.00 |

**28 arm-months, zero positive** — every monthly sub-window of every arm is negative at every envelope point. Robust across four sensitivity runs (1h decision loop, 4h rehedge, recenter-only rehedge, compounding notional).

**The mechanism is not turnover.** LP fees never cover the gamma the delta hedge leaves behind, before any execution cost: **fees/gamma = 0.65–0.97 across every arm** (the Itô term ½∫V″d⟨P⟩). Quadratic variation is frequency-invariant, so rehedging more often does not buy it back — proven empirically: recenter-only rehedging cuts W160's HPL execution −98% while moving its gamma only −7%. Breakeven needs 1.5–1.7× the fee revenue, and that multiple is near-constant across a 40× width range: **the shortfall is a property of the venue, not the rule.** The frontier is monotone in width and its limit is always_cash at $0.00 — "wider is better" points at the exit, not at a good width.

**Disclosed post-hoc change** (REPORT §6): the first pass compounded LP notional and drove W4's balance to −$281 (unphysical); the primary run holds notional constant at $1,015. This moved numbers *away* from the hypothesis (W4 −$12.83 → −$49.13/day); no frozen cost constant was touched; the compounding run is kept separately with ruin detection (W4 exhausts the stake 2026-06-25, W6 2026-08-19).

## Verdict

**REFUTED — the strongest pre-registered clause fired**: no arm reaches ≥ $0/day even under the optimistic envelope. Best arm W160 nets −$0.890/day central vs the +$0.389/day target. Per the pre-registration this routes to **H-pool screening and the structural conversation, not a retrain** — item F's bar cannot be "beat this arm" because there is no arm to beat.

Scope of the claim: ETH/USDC 0.05% on Arbitrum, ~$1,015 LP notional, this strategy family (delta-hedged always-in fixed width), May–Aug 2026. It says nothing against other pools, other fee tiers, or the hedge/engine infrastructure — those are exactly what screening tests next.

## Critique

1. **Proxy or goal?** Goal — real chain data, honest measured costs, the Gate 2 measurement itself.
2. **Survive Gate 2?** It is Gate 2's width half. The weakest term (hedge microstructure) is bracketed by the envelope, and REFUTED holds at every point of it.
3. **Env faithful?** Gate-1-validated engine + 100%-coverage chain data; provenance tied back to T5 at zero relative error.
4. **Exactly one variable?** Width across arms, yes. One post-hoc convention change (notional treatment) — disclosed, moved numbers away from the hypothesis, both treatments reported.
5. **Symptom-fix?** No.

## What this changes

- **H-width: answered for this pool — REFUTED at every width.** Items K/L (re-mint timing, width×dwell sweeps) are moot here.
- **Item F (retrain) is dead for ETH/USDC 0.05%.** Retraining cannot fix fees < gamma.
- **Next: H-pool screening (E005)** — the screen criterion is now sharp and cheap: fees/gamma > 1 with margin, computable per pool from swap data + this engine.
- **ESCALATED to operator:** T6's premise (a confirmation trial on this pool) is undermined by offline falsification at this size; the tracker's Gate-2 "structural conversation" clause fired. Capital scale and venue are operator calls.
