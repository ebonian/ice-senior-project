---
id: E001
family: H-model-class
date: 2026-08-29
verdict: REFUTED
---

# E001 — the shipped DQN beats an always-in-W10 recenter rule in its own env

## Pre-registration (written before the run)

**Hypothesis** — the shipped DQN checkpoint (simulation_14 lineage; the model `model/` serves on :4001) outperforms a trivial rule — always in position at W10, recenter on out-of-range, never EXIT — on the training env's own objective (net carry).

**The one variable** — the policy only. Same env, same episodes/data, same seeds; no retraining, no env changes.

**Decision rule** — rule ≥ DQN on net carry within noise → **REFUTED** (the model adds no value even in its own env; bot tracker item F retrain is justified and the rule becomes the interim serving candidate). DQN clearly above the rule → **SUPPORTED** (model keeps its slot pending cost-honest confirmation at bot item D). Ambiguous → INCONCLUSIVE, naming what disambiguates.

**Abort criteria** — the served checkpoint cannot be identified or replayed in the plumbing → stop and report; no retrained proxies.

**Method** — simulation_14 episode plumbing; report at `research/simulation_14/analysis/baseline_race/REPORT.md`. Runner: background agent launched 2026-08-29 from the bot-repo session (bot tracker item A). Prior leaned REFUTED (γ=0.0 weights, live "W10 timer" behaviour — bot 06-model-audit) — which is exactly why it got tested instead of assumed.

## Result

Run 2026-08-29; code, results JSON/CSV and full report at `research/simulation_14/analysis/baseline_race/` (commit `7f1b9e9`). Checkpoint identified as the served model via `model/weights/default.json` (md5 `745d67c6…`). Determinism verified bit-identical on re-run. ETH/USDC 0.05%, four non-overlapping 730-bar monthly episodes, $1,000 capital, seed 42 — mean net PnL/month:

| Arm | Mean ± σ | Δ vs DQN | Episode wins |
|---|---|---|---|
| always_in_w4 | $435.70 ± 214.93 | +$251.18 | 4/4 |
| always_in_w6 | $369.81 ± 182.87 | +$185.29 | 4/4 |
| always_in_w10 | $266.48 ± 144.74 | +$81.97 | 3/4 |
| **shipped_dqn** | **$184.51 ± 126.65** | — | — |
| paper_w4_threshold | $176.65 ± 98.51 | −$7.86 | 2/4 |
| always_in_w20 | $149.34 ± 109.43 | −$35.17 | 1/4 |
| always_cash | $0.00 | −$184.51 | 0/4 |

Rolling sweep (14 overlapping windows, stride 168): W4 +$292.44 (13/14 wins), W6 +$219.80 (13/14), W10 +$37.12 (10/14). Mechanism: the DQN spends $118.08/mo of tx cost to earn $744 of fees; W10 spends $89.56 to earn $972. The DQN requests go_cash 92.8×/month (rules: 0), dropping time-in-range to 46.5% vs 67.1%.

**Discovery beyond the pre-registered question:** the shipped checkpoint was **trained on a different pool than it serves** — ETH/USDT 0.3% Ethereum mainnet (`tickSpacing=60`). The weights landed in `b208379` (2026-04-17 16:25) while `prepare_interval_data` still read `pool_config_eth_usdt_0p3.csv`; the switch to ETH/USDC 0.05% (`tickSpacing=10`) came ten hours later in `f94b312`, and the blob was never rebuilt. Width actions are denominated in tick-spacings, so `ENTER_W10` = ±3.05% in training but ±0.50% in production — 6.1× narrower. This explains the audit's 40/95 train/serve disagreement and the live "W10 timer". On its own training pool, in-sample, the DQN is **net negative** (−$84.24/episode), losing 0/2 episodes and 0/11 rolling windows to every arm including always-cash. The published simulation_14 gate numbers describe the training pool and are not reproducible on USDC data (best joint fit off by $979.50 across 193 candidate alignments). Filed as **bot issue V**.

**Addendum 2026-08-29 (E002 F1):** the training env pays LP fees with no Uniswap protocol fee, so every arm's fee income here is ×1.333 overstated (bot issue W). Under a naive 0.75 fee haircut the rule stays strictly ahead (W10 ≈ +$23/mo net vs DQN ≈ −$1.5/mo) — the verdict stands; the absolute PnL levels do not.

## Verdict

**REFUTED**, per the pre-registered rule: always-in-W10 ≥ DQN (+$81.97/mo, 3/4 episodes). The robust claim is *"the learned exit policy destroys value"* — NOT *"W4 is the right width"* (critique 2).

## Critique

1. **Proxy or goal?** Proxy — env net carry with a frictionless hedge. The goal check is Gate 2 (bot item D).
2. **Would it survive Gate 2?** The DQN-adds-no-value claim, yes — the DQN pays the same unmodeled costs plus 92.8 go_cash round-trips/month. The width *ranking*, unknown: winning rules rebalance 240–455×/month; at $0.75–1.25 per flatten/rebuild leg that is $180–570/mo of unmodeled hedge cost and could invert W4 > W10.
3. **Env faithful enough?** For this claim yes — beating the DQN in the env it was trained for was the point. For live profitability no (always_cash scores exactly $0.00).
4. **Exactly one variable?** Yes — policy only.
5. **Symptom-fix of the previous iteration?** No — first iteration.

## What this changes

- **G1 closed** ([GOAL.md](../GOAL.md)): the model as shipped adds no value; item F's retrain is the causal fix.
- **Item F re-scoped by the pool mismatch**: any retrain MUST use tickSpacing=10 ETH/USDC data (bot issue V) — the old pipeline reproduces the bug.
- **Escalated to operator**: no future live trial serves the shipped checkpoint as-is; interim = always-in-W10 (defensible over W4: 47% fewer position changes) if a rule is served before F lands.
- simulation_14's published gate numbers ($550 mean, beat-paper 3/4) are never quoted as evidence about the served pool.
- **Next experiment**: once bot item D's engine passes Gate 1, re-race the width arms under honest costs — that experiment decides H-width.
