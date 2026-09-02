# E008 — the streak-aware-rules test

> **Experiment:** [`loop/experiments/E008`](../../loop/experiments/E008-streak-aware-rules.md).
> **Memo:** [`discovery/memos/M002`](../../discovery/memos/M002-buying-contiguity-with-streak-rules.md).
> **Run date:** 2026-09-03. **Cost model:** `gate1-2026-08-29` unmodified.
> **Envelope:** `e003-2026-08-29`. **Data:** E003's committed parquets +
> funding CSV, 2026-05-01 → 2026-08-28 (119.00 days). No new fetches (the
> M002 set needs no Binance data). `gate1/`, `e003/`, `e005/`, `e006/`,
> `e007/` untouched; machinery reused **by import** (e007's
> `causal_signals`/`evaluate`, e006's `oracle.dp_select`/`exact`).

**Verdict: REFUTED.** The pre-registered clause fired: *"no pre-named
candidate exceeds $0/day central full-window"*. All six M002 candidates,
tuned on 2026-05→07 exactly as registered, lose money over the full window
at both arms — best is S5 (DP over the shrunk calendar) at ±0.5% at
**−$0.025/day** central (−$0.007 optimistic) — and every one of the twelve
candidate×arm cells is negative on held-out August and at all three envelope
points. Of the **404 tuning configurations**, **3** were positive on the
tune window (the program's first, after E007's 0/540) — all three are S5
holding 0.6–3.0% of hours in *median-1-hour* streaks, and all three fail
August (−$0.46 to −$0.63/day). With E007 this closes H-timing on ETH/USDC
0.05%: per-hour thresholds cannot buy contiguity, and when streak-aware
rules do buy it, it is not worth buying. **Per the operator pre-commitment
(2026-09-03, bot ADR 0009), the venue moves to the wstETH/WETH 0.01%
funding-carry path (card B2); no further experiments on this pool.**

## 1 — Per-candidate results (frozen params, full window)

Stage-2 exact through E003's `run_arm`, $/day over 119.00 days, central
envelope (opt/pess in the JSONs). Tuned on May–Jul only; August untouched
until every parameter was frozen. AUC is oriented vs E006's oracle-held
hours, descriptive only.

**±0.2% (w4):**

| Cand | tuned cfg | held % | streaks (med h) | tune $/d | full $/d | Aug $/d | months + | AUC |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| S1 calendar hysteresis | κ=0, hi=P90, lo=P50 | 16.1% | 256 (1h) | −0.553 | −1.036 | −2.682 | 0/4 | 0.616 |
| S2 blend hysteresis | q_hi=0.9, q_lo=0.5 | 1.7% | 29 (1h) | −0.163 | −0.181 | −0.240 | 0/4 | 0.589 |
| S3 minimum dwell | θ=P90, D=2 | 18.4% | 239 (2h) | −1.836 | −2.208 | −3.474 | 0/4 | 0.616 |
| S4 exit debounce | θ=P90, M=2 | 20.0% | 239 (2h) | −2.192 | −2.481 | −3.468 | 0/4 | 0.616 |
| S5 DP on calendar | κ=8, c=0.5 | 3.0% | 50 (1h) | **+0.067** | −0.090 | −0.628 | 1/4 | 0.616 |
| S6 receding-horizon DP | λ=24, K=6 | 26.7% | 151 (3h) | −1.591 | −2.069 | −3.698 | 0/4 | 0.622 |

**±0.5% (w10):**

| Cand | tuned cfg | held % | streaks (med h) | tune $/d | full $/d | Aug $/d | months + | AUC |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| S1 | κ=0, hi=P90, lo=P50 | 13.4% | 273 (1h) | −0.711 | −1.097 | −2.414 | 1/4 | 0.594 |
| S2 | q_hi=0.9, q_lo=0.5 | 0.8% | 19 (1h) | −0.094 | −0.116 | −0.193 | 0/4 | 0.592 |
| S3 | θ=P90, D=2 | 18.2% | 256 (2h) | −2.068 | −2.330 | −3.221 | 0/4 | 0.594 |
| S4 | θ=P90, M=2 | 19.9% | 256 (2h) | −2.240 | −2.483 | −3.312 | 0/4 | 0.594 |
| S5 | κ=8, c=0.5 | 0.9% | 17 (1h) | **+0.102** | **−0.025** | −0.458 | 2/4 | 0.594 |
| S6 | λ=24, K=12 | 31.6% | 126 (6h) | −1.318 | −1.599 | −2.565 | 0/4 | 0.608 |

Every candidate was tested; none is omitted. Full grids in
`out/tune_<cand>_w<W>.json`; frozen finals in `out/final_<cand>_w<W>.json`.
(S5 w10's tie between c=0.5 and c=1.0 — identical masks — resolved to c=0.5
by the pre-registered first-in-enumeration rule.)

## 2 — The mechanism finding: the contiguity gradient is negative everywhere

E007 ended on the hypothesis that the oracle's edge is *contiguity*, which
per-hour threshold rules cannot buy. E008's machinery **can** buy it — and
measured its price. Every knob that buys contiguity loses money
monotonically (tune window, w4, central):

- **S1's bridge knob (θ_lo, at θ_hi=P90):** lo=P50 −$0.55/d (16% held) →
  lo=P40 −$0.67 → lo=P30 −$1.51 → lo=P20 −$3.07 → lo=P10 −$6.58/d (61%
  held). Every decile of extra patience holds more dip hours, and the dip
  hours lose more than the saved round trips.
- **S3's dwell knob (D, at θ=P90):** D=2 −$1.84/d → D=4 −$4.01 → D=8
  −$5.37 → D=12 −$9.51/d. The forced-extension hours are
  calendar-arbitrary, and the all-hours mean is −$0.19/h (M002 §1) — a pure
  dwell tax, exactly as the memo's ranking predicted.
- **S5's own optimum:** given the *choice* (the DP prices every bridge
  against a round trip), it refuses contiguity: at κ=0 more freedom to hold
  is monotonically worse (c=0.5, 26% held: −$0.77/d; c=2, 12%: −$0.30), and
  7 of its 12 configs choose the **empty mask**. Its three positive tune
  cells hold 0.6–3.0% of hours as median-1h singletons — it re-derived
  E007's fragments, just profitably-in-sample.
