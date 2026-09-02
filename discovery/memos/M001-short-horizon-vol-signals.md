---
id: M001
for: E007 (H-timing — causal-signal test)
date: 2026-09-02
status: final — feeds E007's pre-registration
---

# M001 — Short-horizon signals for the timing filter: constraints, external research, ranked candidates

> PROTOCOL §1 memo. E006 measured a tall timing ceiling and falsified the two
> obvious signal families in the same run. This memo does the research step
> before E007 names its candidates: state the constraints with numbers, pull in
> what the literature and practitioner record actually say, answer the
> coarseness sub-question with a measured table, and rank candidates by
> mechanism fit × data availability × parameter count. The ranked list below
> **is** E007's pre-named candidate set.

## 1 · The constraints, with their numbers

- **The bar.** A causal hour-level in/out policy on ETH/USDC 0.05% must net
  **≥ +$0.389/day central** through E006's stage-2 exact simulator — 6.4% of
  the exact oracle's +$6.06/day at ±0.2%, 10.5% of +$3.72/day at ±0.5%
  ([E006](../experiments/E006-timing-oracle-bound.md) §1).
- **What the oracle actually is.** Effectively a next-hour realized-variance
  predictor with a fee tiebreak: same-hour hedged gamma separates held hours at
  AUC 0.90, fees 0.66, intra-hour RV 0.37 — held hours are the *quiet* hours
  (E006 §4). Streaks are short: median 3h, p90 8h.
- **Falsified already** (E006 §5, do not re-propose as-is): Kaufman ER
  12/24/48h (AUC 0.526/0.501/0.476), rolling-std trailing vol 12/24/48h
  (0.452–0.466), previous-hour intra-hour RV (0.460).
- **The persistence headwind, and its real size.** E006 reported next-hour RV
  ACF(1) ≈ 0.22 decaying to 0.10 by lag 6 — *linear ACF on levels*. Measured
  here on the same swap stream in the space a threshold rule actually uses:
  **rank/log persistence of hourly RV is 0.62–0.63 at lag 1** (§3). The
  headwind is real but the levels-ACF overstated it; heavy tails were eating
  the linear correlation.
