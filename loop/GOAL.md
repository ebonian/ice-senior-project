# Research goal

> The single source for what the research loop is optimizing and how we'll know it's done. "Current focus" moves as verdicts land; the north star changes only by operator decision.

## North star (operator, 2026-08-29)

The full strategy nets **10–20%+ APR** — at current $1,420 capital, **+$0.39–0.78/day** — measured with honest costs, not training-env reward. The arbiter is the bot repo's backtest engine (tracker item D): **Gate 1** reproduces trials T4/T5 per cost line; **Gate 2** shows the IL-vs-fees distribution of a candidate policy clearing the target. See `bot/STRATEGY_TRACKER.md` and `bot/analysis/strategy-review/00-SYNTHESIS.md`.

## This repo's slice

Produce the **range policy** — when to be in position, at what width, when to recenter — that maximizes net carry = LP fees − IL − the costs the policy causes. Every rebalance forces hedge-side execution the model doesn't see; the bot repo perfects the hedge, and the two couple through rebalance frequency.

## Sub-goal ladder

| # | Sub-goal | Status | Decided by |
|---|---|---|---|
| G1 | Know whether the shipped DQN beats the trivial always-in rule in its own env | ✅ done 2026-08-29 — **REFUTED** ([E001](experiments/E001-baseline-race.md)) | E001's pre-registered decision rule |
| G-pool | Find a venue where the family can work: **fees/gamma > 1 with margin** (pool screen, E005) | **CLOSED-as-measured 2026-08-31 — INCONCLUSIVE** ([E005](experiments/E005-pool-screen.md)): no pool passes all gates; watchlist wstETH/WETH 0.01% (+$0.22–0.27/day, fails only the 10%-APR floor) and LINK/WETH 0.05% (f/g 1.20 at honest share). Escalated to operator | E005 decision rule |
| G2 | A policy trained under **honest costs** that does not collapse to never-act, and beats the always-in rule under those costs | **blocked — no valid venue yet** (E003 killed it for ETH/USDC 0.05%: fees/gamma 0.65–0.97, no arm to beat) | in-env eval vs rule, then G3 |
| G3 | That policy clears Gate 2 in the bot backtest at the target APR | open | bot item D engine |

G2's anti-collapse design (bot synthesis §4a / tracker item F): fix **γ≈0.95 first** (γ=0 makes never-act rational the moment costs are honest — the collapse the operator observed was rational under the old setup), cost curriculum (published technique: Karzanov et al 2025 — ramp transaction costs up during training), terminal net-carry reward, warm-start from the always-in rule, and monitor the stay-cash fraction during training as the collapse alarm.

## Standing hypothesis families

- **H-width** — **ANSWERED for ETH/USDC 0.05% (E003, REFUTED at every width ±0.2%→±8.3%)**: the frontier is monotone toward always_cash; fees/gamma 0.65–0.97 regardless of width. Width was never the lever on this pool.
- **H-frequency** — fewer, better rebalances: dwell/hysteresis on recentering vs. IL crystallized per rebalance (bot issue U's buy-high re-mint is one instance; 79% of T5's crystallized IL came from one breakout hour).
- **H-pool** — **ANSWERED for Arbitrum-V3 × HL-hedgeable at $1,420 (E005, INCONCLUSIVE)**: every USD-quoted pool posts fees/gamma 0.63–0.97 regardless of family or width — E003's venue property generalizes. The exceptions are ultra-correlated pairs (wstETH/WETH 36×, degenerate positive-drift gamma) and LINK/WETH at wide width (1.20) — both net-positive only through perp funding carry, at 4.5–7% APR vs the 10% target. Watchlist disambiguation: longer window, per-venue perp cost calibration, funding-regime sensitivity.
- **H-timing** — **CEILING MEASURED on ETH/USDC 0.05% (E006, SUPPORTED)**: a perfect-foresight hour-level in/out policy nets +$6.06/day at ±0.2% under full frozen costs (positive at every envelope point, every month); 6.4% capture reaches the +$0.389/day target. The oracle holds the low-realized-vol hours (median streak 3h) — confirming the operator's low-vol prior directionally — but E006's descriptive section shows Kaufman ER and trailing vol separate held hours at only AUC 0.45–0.53, because next-hour realized vol has ACF(1) ≈ 0.22 while ER measures (persistent) trend efficiency instead. E007 (staged, unwritten) is the causal-signal test; its design must target short-horizon vol prediction, not ER thresholds.
- **H-model-class** — if the DQN family keeps failing reviews, the named alternatives are: rule + tuned thresholds (simplest), policy-gradient, offline RL on trial data. E001 verdict: the shipped DQN destroys value vs the always-in rule even in its own env — and was trained on a different pool than it serves (bot issue V).

## Constraints

- One variable per experiment; decision rules pre-registered ([PROTOCOL.md](PROTOCOL.md)).
- The training env's hedge leg is frictionless — env results are **signal-only**, never quoted as live profitability.
- No live-capital decisions from this repo — anything touching real funds goes through `bot/docs` and the operator (bot ADR 0008).

## Current focus

**E006 is done — SUPPORTED (2026-09-02; [experiments/E006-timing-oracle-bound.md](experiments/E006-timing-oracle-bound.md)) — and the loop remains ESCALATED to the operator, now with a fourth option on the table.** The timing oracle cleared its pre-registered bar: a perfect-foresight in/out policy on ETH/USDC 0.05% nets +$6.06/day at ±0.2% (stage-2 exact, central; +$3.24 pessimistic), positive in all four months, needing only 6.4% capture for the +$0.389/day target. Timing does not close on the control pool — E003's negative always-in average hides a 57%-positive hourly mix. The catch, measured in the same run: the pre-named causal signals (Kaufman ER, trailing vol, 12/24/48h) find the oracle's hours at AUC 0.45–0.53 — near coin-flip — because the oracle is effectively predicting next-hour realized vol (ACF(1) ≈ 0.22). The pre-registered route stages **E007: the causal-signal test**, whose design must clear that headwind (short-horizon vol features, seasonality, cross-venue leads — not ER thresholds). The operator's E005 three-way venue call (accept 5–7% carry venue / re-screen another chain / judge the family) becomes four-way: stay on ETH/USDC 0.05% iff E007 finds a realizable filter clearing ~6–10% capture at ±0.2–0.5%. G2/item-F retrain stays blocked pending the venue decision. No capital moves on an oracle number (bot ADR 0008).
