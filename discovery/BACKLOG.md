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
- **E010 note (2026-09-03, hold unchanged):** at $10k the package's LP-leg share gate dies below ±0.5% width on Arbitrum (measured 1.47%/1.01% at ±0.1%/±0.2%) but survives at ±0.5%–8.3% (0.65%/0.40%/0.29%) netting +$1.47–1.64/day (5.4–6.0% APR) — and the mainnet twin (`0x109830a1…`, share 0.2–0.3% at the same widths) is the deeper home for the identical carry. Still under the 10% bar; K8 margin pass still prerequisite.
- **Progress:** funding-persistence prerequisite **met — [E009](../loop/experiments/E009-funding-persistence.md) SUPPORTED (2026-09-03)** against memo [**M003**](memos/M003-eth-funding-persistence.md): trailing-12m package net +$0.186/day (4.8% APR) with every pre-registered downside bound holding; carry positive in down-trends; ~49% of hours pinned at HL's interest floor. Caveats that travel: compression (2024H1 +$0.77 → 2026H1 +$0.12/day) and no full bear market in HL's era (K12 — Binance Merge-2022 worst 30d −$0.58/day would breach the bound). Remaining prerequisites: per-venue perp cost calibration; the bot-side K8 margin/liquidation design pass (stress case: sustained −$0.60/day carry reversal). The claim's +$0.22–0.27/day range was window-flattered; the durable central is **+$0.186/day**.

- **Operator (iii), 2026-09-03:** deployment *prep* proceeds in parallel (bot-side T1 margin-distance alerting build, per the K8 design doc) — **capital deploys only after E011 (card B5) reports**, so the venue choice is made with the LINK ceiling known.

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
- **Status:** **INCONCLUSIVE ([E010](../loop/experiments/E010-capital-rescreen.md), 2026-09-03).** The feeProtocol mechanism is measured dead (K13 — mainnet/Base at Arbitrum's own haircuts, multiplier 1.0); the K3 venue property is chain-invariant (USD majors 0.503–0.780 at $10k); no venue passes the full gate set. What capital DID buy: mainnet depth makes the share gate trivial, exposing **mainnet LINK/WETH 0.30%** as the one honest f/g ≥ 1.0 venue with real gamma (K14, +3.3% APR best arm) — and exposing the per-swap fee-credit honesty gap on peg pools (K15; mainnet wstETH's +16.6% headline is a wick artifact, durable ~5.5% carry). Part A: no sign flips at $10k. Part B: both Arbitrum watchlist honest arms die the $10k share gate (measured); the wstETH carry is size-invariant at 5.4–6.0% APR. Escalated to the operator per loop PROTOCOL §7.

## B5 — The LINK/WETH 0.30% mainnet timing/width ceiling

- **Claim:** a perfect-foresight in/out+width policy on mainnet LINK/WETH 0.30% — the program's first honest fee-edge venue (E010: f/g 1.10–1.34 at every width, +$0.915/day static best at $10k) — clears the 10–20% APR band ($2.74–5.48/day at $10k) with modelable margin, reviving the range/timing-model thesis on a venue where fees actually beat gamma.
- **From:** [E010 §2](../loop/experiments/E010-capital-rescreen.md) (model-headroom YES; "an E006-style ceiling measurement on THIS pool is the natural next question"); memo [**M005**](memos/M005-link-ceiling-and-two-leg-funding.md) (committed 2026-09-03: constraints, two-leg hedge read from the engine, LINK floor-pin pre-work, four pre-named measurements C1–C4).
- **Why it might work:** the static wide arm already nets +3.3% APR; E006 showed hour-picking on a *losing* pool found +$6.06/day of structure — on a pool whose every width is fee-positive, the held-hours surface starts above water; worst-month f/g 0.70 means timing has real winter to dodge.
- **Why it might not:** E007/E008's lesson — a ceiling without a causal key is a museum piece; LINK's two-leg hedge (LINK-PERP + ETH-PERP) doubles funding/execution surfaces; mainnet gas prices out narrow/frequent switching (E010 §6).
- **Status:** **STAGED → E011** (operator go 2026-09-03, part of the (iii) parallel decision).
