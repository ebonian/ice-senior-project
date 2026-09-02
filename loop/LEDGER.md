# Experiment ledger

> Append-only index of loop iterations — one row per experiment (E) or review (R); details live in `experiments/`. **A row without a file, or a file without a row, is a bug.**

| ID | Date | Family | Claim (short) | Verdict | File |
|---|---|---|---|---|---|
| E001 | 2026-08-29 | H-model-class | The shipped DQN beats an always-in-W10 recenter rule in its own training env | **REFUTED** | [E001](experiments/E001-baseline-race.md) |
| E002 | 2026-08-29 | Gate-1-instrumentation | The backtest engine can reproduce T4/T5 per cost line within tolerance | **SUPPORTED** | [E002](experiments/E002-gate1-trial-reproduction.md) |
| E003 | 2026-08-29 | H-width | Some always-in width nets ≥ +$0.39/day under honest costs (central envelope) | **REFUTED** (strongest clause: no arm ≥ $0 even optimistic) | [E003](experiments/E003-cost-honest-width-race.md) |
| E004 | 2026-08-29 | Gate-1-instrumentation | Report 01's basket-delta derivation, not the engine's chain read, explains the E002 mismatch | **T5 SUPPORTED · T4 INCONCLUSIVE** (cause located: issue-X boundary) | [E004](experiments/E004-basket-delta-reconciliation.md) |
| E005 | 2026-08-30 | H-pool | Some Arbitrum V3 pool, HL-hedgeable, pays fees/gamma ≥ 1.5 with margin at our size | **INCONCLUSIVE** (watchlist: wstETH/WETH 0.01% fails only the +$0.389/day floor at +$0.22–0.27/day; LINK/WETH 0.05% f/g 1.20 honest-share; all USD-quoted pools 0.63–0.97) | [E005](experiments/E005-pool-screen.md) |
| E006 | 2026-09-02 | H-timing | A perfect-foresight in/out timing policy on ETH/USDC 0.05% clears the target with modelable margin | **SUPPORTED** (stage-2 exact oracle +$6.06/day at ±0.2%, +$3.72 at ±0.5%; 6.4% capture reaches target — but named causal signals separate at AUC ≤ 0.53) | [E006](experiments/E006-timing-oracle-bound.md) |

## Closed sub-goals

_None yet._
