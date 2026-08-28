# CLAUDE.md — Llaminet Research

## Pool naming convention (read before renaming anything)

The target pool is **ETH/USDC 0.05%** on Arbitrum (`0xC6962004f452bE9203591991D15f6b388e09E8D0`). Pool-side code, B2 paths (`eth_usdc_0p05/...`), and docs say **USDC**. The only place **USDT** appears is the Binance price reference: Binance lists no ETH/USDC spot pair, so `ETHUSDT` is used as the off-chain series. Do **not** rename either direction.

> Some older `dune_pipeline/` exports are named `eth_usdt_0p3` — those are genuinely a different pool (0.3% tier) from early exploration, not a naming slip.

## What this repo is

The **offline** half of Llaminet: training, evaluation and backtesting of RL agents for delta-hedged concentrated liquidity. Nothing here runs in production and nothing here holds funds.

One of three repos:

```
~/developments/llaminet/
├── research/   this repo — trains and evaluates models
├── model/      serves the shipped model over HTTP (:4001)
└── bot/        executes on-chain + on Hyperliquid
```

**The cross-repo architecture is documented once, in `bot/docs/architecture/SYSTEM.md`.** Read it before touching a repo boundary. Live strategy status, the bug catalogue, and trial results live in `bot/STRATEGY_TRACKER.md` and `bot/docs/`.

## The research loop

Model/strategy research runs as a **closed loop** with durable memory: hypothesis → one-variable change → test → pre-registered verdict → self-critique, with a mandatory step-back review when a hypothesis family keeps failing. The loop's state lives in [`loop/`](loop/):

- [`loop/GOAL.md`](loop/GOAL.md) — what the loop is optimizing, the sub-goal ladder, standing hypothesis families
- [`loop/PROTOCOL.md`](loop/PROTOCOL.md) — the iteration procedure; **read it and execute exactly one iteration** when asked to “run a research-loop iteration”
- [`loop/LEDGER.md`](loop/LEDGER.md) — append-only index of every experiment and review

An experiment that grows into a full training run still becomes `research/simulation_N+1` (append-only convention below); its `E<NNN>` file wraps and links it.

## Layout

| Path | Purpose |
|---|---|
| `loop/` | **The research loop** — goal, protocol, experiment ledger (see above) |
| `research/simulation_N/` | One numbered experiment each — `README.md`, `CONFIG.md`, `PLAN.md`, training and eval code |
| `research/simulation_14/` | **The shipped lineage.** Three-Head Double-Dueling DQN v3, multi-timeframe, mask-fixed walk-forward |
| `research/data/`, `research/pull-data/` | Training data and its collection |
| `kongtrae/` | Shared model definition, training and inference code |
| `backtest_model_server/` | Backtest harness against a model server (has its own `CLAUDE.md`) |
| `dune_pipeline/`, `data_collector/` | Pool data extraction — Dune exports, poolfish exploration |
| `checkpoints_paper/`, `eval_logs_paper/`, `best_model_paper/` | Paper-reproduction baselines the agents are measured against |
| `archive/` | Superseded experiments |
| `UPLOAD_MODEL.md` | **The handoff doc** — how a trained model reaches `model/` |

Reference papers sit at the repo root as PDFs (Uniswap V3 whitepaper, adaptive LP with deep RL, IL hedging, strategic liquidity provision).

## Conventions

### Experiments are append-only

A new idea becomes `simulation_N+1`. **Do not rewrite an existing simulation directory** — published numbers must stay reproducible, and results from earlier simulations are cited in `bot/`'s decision log and trial reports.

Each simulation carries its own `README.md` with results. `CONFIG.md` and `PLAN.md` where the experiment warranted them.

### Gates before shipping

A model is characterised by **walk-forward cross-validation** across folds, and reported against two baselines: always-cash, and the paper's W4 threshold rule. The gate language used throughout:

| Gate | Meaning |
|---|---|
| **pass** | Beats the paper rule on a majority of folds |
| **candidate** | Beats it on some folds |
| **comparison_candidate** | Does not beat it; kept for comparison |

`simulation_14_1h` (fold 0) is the only **pass** and the only model in production. Report mean, median and worst fold — not just the best. A single strong fold has been misleading here before.

### Promoting a model

Follow `UPLOAD_MODEL.md` exactly. It specifies checkpoint formats, exact layer names per architecture, and the metadata JSON schema. A `.pth` needs a matching `.json` of the same name.

Then update `model/CLAUDE.md`'s strategy-slot table, and record the promotion in `bot/docs/decisions/` — a model change alters the bot's behaviour, and trial results are only interpretable against a known model version.

## Environment

Nix flakes. Note the global `LD_LIBRARY_PATH` caveat: dev shells must `unset LD_LIBRARY_PATH` in `shellHook`, or the flake's newer glibc leaks into the system `ssh` and breaks SSH-based git operations inside the shell.
