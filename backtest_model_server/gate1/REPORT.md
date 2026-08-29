# Gate 1 — reproducing T4 and T5 per cost line

> **Experiment:** [`loop/experiments/E002`](../../loop/experiments/E002-gate1-trial-reproduction.md), phases 1–2 of the build plan in bot [`analysis/strategy-review/04-backtest-design.md`](../../../bot/analysis/strategy-review/04-backtest-design.md) §8.
> **Run date:** 2026-08-29. **Cost model version:** `gate1-2026-08-29` (frozen).
> **Calibration source:** bot [`analysis/strategy-review/01-loss-attribution.md`](../../../bot/analysis/strategy-review/01-loss-attribution.md) §2/§5 and the regenerated `bot/analysis/trials/{4,5}/output/data/summary.json`.

**Verdict: SUPPORTED.** All four pre-registered cost lines reproduce within tolerance on both trials. The engine also found five defects — one of which, a missing Uniswap V3 protocol fee, means the harness *and the training environment it inherits from* have been overstating LP fee income by 33.3%.

---

## 1 — The per-cost-line tables

E002 pre-registered four lines and their tolerances. Those four are marked **[R]** (rule). The other rows come from `04-backtest-design.md` §6.1 and are reported for completeness; they are not part of the decision rule.

### T5 — 2026-05-14 05:00 → 2026-05-15 05:00 UTC, 8 cycles

| Line | Target | Reproduced | Delta | Tolerance | Verdict |
|---|---:|---:|---:|:--|:--|
| **LP fees** **[R]** | +$7.8210 | +$7.8091 | −$0.0119 (−0.2%) | ±15% | **PASS** |
| **Crystallized IL** **[R]** | −$10.90 | −$11.7245 | −$0.8245 (−7.6%) | ±10% | **PASS** |
| **HPL trading fees** **[R]** | −$3.3577 | −$3.3579 | −$0.0002 (−0.006%) | ±5% | **PASS** |
| **Funding** **[R]** | +$0.0702 | +$0.0569 | −$0.0133 | ±$0.05 | **PASS** |
| On-chain cost | −$5.1049 | −$4.6251 | +$0.4798 (+9.4%) | ±10% | PASS |
| On-chain swap volume | $9,062.15 | $8,158.50 | −$903.65 (−10.0%) | ±10% | PASS (at the edge) |
| Flat-gap residual | ≈ −$2.40 | −$3.0507 | −$0.6507 (−27.1%) | ±50% | PASS |
| LP basket delta | +$8.52 | +$9.4988 | +$0.9788 (+11.5%) | ±10% | **FAIL** |

Per-cycle LP fee error runs **−0.5% to +1.3%**, against a §6.1 per-cycle bar of ±25% and the design doc's own expectation of ±3–5%.

### T4 — 2026-05-12 16:00 → 2026-05-13 16:00 UTC, 9 cycles

| Line | Target | Reproduced | Delta | Tolerance | Verdict |
|---|---:|---:|---:|:--|:--|
| **LP fees** **[R]** | +$5.5623 | +$4.7397 | −$0.8226 (−14.8%) | ±15% | **PASS** (see §3.2 — the target is wrong) |
| **Crystallized IL** **[R]** | −$4.51 | −$4.2701 | +$0.2399 (+5.3%) | ±10% | **PASS** |
| **HPL trading fees** **[R]** | −$4.4021 | −$4.4025 | −$0.0004 (−0.009%) | ±5% | **PASS** |
| **Funding** **[R]** | +$0.0947 | +$0.0791 | −$0.0156 | ±$0.05 | **PASS** |
| On-chain cost | ≈ −$6.40 (scaled est., ±40%) | −$5.9306 | +$0.4694 (+7.3%) | ±10% | PASS |
| LP basket delta | +$1.20 | −$4.2720 | −$5.4720 | ±10% | **FAIL** |

Per-cycle LP fee error runs **−0.3% to +0.1%**. Against the fee total the engine's own cycle boundaries imply ($4.7409), the aggregate error is **−0.03%**.

