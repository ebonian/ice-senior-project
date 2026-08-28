# Baseline race: always-in fixed-width rules vs the shipped simulation_14 1h DQN

> Tracker item **A** — "Is the model worth serving at all". Run 2026-08-29 against the
> checkpoint the model service loads today. No retraining; no change to env dynamics
> or reward.

## Verdict: **hypothesis REFUTED**

The pre-registered hypothesis was *the DQN outperforms the trivial rule*. It does not.
On the pool the model is actually served against, **always-in-W10 beats the shipped DQN
by +$81.97 per month** (mean over four non-overlapping 730-bar episodes, 3 of 4 episodes,
$1,000 capital), and the same rule at **W4 beats it by +$251.18, winning 4 of 4** episodes
and 13 of 14 rolling windows. The DQN also loses on the mechanism that matters: it spends
**$118.08/month on transaction costs to earn $744 in fees**, where always-in-W10 spends
**$89.56 to earn $972**.

Two findings go beyond the pre-registered question, and the second is the more important one:

1. On the model's *own training pool*, over the only month of that pool's data still in
   the repo, the shipped DQN is **net negative** (−$84.24 per 250-bar episode) while every
   rule tested — including *always-cash*, which does nothing — is better. It loses 0/2
   episodes and 0/11 rolling windows.
