# Experiment ledger

> Append-only index of loop iterations — one row per experiment (E) or review (R); details live in `experiments/`. **A row without a file, or a file without a row, is a bug.**

| ID | Date | Family | Claim (short) | Verdict | File |
|---|---|---|---|---|---|
| E001 | 2026-08-29 | H-model-class | The shipped DQN beats an always-in-W10 recenter rule in its own training env | **REFUTED** | [E001](experiments/E001-baseline-race.md) |
| E002 | 2026-08-29 | Gate-1-instrumentation | The backtest engine can reproduce T4/T5 per cost line within tolerance | **SUPPORTED** | [E002](experiments/E002-gate1-trial-reproduction.md) |

## Closed sub-goals

_None yet._
