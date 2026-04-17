# Reasons for direct-vs-server drift (potential causes)

Open drift sources identified during the 2026-04-18 action-mismatch
investigation after Bug #1 (hsr off-by-one) was fixed in
`research/backtest_model_server/scripts/03_run_infer_backtest.py`. Post-fix
action match is 40/95 on the Apr 11–14 2026 window; the remaining ~55
mismatches are attributed to the two bugs below.

---

## Bug #2 — OHLCV-source drift

**Status:** open — documented here for a future fix to `visualize_apr11_14.py`.

### Symptom

When the direct DQN run (`visualize_apr11_14.py`) and the server backtest
(`backtest_model_server/scripts/03_run_infer_backtest.py`) are both sitting in
cash at the same hour and the current-hour price matches to < $0.01, they
occasionally disagree on the model's output (direct says `enter_w{n}`, server
says `exit_to_cash`). In the post-b2, post-hsr-fix window Apr 11–14 2026 this
accounts for the last ~2 / 57 residual action mismatches.

### Root cause

Direct and server consume different materializations of the same underlying
on-chain swap data:

- **Direct** (`visualize_apr11_14.py` → `uniswap_v3_ppo_paper.py`): loads the
  concatenated swaps CSV and resamples it to hourly OHLCV inside Python at
  load time.
- **Server** (`backtest_model_server` and `model/app/services/b2_data.py`):
  reads the consolidator's per-day output
  `pipeline/consolidator/daily/ohlcv/{date}.parquet` (built by
  `BuildOHLCVFromSwaps` in `pipeline/consolidator/ohlcv.go`).

These two paths agree on the *current-hour* close to ≈ $0.00 for 92/95 hours
but diverge at **hour 23 of each day** (see `step0_baseline.md` §2.3 — max
diff $3.18 there) because the consolidator emits per-day files with
inclusive/exclusive second handling at midnight UTC that doesn't match the
in-memory resampler.

The current-hour diff is bounded and small. The real problem is that the
model's 31-dim observation includes TA features that **accumulate over
history**:

- `bb_width` expanding median (all prior closes)
- `natr_14` (14-bar ATR)
- `realized_vol_6h` (std of last 6 returns)

Even a $2–3 one-hour close drift at a day boundary shifts these aggregate
features enough to flip the policy's output at *later* hours — including
hours where both sides have matched prices and no position.

### Evidence

From the post-b2 + post-hsr-fix diff on the Apr 11–14 2026 window:

| timestamp | both cash? | current-price diff | direct action | server action |
|---|---|---|---|---|
| 2026-04-11 22:00 | yes | ≈ $0.00 | `enter_w10` | `exit_to_cash` |
| 2026-04-12 21:00 | yes | ≈ $0.00 | `enter_w4` | `exit_to_cash` |

Both of these hours have at least one day-boundary outlier inside their
preceding 6h / 14-bar / expanding-median windows, so the TA features differ
even though the current-hour close matches.

### Fix

Point the direct run at the consolidator's OHLCV instead of resampling the
raw swap CSV:

1. In `visualize_apr11_14.py`'s data-loader, replace the swap-CSV → resample
   path with a concatenation of
   `pipeline/consolidator/daily/ohlcv/{date}.parquet` for the window under
   test (materialized to e.g.
   `research/backtest_model_server/results/ohlcv_hourly_detail.csv` already).
2. Keep the swap CSV only for per-swap needs (in-range tick distribution,
   `compute_time_in_range_for_hour`). TA features must be computed off the
   consolidator OHLCV to match the server.

After this change §2.3 (`max |price diff| < $0.50`, `mean < $0.10`) becomes
achievable by construction, and the two remaining cash-both action mismatches
in the Apr 11–14 2026 window should resolve.

### Why defer

- Net PV impact is tiny (the two flipped decisions are both in cash at the
  time, no capital at risk).
- The fix touches the visualization/direct-run pipeline only; server/backtest
  are already correct.
- Can be bundled with the next `visualize_apr11_14.py` refactor rather than a
  one-shot surgical edit.

### References

- `step0_baseline.md` §2.3 — documents the raw max/mean/median diff
  between direct-resampled and consolidator OHLCV for this window.
- `pipeline/consolidator/ohlcv.go` — `BuildOHLCVFromSwaps` (source of the
  day-boundary handling).
- `model/app/nn/features_v2.py` — `build_dqn_observation` and `FEATURE_COLS`
  (TA features whose cumulative windows are sensitive to this drift).

---

## Bug #3 — history-window mismatch

**Status:** open — likely the dominant remaining driver of action mismatch
after Bug #1 was fixed.

### Symptom

