# Hypothesis backlog

> Discovery's output, the experiment loop's input — one card per testable hypothesis. The card is the interface between the two loops.
>
> Lifecycle: **PROPOSED → STAGED → E<NNN> (running) → SUPPORTED / REFUTED / DROPPED.**

## B1 — Streak-aware in/out rules buy the contiguity that threshold rules cannot

- **Claim:** a rule that chooses *runs* of hours — hysteresis (enter/exit thresholds), dwell minimums, or a DP over a forecast payoff series — on a C3-quality selector nets ≥ +$0.389/day central on ETH/USDC 0.05%.
- **From:** [E007 §2/§6](../loop/experiments/E007-causal-signal-test.md) (the contiguity gap); memo **M002** (written by the E008 cycle).
- **Why it might work:** selection quality is achievable (K6: AUC 0.616, +$0.42/h held-set mean); the ceiling's substance is contiguity (K4: median 3h oracle streaks); the DP mechanism already exists (E006 stage-1) — replace foresight with a forecast.
- **Why it might not:** forecast error compounds across a streak; dwell constraints may force holding exactly the hours the selector was right to drop; E007's smooth candidates (4–5h streaks) died on selection, its selective ones on fragmentation — this family must thread both.
- **Status:** **STAGED → E008** (operator go 2026-09-03). **Operator pre-commitment: if E008 is REFUTED, B2 activates — no further experiments on this pool.**

## B2 — wstETH/WETH 0.01% funding-carry venue

- **Claim:** the wstETH/WETH 0.01% LP + HL hedge package sustains its measured **+$0.22–0.27/day** (5.7–7.0% APR) out of window, with funding persistence and acceptable liquidation risk.
- **From:** [E005 watchlist](../loop/experiments/E005-pool-screen.md). Note the composition: +$0.210 of +$0.223/day is perp funding carry; the LP leg alone is +$0.014.
- **Prerequisites:** funding-persistence validation (longer window, funding-regime sensitivity, per-venue perp cost calibration); the K8 margin/liquidation design pass on the bot side **before any capital**.
- **Status:** **PROPOSED — activates on E008 REFUTED** (operator pre-commitment 2026-09-03).

## B3 — Re-screen another chain (Base) with recalibrated gas constants

- **Claim:** E005's screen, re-run with Base cost calibration, finds a pool passing all gates.
- **From:** [E005](../loop/experiments/E005-pool-screen.md) (Arbitrum-only scope was a validity choice, not a finding).
- **Status:** **PROPOSED, parked** — the operator picked B2 as the fallback path (2026-09-03).