### The like-for-like fee test

The headline LP-fee comparison mixes two questions: is the engine right, and is the published target right. Separating them:

| | Engine | Recorder, over the same replayed cycles | Error |
|---|---:|---:|---:|
| T5 | $7.8091 | $7.8210 | **−0.15%** |
| T4 | $4.7397 | $4.7409 | **−0.03%** |

### Intra-cycle accrual shape (§6.2 instrument 2)

Non-exit `rebalance-history` rows carry a live reading of unclaimed fees, so each is an extra observation. Reproducing a cycle total while getting the path wrong is a detectable failure, and it is the failure mode a time-in-range model exhibits.

| | Extra observations | Worst \|err\| | Mean \|err\| |
|---|---:|---:|---:|
| T5 | 8 | 0.4% | 0.2% |
| T4 | 2 | 0.2% | 0.1% |

### Exact on-chain fee cross-check (§6.2 instrument 3)

The design doc asks for a `feeGrowthInside` comparison. The burn transactions give something equivalent and more direct: `Collect − Burn` is exactly the fee the pool paid out. For every cycle that burned, it reproduces the recorder's `accumulated_fees_usd` **to the cent** — 7 of 8 cycles in T5, 9 of 9 in T4. The calibration target itself is therefore confirmed against chain data, not merely re-read from a CSV.

---

## 2 — Phase 1: what the audit found

### F1 — The pool takes a 25% protocol fee, and nothing in the stack models it (HIGH, fixed)

`slot0().feeProtocol` on `0xC6962004f452bE9203591991D15f6b388e09E8D0` is **`0x44`** — a denominator of 4 on both tokens — so the Uniswap treasury skims one quarter of every swap fee and LPs receive **75% of the 5 bps, i.e. 3.75 bps**. No `SetFeeProtocol` event fires in blocks 460,000,000–465,000,000, which brackets both trial windows, so the value held throughout.

The harness credits LPs the full 5 bps. Before this fix the replay overstated every cycle's fee by a near-constant factor: T5's eight cycles came in between **+32.7% and +35.1%** — i.e. **1/0.75 = 1.333**, on the nose. Adding the term moved the T5 aggregate from +33.1% to −0.2%.

This is not a harness-local bug. `04-backtest-design.md` §2.2 records that the harness inherits its fee and hedge assumptions from the **training environment**, and the fee formula is the inherited part. So `simulation_14` — the shipped lineage — was trained against LP fee income inflated by a third. Whether that changed the learned policy is a question for `model-audit`; this report only establishes the magnitude.

Reproduce: `diagnostics/protocol_fee_check.py`.

### F2 — H1 confirmed: fee and hedge P&L are attributed to the wrong hour (HIGH, avoided)

§10 of the design doc lists "Is H1 real?" as Phase 1's first task and specifies the test. `tests/test_h1_alignment.py` runs it. A step stamped 11:00 prices the interval [10:00, 11:00) and:

- swaps placed in the 10:00 bucket (inside the priced interval) earn it **$0.000000**
- swaps placed in the 11:00 bucket (the hour *after*) earn it **$0.065441**

`hour_ts = pd.Timestamp(timestamp).floor("h")` reads bucket `t` while the interval `[t−1, t)` lives in bucket `t−1`. The same index drives `compute_active_hedge_hour`. The control the design doc names holds: the same file computes `time_in_range` from `timestamps[step_idx - 1]`, so the two conventions genuinely disagree inside one module.

gate1 does not patch the index. It slices swaps by real cycle boundaries — mint block to burn block — so hour bucketing never enters the replay. `03_run_infer_backtest.py` is **left unmodified**; anyone running the harness in mode B still has this bug, and fixing it there is a separate change that should carry its own test.

### F3 — The B2 daily archive is incomplete over both trial windows (HIGH, worked around)

The abort criterion was whether trial-window pool data exists. It does, but **not in B2**:

