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
| G2 | A policy trained under **honest costs** on the served pool's data (tickSpacing=10 — bot issue V) that does not collapse to never-act, and beats the rule under those costs | open — **current focus** | in-env eval vs rule, then G3 |
| G3 | That policy clears Gate 2 in the bot backtest at the target APR | open | bot item D engine |

G2's anti-collapse design (bot synthesis §4a / tracker item F): fix **γ≈0.95 first** (γ=0 makes never-act rational the moment costs are honest — the collapse the operator observed was rational under the old setup), cost curriculum (published technique: Karzanov et al 2025 — ramp transaction costs up during training), terminal net-carry reward, warm-start from the always-in rule, and monitor the stay-cash fraction during training as the collapse alarm.

## Standing hypothesis families

- **H-width** — current widths may be structurally too narrow: W4–W20 ≈ ±0.4–2%, and T5 earned **$0.72 of fees per $1.00 of IL** (fees/IL = 0.72 < 1, T5 corrected). The Strategic Liquidity Provision literature places profitable ranges far wider. Test wider ranges in-env and in the backtest before trusting either.
- **H-frequency** — fewer, better rebalances: dwell/hysteresis on recentering vs. IL crystallized per rebalance (bot issue U's buy-high re-mint is one instance; 79% of T5's crystallized IL came from one breakout hour).
- **H-pool** — ETH/USDC 0.05% at this capital may be structurally thin. The backtest engine is pool-parameterized (bot item D), so other pools can be screened offline. **Live trials stay on ETH/USDC 0.05%** until the engine is trusted — Gate 1 ground truth exists only for this pool.
- **H-model-class** — if the DQN family keeps failing reviews, the named alternatives are: rule + tuned thresholds (simplest), policy-gradient, offline RL on trial data. E001 verdict: the shipped DQN destroys value vs the always-in rule even in its own env — and was trained on a different pool than it serves (bot issue V).

## Constraints

- One variable per experiment; decision rules pre-registered ([PROTOCOL.md](PROTOCOL.md)).
- The training env's hedge leg is frictionless — env results are **signal-only**, never quoted as live profitability.
- No live-capital decisions from this repo — anything touching real funds goes through `bot/docs` and the operator (bot ADR 0008).

## Current focus

**E002 — Gate 1: the engine must reproduce our own trials** (bot item D phases 1–2). Every open question — width, rebalance frequency, rule-vs-model, other pools — is answerable only by a cost-honest engine we trust, and trust = reproducing corrected T4/T5 per cost line. Behind it, pre-committed: **E003** = cost-honest width race (re-race E001's arms plus wider-than-W20 widths with measured costs; decides H-width and bot Gate 2), then the branch — a width clears +$0.39–0.78/day → item F retrain (tickSpacing=10 data, anti-collapse design, must beat the winning rule through the trusted engine); no width clears it → H-pool screening / structural conversation, not retraining. Item F waits for that branch; item C (parity) is folded into F's serving-path scoring (operator, 2026-08-29) — issue V explains most of the 40/95 gap and there is no model worth re-verifying until F produces one.