After the Bug #1 hsr fix, action match on the Apr 11–14 2026 window is only
40/95. 55/95 rows still differ between direct and server despite identical
`has_position`, identical (fixed) `hours_since_rebalance`, and current-hour
prices agreeing to < $0.01 at the vast majority of hours. The server's
policy is receiving a materially different observation vector from what the
direct run's training env builds.

### Root cause

The direct run and the model server build their technical-analysis features
from **different windows of history**:

- **Direct** (`visualize_apr11_14.py` → `prepare_hourly_data` → swaps CSV):
  loads `research/research/poc/training_data/swaps_20260407_to_20260414_eth_usdc_0p05.csv`,
  which covers **Apr 7 – Apr 14 2026 (~8 days / ~192 hours)**. All TA
  features — including the expanding-median windows — are computed off this
  short tail.
- **Server** (`model/app/services/b2_data.py` → B2 rolling parquet /
  consolidator OHLCV): as of this run the server had OHLCV from
  **2026-01-01 onwards (~100 days / ~2400 hours)**. Every `/infer` call
  computes TA features off this long tail.

At backtest hour 0 (2026-04-11 00:00) the two sides differ by **~25×** in
the amount of prior history consumed by the feature builder. The features
most sensitive to this:

- `bb_values` **expanding median** inside
  `model/app/nn/features_v2.py:build_dqn_observation`
  (`np.median(bb_values[:current_idx+1])`) — never rolled off, so the
  median is dominated by whatever regime dominates the history tail.
  Direct's median reflects only April 2026 market conditions; server's
  median is weighted by Jan–Feb 2026 as well. The `bb_ratio` and
  `bb_signal` paper-features derived from this median are therefore
  systematically different at *every hour* of the backtest.
- `natr_14`, `volume_sma_ratio`: rolling fixed-length windows — stable
  once ≥ 14–20 bars are warm, so the direct side is fine here as long as
  the 4-day prelude of swap data is loaded.
- `realized_vol_6h`: 6-bar rolling window — unaffected once 6 bars exist.

The expanding-median issue makes this bug pervasive: it flips the policy
across many hours, and because the server's action drift cascades (each
unmatched action changes future state, which changes the next obs), the
effect stacks on top of whatever residual Bug #2 drift exists.

### Evidence

- Direct trace covers only 2026-04-11 → 2026-04-14 (95 rows). The
  underlying swap CSV is `swaps_20260407_to_20260414_eth_usdc_0p05.csv`
  (8-day window).
- Server-side `research/backtest_model_server/results/ohlcv_hourly_detail.csv`
  contains 2568 hourly rows spanning 2026-01-01 → 2026-04-20 (verified
  2026-04-18).
- Post-Bug-#1 run: 55/95 action mismatches, including 37 both-in-position
  rows where `hsr`, `has_position`, and price all agree — the residual
  obs delta is carried by TA features (expanding median being the most
  susceptible).

### Fix options

**Option A — extend direct's swap coverage.**
Download/concatenate additional swap CSVs into
`research/research/poc/training_data/` so `prepare_hourly_data` reads a
history depth comparable to the server's (e.g., 2026-01-01 onwards).
Cheapest, no code changes to the loader.

**Option B — have direct consume the consolidator OHLCV directly.**
Replace the swap-CSV → resample path in `visualize_apr11_14.py` with
`daily/ohlcv/{date}.parquet` concatenation over the full server-visible
range, keeping the swap CSV only for per-swap needs (in-range tick
distribution, fee math). This collapses Bug #2 and Bug #3 into a single
fix and guarantees identical feature inputs on both sides.

Option B is the durable choice; Option A is a quick shim if you just need
the Apr 11–14 audit to converge.

### Why defer

- Impact is observability-only: the deployed model on the server is already
  using the correct (long-history) feature path — it's the *direct trace*
  that is the odd one out.
- Net PV delta on Apr 11–14 is small (< $3), so trading decisions in
  production are not affected; only the apples-to-apples action-match
  metric in §2.6 is.
- Option B rides on the same `visualize_apr11_14.py` refactor that closes
  Bug #2, so they should be scheduled together.

### References

- `research/research/simulation_14/visualize_apr11_14.py` — `DATA_DIR`,
  `prepare_hourly_data` call.
- `research/research/poc/training_data/swaps_20260407_to_20260414_eth_usdc_0p05.csv`
  — current (short) swap data slice.
- `model/app/services/b2_data.py` — server-side long-history OHLCV loader.
- `model/app/nn/features_v2.py:build_dqn_observation` — `expanding_median`
  call on `bb_values`, which is where the history tail asymmetry hits the
  obs vector.
