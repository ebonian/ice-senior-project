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
| G-pool | Find a venue where the family can work: **fees/gamma > 1 with margin** (pool screen, E005) | open — **next** | E005 decision rule |
| G2 | A policy trained under **honest costs** that does not collapse to never-act, and beats the always-in rule under those costs | **blocked — no valid venue yet** (E003 killed it for ETH/USDC 0.05%: fees/gamma 0.65–0.97, no arm to beat) | in-env eval vs rule, then G3 |
| G3 | That policy clears Gate 2 in the bot backtest at the target APR | open | bot item D engine |

G2's anti-collapse design (bot synthesis §4a / tracker item F): fix **γ≈0.95 first** (γ=0 makes never-act rational the moment costs are honest — the collapse the operator observed was rational under the old setup), cost curriculum (published technique: Karzanov et al 2025 — ramp transaction costs up during training), terminal net-carry reward, warm-start from the always-in rule, and monitor the stay-cash fraction during training as the collapse alarm.

## Standing hypothesis families

- **H-width** — **ANSWERED for ETH/USDC 0.05% (E003, REFUTED at every width ±0.2%→±8.3%)**: the frontier is monotone toward always_cash; fees/gamma 0.65–0.97 regardless of width. Width was never the lever on this pool.
- **H-frequency** — fewer, better rebalances: dwell/hysteresis on recentering vs. IL crystallized per rebalance (bot issue U's buy-high re-mint is one instance; 79% of T5's crystallized IL came from one breakout hour).
- **H-pool** — **now the active family** (E003 routed here). Screen criterion: fees/gamma > 1 with margin, per pool, from swap data + the Gate-1-trusted engine. The engine is pool-parameterized; live-trial venue changes are operator decisions.
- **H-model-class** — if the DQN family keeps failing reviews, the named alternatives are: rule + tuned thresholds (simplest), policy-gradient, offline RL on trial data. E001 verdict: the shipped DQN destroys value vs the always-in rule even in its own env — and was trained on a different pool than it serves (bot issue V).

## Constraints

- One variable per experiment; decision rules pre-registered ([PROTOCOL.md](PROTOCOL.md)).
- The training env's hedge leg is frictionless — env results are **signal-only**, never quoted as live profitability.
- No live-capital decisions from this repo — anything touching real funds goes through `bot/docs` and the operator (bot ADR 0008).

## Current focus

**Pre-register E005 — the pool screen** (pending operator go; live-trial and capital consequences are operator calls). E003 refuted H-width on ETH/USDC 0.05% at the strongest clause: no width clears $0/day even under the optimistic envelope; fees/gamma = 0.65–0.97 across a 40× width range, and gamma is rehedge-frequency-invariant — the shortfall is the venue's, not the rule's. So the question becomes: **which pool (if any) pays > 1.5–1.7× its gamma in fees at our size?** E005 screens candidate pools (other fee tiers, other pairs, other chains the engine's data layer can reach) on exactly that ratio plus liquidity-depth sanity, using the same engine. Item F retrain is dead until a venue passes. T6-as-planned is escalated to the operator.
