# E007 — the causal-signal test

> **Experiment:** [`loop/experiments/E007`](../../loop/experiments/E007-causal-signal-test.md).
> **Memo:** [`discovery/memos/M001`](../../discovery/memos/M001-short-horizon-vol-signals.md).
> **Run date:** 2026-09-02. **Cost model:** `gate1-2026-08-29` unmodified.
> **Envelope:** `e003-2026-08-29`. **Data:** E003's committed parquets +
> funding CSV, 2026-05-01 → 2026-08-28 (119.00 days), plus Binance ETHUSDT 1m
> klines ([`data/binance_ethusdt_1m.csv.gz`](data/binance_ethusdt_1m.csv.gz),
> recipe [`fetch_binance.py`](fetch_binance.py)). `gate1/engine/`, `e003/`,
> `e005/`, `e006/` untouched.

**Verdict: REFUTED.** The pre-registered clause fired: *"no pre-named
candidate's full-window central net exceeds $0/day"*. All six M001 candidates,
tuned on 2026-05→07 exactly as registered, lose money over the full window at
both arms — best is C6 at ±0.5% at **−$0.074/day** central — and every one of
the twelve candidate×arm cells is negative on held-out August and at all three
envelope points. Of the **540 tuning configurations** evaluated across the
pre-registered grids, **zero** were positive even on the tune window the
parameters were chosen on. The +$6.06/day ceiling stands (the oracle's mask
re-evaluated through this experiment's own evaluator returns +$6.058/day
float-consistent); no pre-named causal threshold rule captures any of it.

## 1 — Per-candidate results (frozen params, full window)