| Window | Hours present in B2 | Hours present via RPC |
|---|---:|---:|
| T5 (05-14 05:00 → 05-15 05:00) | **11 / 24** | **24 / 24** |
| T4 (05-12 16:00 → 05-13 16:00) | **11 / 24** | **24 / 24** |

Worse, B2 is incomplete *within* the hours it does cover — for hours present in both sources, RPC carries 1.04× to 4.38× as many swaps:

```
2026-05-14 13:00   B2 1712   RPC 1781   ratio 1.04
2026-05-14 16:00   B2  908   RPC 2078   ratio 2.29
2026-05-15 01:00   B2  312   RPC 1251   ratio 4.01
2026-05-15 05:00   B2  315   RPC 1381   ratio 4.38
```

Replaying against B2 would have silently under-counted fees by roughly half, which is exactly the failure `04-backtest-design.md` §9 names ("refuse to replay a window with gaps rather than silently under-counting"). Every number in this report is sourced from `eth_getLogs` against `https://arb1.arbitrum.io/rpc`, which serves full archive depth at 50k-block ranges. Measured pool volume for 2026-05-14 is **$59.75M**, against ~$67M implied by DefiLlama's `apyBase` (22.10%) × TVL ($55.5M) for that day — the right order, and low if anything, which is the safe direction for a fee model.

The configured Alchemy endpoint in `model/.env` returned HTTP 429 throughout this session and could not be used.

Reproduce: `diagnostics/b2_vs_rpc_coverage.py`, `probe_b2.py`.

### F4 — Three `executed_exit` rows record transactions that reverted (HIGH, data-integrity)

The bot logs `executed_exit` with a `remove_tx_hashes` value without checking the transaction receipt. Three such rows across the two trials have `status = 0x0`:

| Trial | Row | Tx | Consequence |
|---|---|---|---|
| T4 | 2026-05-13 05:02:06 | `0x4c731432aaf1…` | position stayed open; really burned at 06:02 |
| T4 | 2026-05-13 10:02:05 | `0x88dd8ddfc607…` | position stayed open; really burned at 11:02 |
| T5 | 2026-05-15 04:02:04 | `0xb23a2565e6bc…` | **position never closed inside the window** |

Independently corroborated by the AUM path: T4's `position_usd` holds ~$1,020 straight through 05:00–06:00 and only drops to zero at 06:03.

Two consequences for the calibration targets, both in §3.

Reproduce: `diagnostics/inspect_action_txs.py`.

### F5 — Maker share is quoted by fill count; the fee line needs it by notional (MEDIUM, fixed)

`04-backtest-design.md` §4.4 lists "maker share, steady state 88%" without a weighting. The two weightings differ sharply, because the taker fills are the large ones:

| | by fill count | by notional |
|---|---:|---:|
| T5 | 86.06% | **64.63%** |
| T4 | 89.19% | **63.45%** |

Applying the count-weighted share to total notional gives T5 **$2.5147** against a recorded $3.3577 — a **25% understatement** of the second-largest hedge cost line. `cost_model.hpl_fees_from_shares` takes notionals, and its docstring says why.

### Lower-severity findings

- **M3 (tick round-trip) is real but costs nothing.** `compute_fee` derives LP bounds via `price_to_tick(tick_to_price(t))`. Measured over eight hour buckets the round trip is exact: **+0.0000%**. gate1 uses the recorded on-chain ticks anyway, since mode A has them.
- **`simulate_step` rejects timezone-aware timestamps.** `pd.Timestamp(timestamp, tz="UTC")` raises on a tz-aware input, so the function only works with naive datetimes that happen to be UTC. Latent, not currently triggered.
- **`volume_usd = |amount1|` is the output leg on ETH→USDC swaps.** V3 charges the fee on the input, so this is low by exactly the fee rate — 5 bps of 5 bps, or 2.5e-7 of notional. Recorded, not fixed.
- **`funding_rate_annual: 0.048` is a constant and is `abs()`-ed** (H3), so funding can only ever be a cost. Every measured window received funding. gate1 replays the recorded hourly series instead; the harness constant is untouched.
- **The hedge leg is unmodelled** (H2) — `compute_active_hedge_hour` rehedges continuously at zero cost. Out of scope for Gate 1, which replays recorded fills; it is Phase 4's job.