- **A mechanism cap on pure-RV prediction.** Even *perfect* knowledge of the
  next hour's intra-hour RV separates oracle membership at only flipped-AUC
  0.63 (E006's same-hour AUC 0.37). The oracle's actual target is next-hour
  `fees − hedged gamma` — variance is only one leg of it. Signals that nowcast
  the payoff itself outrank signals that nowcast RV alone, mechanically.
- **Inherited caveat.** Adverse selection/MEV is unmodelled and biases every
  timing result upward, more so for hour-picked positions (E006 §7). Any
  SUPPORTED verdict must restate it.

## 2 · The coarseness question — answered first, as pre-work

If a coarse (daily-scale) regime call retained most of the ceiling, E007 could
target daily vol regimes — far more persistent — and the hour-scale headwind
would be moot. Measured by re-running E006's DP under constraints
(same stage-1 payoffs, same switch costs, central point), then re-simulating
the constrained selections exactly through E003's `run_arm`
([`e007/constrained_oracle.py`](../../backtest_model_server/e007/constrained_oracle.py),
[`e007/out/constrained_oracle.json`](../../backtest_model_server/e007/out/constrained_oracle.json)):

**Stage-2 exact, $/day central** (stage-1 UB in parentheses):

| Constraint | ±0.2% (w4) | ±0.5% (w10) | ±2.0% (w40) | ±8.3% (w160) |
|---|---:|---:|---:|---:|
| unconstrained (E006) | **+6.06** (+8.85) | +3.72 (+5.73) | +0.81 (+1.29) | +0.07 (+0.14) |
| min-hold 6h | **+3.13** (+6.31) | +2.53 (+4.53) | +0.70 (+1.19) | +0.06 (+0.13) |
| min-hold 12h | +1.34 (+4.69) | +1.48 (+3.52) | +0.51 (+1.03) | +0.05 (+0.13) |
| min-hold 24h | −0.51 (+2.62) | +0.66 (+2.26) | +0.29 (+0.83) | +0.05 (+0.12) |
| decisions every 4h | +1.20 (+3.83) | +1.37 (+2.85) | +0.34 (+0.75) | +0.02 (+0.09) |
| decisions every 24h | **−0.92** (+0.38) | −0.30 (+0.48) | −0.08 (+0.26) | −0.00 (+0.05) |

Three consequences, all binding on the candidate ranking:

1. **Daily regime calls are dead — even with perfect foresight.** A policy that
   decides once a day at 00:00 UTC *loses money* at every width. Min-hold 24h
   is negative at the best width and retains only +$0.66/day at ±0.5% (59%
   capture needed — heroic). The reframe fails: there is no escape into
   daily-scale prediction. Slow signals (30-day implied vol as a standalone
   gate, weekly regime models) are disqualified as primary drivers.
2. **The viable coarse zone is 1–6h.** Min-hold 6h keeps +$3.13/day at ±0.2%
   (capture bar 12.4%) and +$2.53 at ±0.5% (15.4%). A smooth causal signal
   that naturally produces ≥6h streaks forfeits only half the ceiling — the
   filter does not need to replicate the oracle's 3h-median twitchiness.
3. **Stage-1 flatters coarse policies badly** (min-hold 24h w4: UB +$2.62 vs
   exact −$0.51/day — long streaks accrue in-streak recenter and gamma costs
   stage 1 never charges). E007 must tune and judge on stage-2 exact only.

## 3 · New target-property measurements (this memo's pre-work, local data)

Same swap stream as E006, ±0.2% oracle where membership is referenced.
Computed in the memo phase because they describe the *target*, not any
candidate (candidate outcomes stay untouched until Phase C).

**Aggregation persistence — the HAR mechanism, verified on our data.**
corr(past-k-hour RV, next-k-hour RV), hourly hops:

| k | 1h | 3h | 6h | 12h | 24h | 48h |
|---|---:|---:|---:|---:|---:|---:|
| Pearson (log) | 0.623 | 0.571 | 0.552 | 0.526 | 0.515 | 0.393 |
| Spearman | 0.633 | 0.578 | 0.532 | 0.524 | 0.587 | 0.519 |

Short-horizon RV is *rank*-predictable at ~0.6 — the E006 signals failed not
because the target is unpredictable but because uniform rolling std over
12–48h in levels is the wrong estimator for a 1–6h target. Note the k=1 row
is the *strongest*: aggregation does not need to recover predictability;
it was never absent in rank space.

**Seasonality — of the target and of oracle membership.**

- Median hourly RV by day-of-week (×1e-4): Mon 11.1, Tue 10.4, Wed 11.3,
  Thu 11.8, Fri 10.2, **Sat 6.2, Sun 7.5** — weekend RV is roughly half of
  midweek.
- Median hourly RV by hour-of-day: trough 7.8 at 06 UTC, peak **16.8 at
  14 UTC** (13–16 UTC ≈ 2× the Asian-morning trough) — the US session.
- Oracle held-rate: Sat 75.0% vs Mon 50.2%; by hour-of-day 48.7% (13 UTC) to
  67.2% (16 UTC). In-sample AUC of the seasonal held-rate: hour-of-day alone
  0.554, day-of-week alone 0.580, **dow×hod (168 cells) 0.681** — the last is
  an in-sample ceiling (fitted on the labels), but already above every
  falsified trailing signal, from a calendar.

**Intensity data availability.** The committed parquets carry per-swap
`timestamp`, `volume_usd`, `pool_liquidity`: swap-arrival counts (p50 750/hr,
p10 232, p90 2,627) and volume are computable at any sub-hour granularity with
no new fetches.

## 4 · External research, mapped to our constraint

- **HAR-RV** ([Corsi 2009]; crypto applications: [Ethereum HAR with structural
  breaks](https://www.tandfonline.com/doi/full/10.1080/23322039.2023.2300925),
  [survey](https://link.springer.com/article/10.1007/s10479-021-04116-x)):
  overlapping RV components at heterogeneous horizons is the standard
  short-horizon vol forecaster and is exactly the "multiple half-lives, few
  parameters" shape §3 says our target rewards. Crypto HAR papers forecast
  daily+ horizons; our need is 1–6h — the *structure* transfers, the
  published coefficients do not. Cost: zero (local).
- **Intraday/weekly seasonality** ([intraday HFT patterns — activity peaks
  16:00–17:00 UTC](https://arxiv.org/pdf/2009.04200), [macro news & intraday
  crypto vol seasonality](https://www.tandfonline.com/doi/abs/10.1080/00036846.2023.2212970),
  [recurring intraday components](https://arxiv.org/pdf/2306.17095),
  [weekend/overnight effects](https://quantpedia.com/strategies/intraday-seasonality-in-bitcoin)):
  crypto vol/volume have strong, stable hour-of-day and day-of-week structure
  tied to regional sessions; our §3 measurements match the published pattern
  (US-session peak, weekend lull). A calendar prior is causal by construction
  and near-zero-parameter. Cost: zero.
- **Trade-arrival intensity / MDH** (Clark 1973; Tauchen–Pitts 1983; Hawkes
  self-excitation: [Bacry et al.](https://www.researchgate.net/publication/234060166_Hawkes_model_for_price_and_trades_high-frequency_dynamics),
  [OFI via Hawkes](https://arxiv.org/html/2408.03594v1)): trade counts are the
  variance clock, contemporaneous and self-exciting — recent-minutes intensity
  at the hour boundary is a causal nowcast finer than any hourly close, and
  the same quantity drives the *fee* leg. Full Hawkes fits blow the parameter
  budget; last-N-minutes intensity vs trailing baseline is the 2-parameter
  version. Cost: zero (parquets).
- **Jump/continuous decomposition** ([Barndorff-Nielsen–Shephard 2004
  bipower](https://public.econ.duke.edu/~get/browse/courses/883/Spr15/COURSE-MATERIALS/Z_Papers/BNSJFEC2004.pdf),
  [Andersen–Bollerslev–Diebold "Roughing it up"](https://www.nber.org/system/files/working_papers/w11775/w11775.pdf)):
  the continuous component forecasts future vol better than raw RV; jump
  contributions are transient (crypto evidence is mixed on jump aftermath).
  Mechanism: our falsified prev-1h RV mixes jumpy hours in; bipower filtering
  should clean the nowcast. Cost: zero (swap stream supports bipower at
  swap-to-swap granularity).
- **Cross-venue lead** ([price discovery in crypto markets](https://arxiv.org/abs/2506.08718),
  [CEX/DEX pricing efficiency](https://www.sciencedirect.com/science/article/abs/pii/S0148619524000663)):
  for ETH, centralized venues (Binance) lead DEX prices at minutes scale in
  most studies (some recent work finds DEX leadership episodes — the direction
  is an empirical question per pair/period, which is fine: the *signal* is
  Binance's finer, earlier clock, not a directional bet). Binance 1m klines
  also carry `number_of_trades` — intensity from the lead venue. Cost: small
  public fetch (~176k rows for our window).
- **Implied vol / DVOL** ([Deribit DVOL](https://insights.deribit.com/industry/demystifying-dvol-futures/)):
  30-day horizon, and IV persistently overshoots RV (variance risk premium).
  §2 killed daily-scale gating, so a 30-day IV level cannot drive an hourly
  policy; at best a slow scaler. **Dropped from the candidate set** on the
  coarseness result — recorded here so E008+ does not re-propose it blind.
- **Funding-rate dynamics** (local HL series): slow, positioning-driven, no
  mechanism to next-hour RV at our horizon. **Dropped** (kept in the funding
  leg of the payoff, where it already lives).
- **LP-side literature** ([LVR ∝ σ²·gamma](https://arxiv.org/pdf/2106.12033),
  [Uniswap v3 LP risk/return audits](https://www.researchgate.net/publication/372151626_Risks_and_Returns_of_Uniswap_V3_Liquidity_Providers)):
  confirms the shape of our objective (hedged-LP loss rate ∝ realized
  variance; fees must outrun it) and that regime-aware in/out is the
  practitioner recommendation — but offers no causal hour-scale trigger we
  don't already have. Context, not a candidate.

## 5 · Ranked candidates (E007's pre-named set)

Ranked by mechanism fit × data availability × parameter count. Each: mechanism,
data, tuned params (≤2), and what falsifies it.

| # | Candidate | Mechanism (one line) | Data | Tuned params |
|---|---|---|---|---|
| C1 | **Trailing-payoff nowcast** — EWMA of past hours' freshly-centered payoff (`fees+funding−gamma`, causal at hour close), enter when above threshold | nowcasts the *actual* objective, both legs in $ — §1's mechanism cap says payoff beats any pure-RV proxy | local (stage-1 hour machinery, shifted 1h) | half-life, threshold |
| C2 | **Log-EWMA RV nowcast** — EWMA of log hourly RV with short half-life, enter when *below* threshold | rank persistence 0.63 at 1h; falsified signals used uniform 12–48h windows in levels — wrong estimator, not wrong target | local | half-life, threshold |
| C3 | **Seasonal prior** — dow×hod cell mean of hour payoff estimated on the tune window (shrunk to row/col means), enter when cell ≥ threshold | documented session/weekend structure; causal by construction; §3 in-sample ceiling 0.68 | local | shrinkage, threshold |
| C4 | **Binance boundary nowcast** — last-30m ETHUSDT 1m-kline RV (and its trade-count twin) at the hour boundary, enter when below threshold | lead venue, finer clock, fresher than any hourly close; MDH count leg included | small public fetch | lookback, threshold |
| C5 | **Continuous-vol nowcast** — C2 on bipower-filtered hourly RV (jump part removed) | continuous component persists; jumps pollute the nowcast (HAR-CJ) | local | half-life, threshold |
| C6 | **C1 × C3 combination** — payoff nowcast gated by the seasonal prior | orthogonal information: state nowcast × calendar prior | local | threshold pair (2) |

Order of testing = table order; if total runtime projects beyond budget, cut
from the bottom (C6 first, then C5, C4). Every candidate tested is reported —
no silent drops. DVOL and funding dynamics are pre-emptively out (§4).

**Falsifiers.** Each candidate is refuted by the E007 decision rule itself
(fails to beat $0/day central full-window through the stage-2 exact
simulator); C2/C5 additionally carry the E006 prior that their family already
failed once in cruder form — if the EWMA/log/bipower refinements do not move
AUC materially above the falsified 0.45–0.53 band, that closes the RV-proxy
family on this pool, which is itself a result worth recording.

## 6 · What this memo changes about E007's design

- **Tune and judge on stage-2 exact dollars only** (§2's stage-1 flattery).
  Tune window 2026-05→07; August held out untouched until final judgment.
- **Widths ±0.2% and ±0.5% only** — the constrained table shows w40/w160
  ceilings too thin for any capture fraction to matter.
- **Hour-boundary decisions, no imposed min-hold** — but smooth signals are
  *expected* to produce ≥6h streaks; the 6h-constrained ceiling (+$3.13/day)
  says that costs only half the ceiling, so smoothness is not a design flaw.
- **The capture bar the verdict quotes**: +$0.389/day = 6.4% of unconstrained
  at ±0.2%; against the 6h-coarse ceiling it is 12.4% — both get stated.
- **Adverse-selection caveat travels with any SUPPORTED verdict** (§1).