- **S6 (MPC)** held the most coherent streaks of the set (median 3–6h,
  26–32% held) and lost $1.6–2.1/day for it — smooth-and-wrong, the C2/C5
  failure mode with a better selector underneath.

So the two failure modes E007 separated do not have a profitable point
between them. The frontier from "fragmented but selective" (S5, S2) to
"contiguous but diluted" (S6, S3, S4), with S1 sweeping the middle, is
negative end to end: **selection quality survives out of window (AUC
0.59–0.62, same as E007's C3) but there is no exchange rate at which its
fragments can be consolidated into streaks that clear the $0.77–0.85 round
trip plus what stage 2 charges for real minting, recentering, and hedging.**

And the one configuration family that found in-sample profit *without*
contiguity — S5's extreme cells, mean tune value ≳ $1/h across 13–40
singleton holds — did not generalize: w4 June +$15.2 and w10 June/July
+$3.9/+$6.8, but May negative and **August −$12.4 to −$17.0 for 4–16 held
hours**. The top of the calendar's cell distribution is exactly where
13-observation estimation noise concentrates, and the August market punished
those cells specifically (the same weeks E007's C3 lost −$2.4/day on).

## 3 — Why this is a clean kill for the family, not a tuning accident

- **The grids were not floor-limited this time.** E007's optima all sat at
  the most conservative decile with the grid floor forcing ~10% held. E008's
  mechanisms could and did explore 0%–90% held, 1h–17h median streaks, and
  the empty mask was *reachable* (S5 chose it 7 times). The family's
  interior optimum is "hold almost nothing", and its best non-empty cells
  still lose full-window.
- **3/404 in-sample positives, all fragile.** All three are one mechanism
  (S5), one shrinkage (κ=8), near-zero held fractions, and all three are
  negative on held-out August by 4–9× their tune-window gain.
- **August agrees at every cell.** Twelve of twelve frozen candidate×arm
  cells negative held-out — most worse than their full-window rate.
- **The envelope does not rescue anything.** Best optimistic cell:
  S5 w10 −$0.007/day. Even free-ish hedge execution leaves the family
  under water.
- **The machinery is not the story.** All 38 blocking contract checks pass
  (§5): `always_in` reproduces E003 float-exact; `always_cash` is $0; the
  E006 oracle mask through this evaluator returns +$6.058/day (w4) and
  +$3.718/day (w10) — the evaluator prints large positives the moment a
  mask deserves them.

## 4 — H-timing, closed: the route map after E006 + E007 + E008

| Route | Tested by | Result |
|---|---|---|
| Perfect-foresight ceiling | E006 | +$6.06/day (w4) — real, and made of median-3h streaks chosen jointly with switch costs |
| Daily/coarse regime calls | M001 §2 | negative at 24h grain *even with foresight* |
| Per-hour causal thresholds | E007 | 0/540 positive; best selector (calendar, AUC 0.616) fragments into 272 median-1h streaks |
| Streak-aware rules (hysteresis, dwell, debounce, DP-on-forecast, MPC) | **E008** | 12/12 cells negative; contiguity gradient negative everywhere; 3/404 in-sample positives all fail August |

What remains untested is only what was deliberately out of scope for the
rule family: learned many-parameter policies (G2-era, blocked) and other
venues. Within the pre-committed scope — parametric causal timing rules on
ETH/USDC 0.05% under honest frozen costs — the family is exhausted, and the
operator pre-commitment resolves the venue accordingly.

## 5 — Validation

[`tests/test_e008_contracts.py`](tests/test_e008_contracts.py), blocking,
**38 checks, all pass** (re-run after the final phase; artifacts current):

- **Reproduction** — `always_in` mask == E003 committed lag1h_rh1h: `==` on
  net at all three envelope points, LP fees, recenter counts, w4 + w10,
  evaluated **uncached**.
- **Zero** — `always_cash` nets exactly $0, zero streaks.
- **Oracle** — E006's `held_central` mask through this evaluator ==
  E006's committed stage-2 numbers (+$6.058/day w4, +$3.718/day w10).
- **Causality** — S1/S3/S4/S5 masks invariant to scrambled August payoffs;
  S1–S4 truncated re-runs equal the full run at sampled boundaries; S2's
  score and S6's decisions recomputed from truncated data match exactly;
  S5/S6 optimizers consume only forecast series.
- **Tuning isolation** — the tuner raises on any held-out row; the final
  phase refuses to run until all 12 candidate×arm parameter sets are frozen
  on disk (it was run only after `out/tune_*.json` × 12 existed —
  commit 8e22719 precedes the final-phase commit).
- **Determinism** — no RNG; grids and tie-breaks fixed and ordered;
  signals/masks rebuild identically.
- **Accounting identity** — ledger gap ≤ 1e-6 asserted on every streak use
  and re-checked over all 11,884 cached streaks.

Memo pre-work (M002 §1's run/gap and decile tables) is reproducible with
the snippet recorded in the memo's own text; it touches stage-1 tune-window
quantities only.

## 6 — What this does not answer

- **Adverse selection / MEV.** Fee credit assumes our $1,015 takes its full
  pro-rata share of every in-range swap (K9). Every number here is
  therefore an **upper bound**; for this verdict the caveat is moot in
  direction — it would only deepen the losses — but any successor reading
  S5's "−$0.025/day, nearly flat" as "nearly viable" should note the true
  number is worse.
- **Learned policies.** Six mechanisms × ≤3 parameters is not a model
  class. A learned policy (G2's cost-honest retrain) could in principle
  find structure these rules cannot — but it would face the same negative
  contiguity gradient and the same $0.77+ round trip, on a pool whose
  always-in economics are 0.65–0.97 fees/gamma (K2).
- **Other venues.** Everything here is ETH/USDC 0.05% on Arbitrum at
  $1,420. The wstETH/WETH funding-carry package (B2) has a different
  economic engine (perp funding, not LP fees) and none of these results
  transfer to it automatically.
- **Four months of one market** remains the window; all four months and
  both arms agree on the sign.

## 7 — Reproducing this

```bash
cd ~/developments/llaminet/research
nix develop .#gate1 -c python backtest_model_server/e008/tests/test_e008_contracts.py
for c in s1 s2 s3 s4 s5 s6; do
  nix develop .#gate1 -c python backtest_model_server/e008/run_e008.py --phase tune --candidate $c --arm 4
  nix develop .#gate1 -c python backtest_model_server/e008/run_e008.py --phase tune --candidate $c --arm 10
done
nix develop .#gate1 -c python backtest_model_server/e008/run_e008.py --phase final --arm 4
nix develop .#gate1 -c python backtest_model_server/e008/run_e008.py --phase final --arm 10
```

Needs E003's parquets and funding CSV (as E006/E007). Total compute ≈ 5 min
warm, ≈ 20 min cold (`out/cache_w*.json` is git-ignored and rederivable;
tune grids resume from `*.partial.json` checkpoints if interrupted).

| Path | Purpose |
|---|---|
| [`streak_rules.py`](streak_rules.py) | The six pre-named mechanisms; frozen grids; signal reuse from e007 |
| [`run_e008.py`](run_e008.py) | Tune (May–Jul only) and final (all-frozen-first) phases |
| [`tests/test_e008_contracts.py`](tests/test_e008_contracts.py) | The blocking contracts of §5 |
| `out/tune_*.json`, `out/final_*.json` | Every grid point; every frozen result |

## 8 — What this changes

- **H-timing is closed on ETH/USDC 0.05%** (E006 ceiling real; E007 kills
  thresholds; E008 kills streak-aware rules — the pre-named residual of
  E007 §6, tested and refuted).
- **The operator pre-commitment executes**: the venue call resolves to the
  wstETH/WETH 0.01% funding-carry path (discovery card B2), with the K8
  margin/liquidation design pass as the hard prerequisite before any
  capital. No further experiments on this pool.
- **For the record**: the calendar selector's information is real and
  stable (AUC 0.59–0.62 across two experiments and both arms) — it is the
  *cost structure*, not the signal, that makes it unmonetizable here. If
  this strategy family ever runs on a venue with ~10× cheaper switches, the
  E008 mechanisms are the right first test, in this order: S5, S1, S2.