---

## 3 — Corrections the reproduction forces on the calibration source

Both follow from F4. `01-loss-attribution.md` is the single calibration source, and these are proposed amendments to it, not disagreements with the engine.

### 3.1 T5's LP fees were not all collected

`lp_fees_collected_usd = $7.8210` is the sum of `accumulated_fees_usd` over `executed_exit` rows. The final exit reverted, so **$1.5764 of that was accrued but never collected** — the position minted at 02:02 was still open at window end. `Collect − Burn` over the seven cycles that did burn totals **$6.2446**, and $6.2446 + $1.5764 = $7.8210 exactly.

The engine reproduces $7.8091 of *fees earned*, which is the right quantity for a simulator and the right comparison against $7.8210. But "collected" overstates the realised cash by $1.58, and any statement about T5's LP-side cash should use $6.24.

### 3.2 T4's LP-fee figure double-counts $0.82

`01-loss-attribution.md` §2 gives T4 LP fees as **+$5.56**, summing all eleven `executed_exit` rows. Two of those rows are the reverted exits. `accumulated_fees_usd` is a running total on the live position that only resets at a real burn, so the readings at 05:02 ($0.4320) and 10:02 ($0.3894) are intermediate samples of totals that continued to $0.6789 and $0.7190.

The correct figure is the fee at the moment each position was actually burned: **$4.7409**. It is confirmed independently — `Collect − Burn` over the nine real cycles gives $4.7409 to the cent.

So T4's LP fee line should read **+$4.74/day, not +$5.56**. This lowers T4's LP-side income by 15% and makes T4 and T5 further apart than the ledger currently shows.

### 3.3 Basket delta does not reconcile — the one line I could not close

This is the honest gap. Under every combination of cycle boundaries and price source, the engine's basket delta sits outside ±10% of report 01:

| Variant | T5 | T4 |
|---|---:|---:|
| report 01 | +$8.52 | +$1.20 |
| engine, pool price at burn block | +$9.50 (+11.5%) | −$4.27 |
| engine, Binance 1m | +$9.78 (+14.7%) | −$2.31 |
| engine, exact from Mint/Burn amounts | +$10.10 | −$4.27 |
| engine, report-01 cycle pairing + pool price | — | +$0.80 (−33%) |
| engine, report-01 cycle pairing + Binance | — | +$1.55 (+29%) |

Best hypothesis: **the difference is `amount0` at mint.** Basket delta is `a0_mint × (P_exit − P_entry)`, and the whole T5 gap sits in the breakout cycle (14:02→16:02). The Mint event says the position was opened with **0.250925 ETH**; report 01's +$9.96 for that segment implies about 0.2316 ETH, 8% less. Report 01 inverted liquidity from a five-minute AUM snapshot; the engine reads the deposited amount off the Mint event. The engine's input is strictly better sourced, but I have not reconciled the two derivations line by line, and T4's basket delta is additionally dominated by the F4 boundary correction, so I am not asserting a replacement value.

Basket delta is not one of E002's four pre-registered lines. It matters anyway, because it is the "delta luck" that §3.2 of the design doc says must be stripped before projecting — so **the +$3.98 T5 / +$4.64 T4 delta-luck figures should be treated as unconfirmed until this is closed.**

### 3.4 A note on two choices I made after seeing results

Disclosed because they affect the verdict:

1. **IL is graded on the pool price at the burn block, not Binance 1m.** Under Binance, T4's IL is −$5.6696 (−25.7%, FAIL); under the pool price it is −$4.2701 (+5.3%, PASS). The justification is independent of that outcome: a V3 position's composition is set by the pool's own price, and the **zero-model figure taken straight from the Mint/Burn token deltas is −$4.2696**, agreeing with the pool-price closed form to **$0.0005 across all nine cycles** while the Binance convention is $1.40 away. All three variants are printed by the replay and stored in `out/T<n>/result.json` so the choice is auditable. T5 is insensitive to it (−$11.72 vs −$11.70).

2. **Cycle boundaries come from on-chain Burn events, not from `executed_exit` rows.** This is a factual correction (F4) rather than a tuning choice, but it does change T4's IL, so `replay_mode_a.py --assume-all-exits-burned` reproduces report 01's pairing on demand. Under it, T4's IL is **−$4.6231 against a −$4.51 target, −2.5%** — which is what confirms the diagnosis: the engine reproduces report 01's number under report 01's assumption, and produces a different number under boundaries verified against chain data.

---

## 4 — What is still unexplained

Reported rather than absorbed, per §6.4 and decision `0005`.

**T5.** Modelled and replayed lines account for −$9.55 of the recorded −$12.60 AUM change. The −$3.05 gap is the flat-gap / out-of-position residual, against report 01's independent ≈−$2.4 estimate (within the ±50% band). T5 held no LP position 38% of the time, and this line is drift on the parked token mix — open question 3 in the design doc, and nothing in the queue addresses it.

**T4.** The same arithmetic gives −$12.23 explained against a recorded −$8.76, a residual of **+$2.90** — the opposite sign to T5. Some of that is the basket-delta gap (§3.3) feeding straight through. T4's on-chain line is also a ±40% scaled estimate rather than an audit, because `onchain_audit.json` exists only for T5.

**Funding is passing a weak test.** The ±$0.05 band is comparable to the line itself (≈$0.06–0.09/day), and the reconstruction is sensitive to which AUM snapshot is taken at each hour top — exits fire at :02, so "nearest after" catches a just-flattened perp and biases low. Using the nearest snapshot in either direction moves T4 from +$0.0569 to +$0.0791. The line passes, but it is not strongly constrained, and this is consistent with report 01's conclusion that funding is small positive income rather than a real cost lever.

**On-chain swap volume is at the tolerance edge.** The engine identifies 22 of the 23 audited pool swaps by the Swap event's counterparty topics, for $8,158 against the audit's $9,062 (−10.0%). The policy-implied prediction — what a counterfactual would actually use — is $7,775 (−14.2%), so **the swapped-notional term is the weakest part of the on-chain model**, exactly as §3.5 predicted ("dominated by getting swapped notional right").

---

## 5 — Reproducing this

Everything runs from the research repo root. No writes outside it.

```bash
# 0. Environment. `nix develop` (the default shell) lacks pyarrow and requests;
#    the gate1 shell was added to flake.nix for this work.
cd ~/developments/llaminet/research

# 1. Optional: what is in the B2 archive, and what is missing.
nix develop .#gate1 -c python backtest_model_server/gate1/probe_b2.py
nix develop .#gate1 -c python backtest_model_server/gate1/fetch_trial_data.py

# 2. The data the replay actually uses: complete windows from Arbitrum RPC,
#    plus decoded Mint/Burn/Collect for every recorded action tx.
#    ~470 RPC calls and ~4 min per trial; --reuse-edges skips the hour-boundary
#    binary search on a re-run.
nix develop .#gate1 -c python backtest_model_server/gate1/fetch_rpc_window.py --trial 5
nix develop .#gate1 -c python backtest_model_server/gate1/fetch_rpc_window.py --trial 4

# 3. Tests.
nix develop .#gate1 -c python backtest_model_server/gate1/tests/test_h1_alignment.py
nix develop .#gate1 -c python backtest_model_server/gate1/tests/test_fee_equivalence.py
nix develop .#gate1 -c python backtest_model_server/gate1/tests/test_cost_model_fixture.py

# 4. The reproduction.
nix develop .#gate1 -c python backtest_model_server/gate1/replay_mode_a.py --trial 5
nix develop .#gate1 -c python backtest_model_server/gate1/replay_mode_a.py --trial 4
nix develop .#gate1 -c python backtest_model_server/gate1/replay_mode_a.py --trial 4 \
    --assume-all-exits-burned      # report 01's cycle pairing, for §3.4

# 5. Diagnostics behind the findings.
nix develop .#gate1 -c python backtest_model_server/gate1/diagnostics/protocol_fee_check.py
nix develop .#gate1 -c python backtest_model_server/gate1/diagnostics/inspect_action_txs.py
nix develop .#gate1 -c python backtest_model_server/gate1/diagnostics/b2_vs_rpc_coverage.py
```