Stage-2 exact through E003's `run_arm`, $/day over 119.00 days, central
envelope (opt/pess in the JSONs). Tuned on May–Jul only; August untouched
until every parameter was frozen. AUC is oriented (>0.5 = points toward
oracle-held per the rule's own direction), descriptive only.

**±0.2% (w4):**

| Cand | tuned params | held % | streaks (med h) | full $/day | Aug $/day | months + | AUC |
|---|---|---:|---:|---:|---:|---:|---:|
| C1 payoff-EWMA | λ=24h, θ=P90 | 11.3% | 28 (4h) | −1.192 | −0.806 | 0/4 | 0.544 |
| C2 log-RV-EWMA | λ=4h, θ=P10 | 16.6% | 36 (5h) | −1.093 | −2.953 | 0/4 | 0.544 |
| C3 seasonal dow×hod | κ=0, θ=P90 | 10.1% | 272 (1h) | −0.792 | −2.369 | 2/4 | **0.616** |
| C4 Binance 60m RV | N=60, θ=P10 | 13.8% | 146 (1h) | −1.359 | −2.499 | 0/4 | 0.558 |
| C5 bipower-EWMA | λ=4h, θ=P10 | 16.3% | 36 (4h) | −1.000 | −2.716 | 0/4 | 0.549 |
| C6 C1∧C3 | θ₁,θ₂=P90,P90 | 1.1% | 31 (1h) | −0.140 | −0.196 | 0/4 | 0.588 |

**±0.5% (w10):**

| Cand | tuned params | held % | streaks (med h) | full $/day | Aug $/day | months + | AUC |
|---|---|---:|---:|---:|---:|---:|---:|
| C1 | λ=24h, θ=P90 | 9.9% | 32 (2h) | −0.858 | −0.967 | 0/4 | 0.564 |
| C2 | λ=4h, θ=P10 | 16.6% | 36 (5h) | −0.600 | −1.647 | 0/4 | 0.568 |
| C3 | κ=0, θ=P90 | 10.1% | 273 (1h) | −1.010 | −2.112 | 0/4 | 0.594 |
| C4 | N=60, θ=P10 | 13.8% | 146 (1h) | −1.178 | −1.777 | 0/4 | 0.601 |
| C5 | λ=4h, θ=P10 | 16.3% | 36 (4h) | −0.560 | −1.530 | 0/4 | 0.575 |
| C6 | θ₁,θ₂=P90,P90 | 0.7% | 19 (1h) | **−0.074** | −0.127 | 0/4 | 0.591 |

Every candidate was tested; none is omitted. In tuning, every candidate's
optimum sat at the most conservative decile of its grid — the optimizer was
reaching for `always_cash` and the grid floor (~10% held; C6's intersection
~1%) is the only reason any hours were held at all. Full grids:
`out/tune_<cand>_w<W>.json`.

## 2 — Two failure modes, cleanly separated

The candidates fail in two different ways, and the difference is the real
finding:

**Smooth but wrong (C1, C2, C5).** The EWMAs produce respectable streaks
(median 4–5h — the shape M001 §2 said survives switch costs) but select at
AUC 0.54–0.57: the held sets' hours are barely better than random, and 10–17%
of random hours lose ≈ $1/day at these widths.

**Right but fragmented (C3, C4).** The seasonal calendar is the best causal
selector yet measured on this pool — AUC 0.616, clear of the falsified
0.45–0.53 band, and its held set is genuinely good: mean stage-1 payoff
**+$0.42/hour** (vs +$0.80 for the oracle's held set, −$0.33 all-hours), with
72% of its picks oracle-held (base rate 57.9%). It still loses $0.79/day,
because its picks arrive as **272 streaks of median 1 hour**: ~$0.76 mean
round-trip switch cost against ≈ +$0.42/h of stage-1 edge, and stage 2 then
strips the stage-1 over-credits (free centering, boundary funding) from
single-hour holds — E006 §3 measured that stripping at ~1/3 even for the
oracle's 3.8h-mean streaks; for 1h fragments it is worse.

The oracle's +$6.06/day, in other words, is not just *which* hours — it is
**contiguity**: the DP chooses hours jointly with the switch costs, so its
edge compounds across 3–8h runs. A per-hour threshold rule has no mechanism
to buy contiguity, and the candidates that held their streaks together
(C2/C5 at 4–5h) did so by smoothing away exactly the selectivity that made
C3's hours good.

## 3 — Why this is a clean kill for the family, not a tuning accident

- **Zero of 540 tune-window configs were positive.** Not "the best config
  failed out-of-sample" — the pre-registered grids never produced a single
  in-sample winner to overfit with. The REFUTED clause would have fired on
  the tune window alone.
- **August confirms in the same direction.** All twelve frozen cells are
  negative held-out, most by more than their tune-window loss.
- **The machinery is not the story.** Contracts (§5): `always_in` through
  this evaluator reproduces E003's committed lag1h_rh1h results float-exact
  at both arms and all three envelope points; `always_cash` returns exactly
  $0; and the E006 oracle mask through the same path returns +$6.058/day
  (w4) and +$3.718/day (w10) — the evaluator prints large positive numbers
  the moment a mask deserves them.
- **The envelope does not rescue it.** Even fully optimistic hedge execution
  leaves every cell negative (best: C6 w10 −$0.054/day optimistic).

## 4 — What the AUCs say for any successor

C3's 0.616 beats every falsified E006 signal and confirms M001's estimator
critique (rank/log persistence 0.63 ≫ levels-ACF 0.22; the calendar carries
real information). But the gap to *sufficiency* is measured now: an
AUC-0.62 selector with hour-scale granularity monetizes **less than zero** of
a +$6.06/day ceiling once switch costs and honest streak accounting apply.
Selection quality and contiguity have to arrive together — a signal family
that only ranks hours cannot get there through a threshold, however good the
ranking. The RV-proxy refinements (C2/C5 vs the falsified rolling-std) moved
AUC by +0.02–0.05, not the ~0.25+ a threshold rule would need at this cost
structure.

## 5 — Validation

[`tests/test_e007_contracts.py`](tests/test_e007_contracts.py), blocking,
27 checks, all pass:

- **Reproduction** — `always_in` mask == E003 committed lag1h_rh1h, `==` on
  net at all three envelope points, LP fees, recenter counts, w4 + w10.
- **Zero** — `always_cash` nets exactly $0, zero streaks.
- **Accounting identity** — every simulated streak's ledger gap ≤ 1e-6,
  asserted at simulation time and re-checked over the full cache.
- **Causality** — C1/C2/C4/C5 recomputed from truncated data are exactly
  equal at sampled boundaries; C3's cells are provably invariant to held-out
  August data; hourly RV matches a direct recompute under E006's boundary
  convention.
- **Tuning isolation** — the tuning routine raises on any held-out row;
  the final phase refuses to run until all 12 candidate×arm parameter sets
  are frozen on disk.
- **Determinism** — no RNG; grids and tie-breaks are fixed and ordered;
  results are a pure function of committed inputs.

## 6 — What this does not answer

- **Streak-aware rules.** Hysteresis (enter/exit thresholds), dwell minimums,
  or a DP over a *forecast* payoff series could buy the contiguity that
  threshold rules cannot. That is a different policy family — it was not
  pre-named here and would be a new experiment (E008 candidate), taken only
  if the operator keeps the venue alive.
- **Learned combinations.** Six signals × two params each is not a model
  class; a small learned policy was deliberately out of scope (G2 is blocked
  pending the venue decision anyway).
- **Adverse selection/MEV** — inherited from E003/E006 and moot in this
  direction: it would only make the (already negative) candidate results
  worse and a hypothetical successor's bar higher.
- **Other venues.** Everything here is ETH/USDC 0.05% on Arbitrum. E005's
  watchlist pools have different fee/gamma structure; nothing here transfers
  automatically.

## 7 — Reproducing this

```bash
cd ~/developments/llaminet/research
nix develop .#gate1 -c python backtest_model_server/e007/tests/test_e007_contracts.py
for c in c1 c2 c3 c4 c5 c6; do
  nix develop .#gate1 -c python backtest_model_server/e007/run_candidates.py --phase tune --candidate $c --arm 4
  nix develop .#gate1 -c python backtest_model_server/e007/run_candidates.py --phase tune --candidate $c --arm 10
done
nix develop .#gate1 -c python backtest_model_server/e007/run_candidates.py --phase final --arm 4
nix develop .#gate1 -c python backtest_model_server/e007/run_candidates.py --phase final --arm 10
```

Needs E003's parquets and funding CSV (as E006) and the committed Binance
reduction. Total compute ≈ 15 min cold (the per-streak cache makes the grids
cheap; `out/cache_w*.json` is git-ignored and rederivable).

| Path | Purpose |
|---|---|
| [`causal_signals.py`](causal_signals.py) | The six pre-named signals; grids; causality conventions |
| [`evaluate.py`](evaluate.py) | Mask → streaks → cached exact simulation (E006 stage-2 machinery) |
| [`run_candidates.py`](run_candidates.py) | Tune (May–Jul only) and final (all-frozen-first) phases |
| [`fetch_binance.py`](fetch_binance.py) | C4 input fetch + reduction recipe |
| [`constrained_oracle.py`](constrained_oracle.py) | M001 §2 coarseness table (memo-phase artifact) |
| [`tests/test_e007_contracts.py`](tests/test_e007_contracts.py) | The blocking contracts of §5 |
| `out/tune_*.json`, `out/final_*.json` | Every grid point; every frozen result |

## 8 — What this changes

- **H-timing's realizable arm is refuted as pre-named.** The ceiling is real
  (E006) but the M001 candidate set — the memo-ranked best of the standard
  literature under our constraints — captures none of it through the fixed
  threshold-rule family. The conditional fourth option E006 handed the
  operator ("stay on ETH/USDC 0.05% iff E007 finds a realizable filter")
  **dies as specified**; the venue decision reverts to E005's three-way call.
- **The measured residual** is §2's contiguity gap: the one avenue this run
  identifies but does not test (streak-aware rules on a C3-quality selector).
  It goes to the operator as an option with its cost stated (a new experiment
  family), not as a recommendation.
- **For any successor**: tune and judge on stage-2 exact only (M001 §2);
  expect selection and contiguity to trade off; and the 0.62-AUC calendar is
  the strongest causal selector measured on this pool to date.
