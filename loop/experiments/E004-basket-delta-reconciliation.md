---
id: E004
family: "new: Gate-1-instrumentation"
date: 2026-08-29
verdict: SUPPORTED (T5) · INCONCLUSIVE (T4 — cause fully located)
---

# E004 — report 01's basket-delta derivation, not the engine's chain read, explains the E002 mismatch

## Pre-registration (written before the run)

**Hypothesis** — the LP basket delta line that failed E002 (outside ±10% on both trials, every pricing variant) fails because bot report 01 inverted position liquidity from 5-minute AUM snapshots, while the engine reads deposits from the chain's Mint events; the chain read is correct.

**The one variable** — the derivation only: re-derive report 01's basket delta by its own method but fed chain-read mint amounts (and the engine's by report 01's amounts), cycle by cycle, to locate exactly where the two diverge. E002's flagged cycle: T5's breakout cycle — Mint event says 0.250925 ETH deposited; report 01's +$9.96 implies ≈0.2316 ETH.

**Decision rule** — the discrepancy collapses to within ±10% when report 01's method is fed chain-read amounts → **SUPPORTED**: report 01's delta-luck figures (+$3.98 T5 / +$4.64 T4) get corrected and luck-stripped nets become quotable again. The chain read is shown wrong (Mint event inconsistent with wallet token flows / receipts) → **REFUTED**: engine bug — STOP and escalate; E002's IL line must be re-checked before any E003 result is trusted. Neither → INCONCLUSIVE with the cycle-level table of what remains.

**Abort criteria** — required raw inputs (AUM snapshots, trial CSVs, receipts) missing fields.

**Method** — work only in `backtest_model_server/gate1/diagnostics/basket_delta/`; `gate1/engine/` is read-only. Deliverable: cycle-by-cycle reconciliation table and either corrected delta-luck figures or the engine bug report. Runner: background agent, 2026-08-29.

## Result

Commit `823835a`; full writeup + cycle-level table at `backtest_model_server/gate1/diagnostics/basket_delta/`. **The engine is vindicated**: the disputed Mint is corroborated **to the wei** by the receipts' ERC-20 Transfer logs (pool `Mint.amount0` = WETH Transfer→pool = 250925078172474145 wei; USDC leg exact; 7/7 independent checks). No engine bug; E002's IL line stands; **E003 is not blocked**.

The reconciliation ladder closes both trials to a $0.000000 identity residual. T5's gap = the ETH-leg amount (+$0.78) + price source (+$0.20). T4's gap = **the cycle boundary, −$5.07** — the two reverted `executed_exit` rows (bot issue X) that report 01 treated as real cycle closes; the engine correctly carries the position to the next real Burn.

**Mechanism — not the §3.3 guess.** The AUM snapshot agrees with the chain to 0.08%; the error is inverting position size at the **Binance price instead of the pool price**. A 4.27 bp basis is amplified ≈185×/bp by narrow-range V3 geometry (the ETH share of value sweeps 100%→0% across a 100 bp range): the price swap alone cuts mean ETH-leg error 4.08%→0.05% (T5) and 5.96%→0.02% (T4). → new bot learning `invert-v3-splits-at-the-pool-price`.

**Corrected figures** (only the basket term changes; hedge directional reproduces report 01 exactly):

| | T5 published → corrected | T4 published → corrected |
|---|---|---|
| LP basket delta | +$8.52 → +$9.50 | +$1.20 → **−$4.27** |
| Delta luck | +$3.98 → +$4.96 | +$4.64 → **−$0.83** |
| Luck-stripped net | −$16.58 → −$17.56 | −$13.40 → **−$7.93** |

Report 01 §6's "both trials gained ~$4 from under-hedge" is false for T4; the corrected pair straddles zero — better support for "expectation ≈ 0, strip before projecting" than two same-signed figures. The T5-vs-T4 spread is now IL-dominated (−$10.90 vs −$4.27), as report 01 §7 argued.

## Verdict

**T5: SUPPORTED** — the substitution collapses the gap to +9.1%, inside ±10%. **T4: INCONCLUSIVE per the rule as written** — its divergence is not an amount problem but the F4/issue-X cycle boundary, fully located and proven on-chain anyway. The REFUTED (engine-bug) branch does not fire.

## Critique

1. **Proxy or goal?** Goal-side — instrument calibration.
2. **Survive Gate 2?** n/a — strengthens the instrument's standing (closed-form vs raw-token-delta agree to $0.005 on the 7 comparable cycles).
3. **Env faithful?** n/a.
4. **One variable?** For T5, yes. T4's pre-registered instrument turned out wrong for its actual cause — recorded as INCONCLUSIVE rather than reframed post hoc.
5. **Symptom-fix?** No.

## What this changes

- Luck-stripped nets are quotable again at corrected values (bot review 01 banner, tracker, synthesis updated).
- Issue X's blast radius grows: it corrupted the attribution layer too (T4 basket −$5.07, delta-luck sign flip), not just LP fees.
- New bot learning: never infer a V3 token split from a USD value and an off-chain price; invert at the pool price.
- Carried unresolved: the luck construction's time-coverage mismatch (basket covers 54–67% of the window, directional 100%); T4's unexplained residual must be re-read after this correction, not carried over.