**Determinism.** No random number generator is used anywhere; there is no seed. The replay is a pure function of the cached data under `gate1/data/`, which is committed, so step 4 reproduces byte-identical results without network access. Steps 1–2 need network and re-fetch the same immutable chain data.

**Credentials.** B2 keys and `ARBITRUM_RPC_URL` are read from `/home/poon/developments/llaminet/model/.env`, read-only. The RPC work defaults to the public `arb1.arbitrum.io/rpc` and needs no key.

### Layout

| Path | Purpose |
|---|---|
| `engine/harness.py` | Bridge to the harness's verified V3 math. Loads `scripts/03_run_infer_backtest.py` by path and re-exports the closed forms. |
| `engine/fee_engine.py` | Per-swap fee accrual over an arbitrary slice. The harness's formula plus the protocol-fee term. |
| `engine/il_ledger.py` | Crystallized IL and basket delta per cycle, reported separately and never netted. |
| `engine/cost_model.py` | Self-contained cost model, stdlib only. The file §2.3 asks to be copied into `bot/analysis/`. |
| `engine/trials.py` | Recorded-trial loaders. Owns the UTC+7 correction and the reverted-exit handling. |
| `engine/rpc.py`, `engine/b2.py` | Data access. |
| `engine/swaps.py` | B2 parquet loader, used by the equivalence test. |
| `replay_mode_a.py` | The mode-A driver. |
| `out/T{4,5}/` | `result.json`, `cycles.csv`, `checkpoints.json`, `funding_detail.json`. |
| `data/rpc/T{4,5}/` | `swaps.parquet`, `actions.json`, `meta.json` — the committed inputs. |

The directory is `engine/`, not `lib/`, because the repo's `.gitignore` carries a Python-packaging `lib/` rule that silently excludes any directory of that name.

---

## 6 — What this unlocks, and what it does not

Per E002's decision rule, all four pre-registered lines pass on both trials, so **Gate 1 passes and the engine is trusted for counterfactuals** on the lines it reproduced. Concretely, the LP-fee engine reproduces per-cycle fees to about 1%, the IL ledger to 5–8%, and the HPL fee model to better than 0.01%. E003 (cost-honest width race) is unblocked.

Three limits should travel with any counterfactual quoted from this engine:

- **Basket delta is unreconciled** (§3.3), so delta-luck-stripped nets are not yet trustworthy.
- **The hedge leg is still unmodelled.** Mode A replays recorded fills; it does not predict them. Nothing here licenses a claim about maker share, queue position or chase cost under a changed policy — that is Phase 4, and §4.5's envelope discipline still applies.
- **Swapped notional is the weak term** in the on-chain line (−14.2% predicted vs audited), and it is precisely the term that issues `8` and `9` move. Tighten it before pricing those.

Two items for whoever owns the bot repo, which this session could not write to:

1. Copy `engine/cost_model.py` to `bot/analysis/cost_model.py`; `tests/test_cost_model_fixture.py` already checks both copies agree and currently reports the copy as absent.
2. The recorder should check receipt status before logging `executed_exit` (F4). Three of nineteen exits across two trials were recorded as successful when they reverted, which corrupted a published cost line (§3.2).

And one for `model-audit`: F1 means the training environment credited LP fee income 33% too high. That changes the reward the shipped model was optimised against.
