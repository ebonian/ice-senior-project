---
id: E001
family: H-model-class
date: 2026-08-29
verdict: RUNNING
---

# E001 — the shipped DQN beats an always-in-W10 recenter rule in its own env

## Pre-registration (written before the run)

**Hypothesis** — the shipped DQN checkpoint (simulation_14 lineage; the model `model/` serves on :4001) outperforms a trivial rule — always in position at W10, recenter on out-of-range, never EXIT — on the training env's own objective (net carry).

**The one variable** — the policy only. Same env, same episodes/data, same seeds; no retraining, no env changes.

**Decision rule** — rule ≥ DQN on net carry within noise → **REFUTED** (the model adds no value even in its own env; bot tracker item F retrain is justified and the rule becomes the interim serving candidate). DQN clearly above the rule → **SUPPORTED** (model keeps its slot pending cost-honest confirmation at bot item D). Ambiguous → INCONCLUSIVE, naming what disambiguates.

**Abort criteria** — the served checkpoint cannot be identified or replayed in the plumbing → stop and report; no retrained proxies.

**Method** — simulation_14 episode plumbing (`research/simulation_14/training/hedged_hierarchical_policy.py`); optional secondary arms: the same rule at W20/W4/W6 if width is a trivial parameter. Report lands at `research/simulation_14/analysis/baseline_race/REPORT.md`. Runner: background agent launched 2026-08-29 from the bot-repo session (bot tracker item A).

**Context** — the model audit (`bot/analysis/strategy-review/06-model-audit.md`): shipped weights have γ=0.0 (effectively a one-step bandit); live behaviour looks like a W10 timer (8/8 W10 entries, EXIT on 15/16 in-range ticks); 40/95 train/serve hourly action agreement. The prior leans REFUTED — which is exactly why it gets tested instead of assumed.

## Result

_Pending._

## Verdict

RUNNING.

## Critique

_After results._

## What this changes

G1 in [GOAL.md](../GOAL.md); bot `STRATEGY_TRACKER.md` item A; if REFUTED, item F (anti-collapse retrain) becomes the research focus.
