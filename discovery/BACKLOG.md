# Hypothesis backlog

> Discovery's output, the experiment loop's input — one card per testable hypothesis. The card is the interface between the two loops.
>
> Lifecycle: **PROPOSED → STAGED → E<NNN> (running) → SUPPORTED / REFUTED / DROPPED.**

## B1 — Streak-aware in/out rules buy the contiguity that threshold rules cannot

- **Claim:** a rule that chooses *runs* of hours — hysteresis (enter/exit thresholds), dwell minimums, or a DP over a forecast payoff series — on a C3-quality selector nets ≥ +$0.389/day central on ETH/USDC 0.05%.
- **From:** [E007 §2/§6](../loop/experiments/E007-causal-signal-test.md) (the contiguity gap); memo [**M002**](memos/M002-buying-contiguity-with-streak-rules.md) (2026-09-03 — ranked set S1–S6: calendar/blend hysteresis, dwell, debounce, DP-on-calendar-forecast, receding-horizon DP; E008's pre-named candidates).
- **Why it might work:** selection quality is achievable (K6: AUC 0.616, +$0.42/h held-set mean); the ceiling's substance is contiguity (K4: median 3h oracle streaks); the DP mechanism already exists (E006 stage-1) — replace foresight with a forecast.
- **Why it might not:** forecast error compounds across a streak; dwell constraints may force holding exactly the hours the selector was right to drop; E007's smooth candidates (4–5h streaks) died on selection, its selective ones on fragmentation — this family must thread both.
- **Status:** **REFUTED ([E008](../loop/experiments/E008-streak-aware-rules.md), 2026-09-03)** — all six M002 candidates negative full-window and on held-out August at both arms (best S5 w10 −$0.025/day central); the contiguity gradient is negative everywhere; 3/404 tune configs positive, all fail August. The operator pre-commitment executed: **B2 activates; no further experiments on this pool.**

## B2 — wstETH/WETH 0.01% funding-carry venue

- **Claim:** the wstETH/WETH 0.01% LP + HL hedge package sustains its measured **+$0.22–0.27/day** (5.7–7.0% APR) out of window, with funding persistence and acceptable liquidation risk.
- **From:** [E005 watchlist](../loop/experiments/E005-pool-screen.md). Note the composition: +$0.210 of +$0.223/day is perp funding carry; the LP leg alone is +$0.014.
- **Prerequisites:** funding-persistence validation (longer window, funding-regime sensitivity, per-venue perp cost calibration); the K8 margin/liquidation design pass on the bot side **before any capital**.
- **Status:** **ACTIVATED (2026-09-03 — E008 REFUTED; operator pre-commitment, bot ADR 0009).** Escalated to the operator per loop PROTOCOL §7; the K8 margin/liquidation design pass and funding-persistence validation precede any capital. Not started by the E008 iteration.
- **Progress:** funding-persistence prerequisite **met — [E009](../loop/experiments/E009-funding-persistence.md) SUPPORTED (2026-09-03)** against memo [**M003**](memos/M003-eth-funding-persistence.md): trailing-12m package net +$0.186/day (4.8% APR) with every pre-registered downside bound holding; carry positive in down-trends; ~49% of hours pinned at HL's interest floor. Caveats that travel: compression (2024H1 +$0.77 → 2026H1 +$0.12/day) and no full bear market in HL's era (K12 — Binance Merge-2022 worst 30d −$0.58/day would breach the bound). Remaining prerequisites: per-venue perp cost calibration; the bot-side K8 margin/liquidation design pass (stress case: sustained −$0.60/day carry reversal). The claim's +$0.22–0.27/day range was window-flattered; the durable central is **+$0.186/day**.

## B3 — Re-screen another chain (Base) with recalibrated gas constants

- **Claim:** E005's screen, re-run with Base cost calibration, finds a pool passing all gates.
- **From:** [E005](../loop/experiments/E005-pool-screen.md) (Arbitrum-only scope was a validity choice, not a finding).
- **Status:** **FOLDED INTO B4** (2026-09-03) — the operator's capital amendment made the chain re-screen part of a larger question; Base is a pre-named secondary scope inside E010.

## B4 — Capital unlocks a venue where the strategy (and the model) can work

- **Claim:** at a $10k reference, some HL-hedgeable Uniswap V3 venue — with Ethereum mainnet now in scope — passes the full E005 gate set with best-arm fees/gamma ≥ 1.0 (model headroom) and net ≥ 10% APR central (target).
- **From:** operator capital amendment 2026-09-03; the mainnet **feeProtocol hypothesis** (Arbitrum 0x44 takes 25% of fees; mainnet fee switch off ⇒ ×1.33 fee income ⇒ E005's 0.86–0.97 near-misses map to 0.87–1.29 — must be read on-chain per pool); memo [**M004**](memos/M004-capital-reopens-the-venue-menu.md) (2026-09-03 — governance record says the Dec-2025 UNIfication + Feb-2026 all-pools extension likely put mainnet at Arbitrum's own 1/4–1/6 haircut, so the ×1.33 case is expected dead per-pool pending the on-chain read; ranked 9-venue screen list + 2 probes, measured mainnet gas envelope construction, JIT/K9 caveat quantified).
- **Why it might work:** the near-misses were dense just under 1.0 and the haircut is exactly the missing margin; mainnet pools are 10–100× deeper (share gates relax at $10k there); gas at $10k is bps-scale, not ruinous.
- **Why it might not:** mainnet JIT liquidity and MEV make the full-share fee-credit assumption *more* optimistic there, not less; the fee switch may have been enabled since; mainnet gas envelopes are volatile and need honest calibration.
- **Both lenses, always:** static-carry APR *and* model headroom (any arm f/g ≥ 1.0) — B4 exists to answer whether the range/timing model thesis gets a venue, not just where carry is highest.
- **Status:** **STAGED → E010** (operator go 2026-09-03). The B2 go/no-go is on hold pending this card's verdict.