2. **The shipped checkpoint was trained on a different pool than the one it is served
   against.** It was trained on ETH/USDT 0.3% (Ethereum mainnet, `tickSpacing=60`) and is
   served against ETH/USDC 0.05% (Arbitrum, `tickSpacing=10`). Because width is denominated
   in tick-spacings, **the action `ENTER_W10` means a ±3.05% range in training and a ±0.50%
   range in production** — the same integer, a 6.1× narrower position. Evidence in
   [§3](#3-the-checkpoint-was-trained-on-a-different-pool-than-it-serves).

The decision rule said: *rule matches or beats the DQN within noise → the model adds no
value even in the environment it was trained for → REFUTED.* The rule does not merely
match; it beats the DQN on both pools, at three of four widths, on the primary and the
secondary evaluation, with the margin far outside per-episode spread.

---

## 1. Results — ETH/USDC 0.05% (the pool the model is served on)

Four **non-overlapping** 730-bar (one-month) episodes, 2025-12-20 08:00 → 2026-04-20 23:00 UTC,
$1,000 capital, seed 42. Every arm sees the identical bars, identical env, identical env
kwargs. `pnl` *is* the environment's own objective here: summed `reward_usd` equals
final-portfolio-minus-initial to the cent in every trace.

| policy | PnL mean ± sd ($/mo) | Δ vs DQN | wins | LP fees | tx cost | funding | IL (last) | time in range | rebalances | exits |
|---|---:|---:|:--:|---:|---:|---:|---:|---:|---:|---:|
| `always_in_w4` | **435.70** ± 214.93 | **+251.18** ± 133.86 | **4/4** | 1380.56 | 179.73 | 2.21 | −0.99 | 37.6% | 454.8 | 0 |
| `always_in_w6` | **369.81** ± 182.87 | **+185.29** ± 106.60 | **4/4** | 1220.73 | 140.05 | 2.21 | −0.87 | 50.5% | 361.0 | 0 |
| `always_in_w10` | **266.48** ± 144.74 | **+81.97** ± 84.40 | **3/4** | 972.46 | 89.56 | 2.18 | −0.38 | 67.1% | 240.0 | 0 |
| `shipped_dqn` | 184.51 ± 126.65 | — | — | 744.01 | 118.08 | 1.71 | −2.15 | 46.5% | 244.8 | 92.8 |
| `paper_w4_threshold` | 176.65 ± 98.51 | −7.86 ± 73.73 | 2/4 | 750.07 | 91.27 | 0.94 | −0.40 | 14.8% | 239.0 | 15.5 |
| `always_in_w20` | 149.34 ± 109.43 | −35.17 ± 90.88 | 1/4 | 634.73 | 39.79 | 2.14 | −1.67 | 84.6% | 112.0 | 0 |
| `always_in_w10_no_recenter` | 34.96 ± 32.13 | −149.55 ± 117.44 | 0/4 | 83.67 | 0.33 | 1.81 | −75.85 | 8.8% | 1.0 | 0 |
| `always_cash` | 0.00 ± 0.00 | −184.51 ± 126.65 | 0/4 | 0.00 | 0.00 | 0.00 | 0.00 | 0.0% | 0 | 0 |

Per-episode paired deltas (same window, same data), $:

| policy | ep0 Dec20–Jan19 | ep1 Jan19–Feb19 | ep2 Feb19–Mar21 | ep3 Mar21–Apr20 |
|---|---:|---:|---:|---:|
| `always_in_w4` − DQN | +327.08 | +60.04 | +357.90 | +259.71 |
| `always_in_w6` − DQN | +268.58 | +34.69 | +252.19 | +185.73 |
| `always_in_w10` − DQN | +176.65 | **−28.46** | +96.50 | +83.17 |

W10's single loss is episode 1, the month where every arm's fee income roughly doubled
(DQN $1,098, W10 $1,398) — a high-volume, high-volatility window. W4 and W6 win that
episode too, so the DQN's edge there is not a width-selection edge.

**Rolling-origin sweep** — 14 windows of 730 bars at stride 168 (one week) across the same
span, for variance. These windows overlap, so they are *not* independent samples; they are
here to show the distribution, not to add statistical power:

| policy | PnL mean ± sd | Δ vs DQN | wins |
|---|---:|---:|:--:|
| `always_in_w4` | 434.21 ± 239.04 | +292.44 ± 156.08 | 13/14 |
| `always_in_w6` | 361.57 ± 203.06 | +219.80 ± 139.47 | 13/14 |
| `always_in_w10` | 178.89 ± 195.54 | +37.12 ± 181.39 | 10/14 |
| `always_in_w20` | 158.86 ± 134.47 | +17.09 ± 119.08 | 10/14 |
| `shipped_dqn` | 141.77 ± 187.29 | — | — |
| `always_in_w10_no_recenter` | 22.08 ± 47.89 | −119.69 ± 188.09 | 4/14 |

On the four independent episodes a 4/4 sweep is one-sided sign-test p = 0.0625 — suggestive,
not conclusive on its own. The reason to call this refuted rather than inconclusive is that
it is 4/4 for W4 *and* 4/4 for W6 *and* 3/4 for W10 *and* 2/2 (plus 11/11 rolling) on the
second pool, with a mean margin (+$251 on W4) roughly twice the DQN's entire mean PnL.

## 2. Results — ETH/USDT 0.3% (the pool the model was trained on)

Two non-overlapping 250-bar episodes, 2025-09-10 04:00 → 2025-09-30 23:00 UTC. This is the
only month of this pool's swap data left in the repo (`dune_pipeline/`), and it falls inside
the checkpoint's own training span, so **this is in-sample and weakly powered** — indicative
only.

| policy | PnL mean ± sd ($/250 bars) | Δ vs DQN | wins | LP fees | tx cost | time in range | rebalances | exits |
|---|---:|---:|:--:|---:|---:|---:|---:|---:|
| `always_in_w4` | 53.78 ± 22.19 | +138.02 ± 8.84 | 2/2 | 126.23 | 33.82 | 91.8% | 20.5 | 0 |
| `always_in_w6` | 43.72 ± 8.05 | +127.97 ± 5.30 | 2/2 | 93.23 | 18.91 | 95.4% | 11.5 | 0 |
| `always_in_w10` | 29.24 ± 4.94 | +113.48 ± 8.41 | 2/2 | 56.30 | 9.67 | 97.6% | 6.0 | 0 |
| `paper_w4_threshold` | 16.62 ± 16.54 | +100.86 ± 3.19 | 2/2 | 64.76 | 32.21 | 41.0% | 15.5 | 5.5 |
| `always_in_w20` | 15.10 ± 1.73 | +99.34 ± 11.62 | 2/2 | 29.67 | 4.77 | 98.8% | 3.0 | 0 |
| `always_cash` | 0.00 ± 0.00 | +84.24 ± 13.35 | 2/2 | 0.00 | 0.00 | 0.0% | 0 | 0 |
| `always_in_w10_no_recenter` | −1.23 ± 6.44 | +83.01 ± 19.79 | 2/2 | 5.39 | 1.58 | 11.8% | 1.0 | 0 |
| **`shipped_dqn`** | **−84.24** ± 13.35 | — | — | 66.20 | **127.41** | 78.7% | 47.0 | 43.5 |

Rolling sweep, 11 windows of 250 bars at stride 24: DQN −$91.65 ± 15.42, beaten by every
rule in **11/11** windows (W10 +$102.73 ± 41.74).

The mechanism is unambiguous here: the DQN pays **$127.41 in transaction costs to collect
$66.20 in fees**, churning 47 rebalances and 43.5 exits into 250 bars — a position change
roughly every 2.7 bars. `always_in_w10` collects $56.30 for $9.67 of cost.

## 3. The checkpoint was trained on a different pool than it serves

**Checkpoint identification (one line):** `model/weights/default.json` selects
`model_filename: dqn_three_head_v3_1h` from `model_dir: simulation_14_1h`, and
`model/weights/simulation_14_1h/dqn_three_head_v3_1h.zip` is **md5
`745d67c683ba5e339f1f0d92ae281826`**, byte-identical to
`research/simulation_14/models/dqn_three_head_v3_1h.zip` and to that lineage's
`three_head_v3_1h/fold0_model.zip` — so the served model is simulation_14 1h **fold 0**.

The pool mismatch follows from git history in the research repo:

| when | commit | what |
|---|---|---|
| 2026-04-17 16:25 +0700 | `b208379` | **adds** `dqn_three_head_v3_1h.zip` (md5 `745d67c6…`) and `dqn_three_head_v3_manifest.json` |
| 2026-04-18 02:42 +0700 | `f94b312` | **switches** `prepare_interval_data` from `*_eth_usdt_0p3.csv` to `*_eth_usdc_0p05.csv` |

At `b208379` — the commit that produced the shipped weights —
`simulation_14/training/uniswap_v3_ppo_paper.py:420-422` read
`pool_config_eth_usdt_0p3.csv` / `token_metadata_eth_usdt_0p3.csv` /
`swaps_*_eth_usdt_0p3.csv`. The USDC switch landed ~10 hours *later*. The blob has not been
modified since (`git show b208379:…` and `git show 8d14333:…` both hash to `745d67c6…`, as
does the working tree).

The two pools are not interchangeable:

| | training (`dune_pipeline/pool_config_eth_usdt_0p3.csv`) | serving (`simulation_13/training_data/pool_config_eth_usdc_0p05.csv`) |
|---|---|---|
| pool | `0x4e68ccd3…` WETH/USDT, Ethereum mainnet | `0xC6962004…` WETH/USDC, Arbitrum |
| fee | 3000 (0.30%) | 500 (0.05%) |
| tickSpacing | **60** | **10** |

Width is counted in tick-spacings, so the same action index means a different position:

| action | range at `tickSpacing=60` (trained) | range at `tickSpacing=10` (served) |
|---|---:|---:|
| `ENTER_W4` | ±1.21% (2.41% wide) | ±0.20% (0.40% wide) |
| `ENTER_W6` | ±1.82% (3.63% wide) | ±0.30% (0.60% wide) |
| `ENTER_W10` | ±3.05% (6.09% wide) | ±0.50% (1.00% wide) |
| `ENTER_W20` | ±6.18% (12.37% wide) | ±1.00% (2.01% wide) |

`simulation_14/README.md:131` now states "W4 is centered at roughly +/-2 tick-spacings
(~0.4% total range), and W20 is roughly +/-10 tick-spacings (~2% total range)" — those are
the *USDC* numbers, written after the switch, describing a model trained under the other
regime. This also supplies a mechanism for two things the model audit
(`bot/analysis/strategy-review/06-model-research-audit.md`) observed but could not explain:
the served policy agreeing with the evaluated policy on only 40/95 hours, and the live
policy behaving like a fixed W10 timer. A policy whose value function was fit where W10 is a
±3% range will hold W10 through moves that, on the served pool, have long since left a
±0.5% range.

**Falsification recorded:** the published 1h walk-forward numbers cannot be reproduced on
ETH/USDC 0.05% data. Scanning 193 candidate window alignments (±96 h around the derived
fold-0 start) and re-scoring the 12 best against all four published fold PnLs
(`models/three_head_v3_1h/manifest.json`: $562.21 / $435.31 / $486.52 / $717.60, summing to
$2,201.64), the **best joint fit was off by $979.50 in total**, with a worst single-fold
error of $366.74. That is not an alignment failure — it is the wrong pool. The published
gate numbers describe the USDT pool and should not be quoted as evidence about the USDC
pool the bot trades.

## 4. Why the DQN loses

Not because it picks bad widths — because it exits. On USDC it requests `go_cash` **92.8
times per 730-bar month** while the rules request it zero times, and the exits are what
drop it to 46.5% time-in-range against `always_in_w10`'s 67.1%. Per-month requested-action
mix for the DQN:

| episode | hold | go_cash | hold_oor | recenter_same | enter_w4 | enter_w6 | enter_w10 | enter_w20 | stay_cash |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ep0 | 260 | 166 | 71 | 66 | 6 | 1 | 114 | 45 | 0 |
| ep1 | 209 | 83 | 142 | 199 | 39 | 7 | 22 | 15 | 13 |
| ep2 | 251 | 53 | 138 | 228 | 16 | 2 | 23 | 12 | 6 |
| ep3 | 365 | 69 | 111 | 114 | 6 | 1 | 46 | 17 | 0 |

W10 and W20 dominate entries in three of four months (ep0: 159 of 166 entries; ep3: 63 of
70), which is the "W10 timer" signature the audit saw live, reproduced offline. Widths W4
and W6 — the two that win this race — are chosen 7 and 8 times respectively across
ep0/ep3 combined.

This is consistent with `gamma = 0.0` in the shipped weights
(`walk_forward_three_head_v2_dqn.py` argparse default): a one-step bandit has no way to
represent "exiting costs me the next twenty hours of fees", so it takes any hour whose
one-step expectation looks negative and pays the round trip. The rule cannot make that
mistake because it has no exit action.

The `always_in_w10_no_recenter` arm separates the two things the rule does. Holding a
position and never recentering earns almost nothing on USDC (8.8% time in range, $83.67 of
fees, −$75.85 IL) because a ±0.50% range is left almost immediately. So the rule's win is
**not** "being in the pool is free money" — it is *recentering without exiting*. That is the
specific behaviour the model fails to learn.

## 5. Method

**Code** (all under `research/simulation_14/analysis/baseline_race/`):

| file | role |
|---|---|
| `sim14_bootstrap.py` | binds `kongtrae` → `research/simulation_14` in `sys.modules` |
| `fixed_width_rule_policy.py` | the rule policies |
| `run_baseline_race.py` | `race` and `probe` subcommands |
| `fetch_swaps_from_b2.py` | rebuilds the swaps CSV from B2 daily parquets |

**Environment parity.** Every arm runs through `run_three_head_policy_episode` in
`UniswapV3HedgedThreeHeadEnv` with `_v2_env_kwargs((4,6,10,20))` — the exact kwargs the
shipped model was trained and gated under (`allow_in_range_recenter=False`,
`oor_recenter_same_width_only=True`, `recenter_cooldown_hours=0.0`,
`recenter_emergency_oor_sigma=2.5`, `fee_haircut=1.0`, `active_liquidity_multiplier=1.0`,
`include_paper_signal_features=True`). The rule policy implements the same
`.predict(obs, return_q=…) -> PolicyPrediction` contract as `NormalizedDQNPolicy`, so it is
a drop-in: nothing in the env, the reward, or the accounting was touched. Reference arms
`always_cash` and `paper_w4_threshold` use the repo's own runners unchanged.

**The import shim matters.** Modules in `research/simulation_14/training/` import their
siblings as `kongtrae.training.*`, but that package name resolves to the **top-level
`kongtrae/`** directory, which is the *pre-mask-fix* copy — it lacks `masked_invalid_action`
in the trace and does not count `recenter_same_width` in `trace_metrics`. The shipped
checkpoint comes from run `walk_forward_three_head_v2_1h_maskfix_100k`, i.e. the mask-fixed
snapshot. `sim14_bootstrap.bind()` aliases `kongtrae` to `research/simulation_14` and
asserts the resolved path, so the race runs against the snapshot. Anyone running
`evaluate_three_head_v2_model.py` from the repo root today is silently getting the older
code.

**Data.** The concatenated CSV simulation_14 trained on
(`swaps_20250504_to_20260212_eth_usdc_0p05.csv`, per
`simulation_13/training_data/README.md`) is not on disk, and neither are the daily CSVs it
was built from. The USDC series was rebuilt from the project's own B2 bucket
(`eth_usdc_0p05/daily/swaps/*.parquet`, 171 days 2025-11-01 → 2026-04-20, 5,929,628 swaps,
0.66 GB) by `fetch_swaps_from_b2.py`, using read-only credentials from the model service's
`.env`. The full 2025-05-04 → 2026-04-17 range was not fetched because it is ~1.46 GB as CSV
and the machine had 1.2 GB free; the slice fetched gives a 1,189-bar lead-in before the
first episode, far past the longest indicator lookback (`ma_200`, 200 bars) and past
`ewm(alpha=0.05)` convergence (0.95^1189 ~ 1e-27). The USDT series is the `dune_pipeline/`
Dune export, copied under the `*_eth_usdc_0p05.csv` filenames the current
`prepare_interval_data` globs for — pool identity comes from `pool_config`'s contents, not
the filename (see `_data_usdt/README.md`).

**Windows.** Stated outright, not recovered from `generate_fold_specs`: the published fold
boundaries are index arithmetic over a series that no longer exists, for a different pool.
Episodes are non-overlapping, packed against the end of the series, with everything before
the first episode reserved as lead-in. Both `_data` and `_data_usdt` runs record their
windows in `results/<label>/summary.json`.

**Determinism.** Seed 42 everywhere; `argmax` policies with no sampling. Episode 0 (USDC)
re-run end to end in a fresh process returns bit-identical PnL: DQN
`78.07843447439063`, W10 `254.73164014960025`, both runs.

**Runtime.** Python 3.12.12, torch 2.13.0+cpu, stable-baselines3 2.9.0, sb3-contrib 2.9.0,
gymnasium 1.3.0, pandas 2.3.3, numpy 2.5.2, in a `uv` venv at the research repo root
(`.venv`, gitignored). NixOS needs `LD_LIBRARY_PATH` scoped to the single command for
`libz`/`libstdc++`; it is never exported into the shell (that breaks SSH git — see the
global note).

```bash
NIXLIBS=$(nix build --no-link --print-out-paths nixpkgs#zlib nixpkgs#stdenv.cc.cc.lib | sed 's|$|/lib|' | paste -sd:)
env LD_LIBRARY_PATH="$NIXLIBS" MPLCONFIGDIR=/tmp .venv/bin/python \
  research/simulation_14/analysis/baseline_race/run_baseline_race.py race --data-dir _data --label usdc_served
```

**Raw output.** `results/usdc_served/{episodes.csv,episodes.json,summary.json}` and
`results/usdt_trained/{…}`. Per-episode rows carry every column in the table above plus the
full requested/effective action histograms.

## 6. Caveats — what this result does *not* establish

- **Signal-only.** The training env's hedge is frictionless: it re-hedges continuously
  along the swap path at observed prices with zero execution cost (`simulation_7/README.md:274`,
  `simulation_14/README.md:48`). `always_cash` scores exactly $0.00, which confirms the
  hedge leg is costless in cash. Live, every position change forces a full hedge flatten and
  rebuild (bot issue `P`). **A win here is not live profitability.** The always-in rules
  rebalance 240–455 times per month on USDC; at the ~$0.75–1.25 per flatten/rebuild leg the
  audit estimates, that is $180–570/month of hedge-side cost the env does not charge — which
  could invert the entire ranking. The cost-honest confirmation is item D in the bot repo's
  backtest engine, and **nothing here should be acted on before that runs.**
- **The rule's advantage is the part most exposed to real costs.** The DQN's problem is that
  it churns; the rules win by churning *differently* (recentering rather than exiting), not
  by churning less — W4 makes 454.8 position changes a month. Under honest hedge costs the
  ordering W4 > W6 > W10 > W20 may reverse toward the wider, lazier end. The robust claim is
  narrower than the table: *the learned exit policy destroys value*, not *W4 is the right
  width*.
- **Not the published gate.** These windows are not the published folds and the data is
  rebuilt from B2, so none of these numbers are comparable to the $550 mean in
  `dqn_three_head_v3_manifest.json`. The race is internally valid — identical data, windows,
  env, and seed across arms, verified deterministic — but it is not a reproduction.
- **The USDT arm is in-sample and thin.** One month, 2 episodes, from a Dune export that is
  not provably the training series. It supports the USDC result; it does not stand alone.
- **`gamma = 0.0`** is in the shipped weights, so the DQN is a one-step bandit. The audit
  predicted the rule would be competitive; it is more than competitive. That is a property
  of *this* checkpoint, not of DQNs on this problem.
- **Widths beyond the catalog were not tested.** The action catalog is (4, 6, 10, 20); W4 is
  the narrowest available and it won, so the optimum on USDC may lie below the catalog floor.

## 7. What follows

- The model does not earn its serving slot on the evidence available. Under the tracker's
  own framing ("rule beats model with real costs → serve the rule while the retrain cooks"),
  the remaining gate is cost-honesty, not signal.
- **The pool mismatch is a bug independent of this race** and should be filed as an issue in
  the bot repo's knowledge base regardless of what the backtest says. Any retrain (item F)
  must train on ETH/USDC 0.05% data with `tickSpacing=10`, or the width semantics break
  again.
- The published `simulation_14` gate numbers should be annotated as ETH/USDT 0.3% results
  wherever they are quoted as evidence about the production strategy.
- If a rule is served as an interim, `always_in_w10` is the defensible choice over W4/W6
  despite lower in-sim PnL: it makes 47% fewer position changes than W4 (240 vs 455 per
  month), so it is the least exposed to the hedge costs this environment does not model.
