# M006 — Capturing the LINK ceiling with a causal vol gate: the target is burst-dodging, not regime-riding

Discovery cycle run 2026-09-04 against binding constraint **K16 / card
[B6](../BACKLOG.md)** (operator go 2026-09-03). Harvest of E011 was done in
the E011 iteration itself (K16 written, B5 → SUPPORTED, B6 staged); this
cycle's §1 restates, measures the target's shape from committed artifacts
(§2), researches outward (§3), and pre-names E012's candidate set (§4).
Once E012 pre-registers against this memo it is **append-only**.

## 1 · Constraints (restated from [CONSTRAINTS.md](../CONSTRAINTS.md), numbers anchored)

- **K16** — the ceiling to capture: stage-2 exact **+$5.79/day central at
  ±0.6%** (opt +$10.74 / pess −$13.51), +$3.64 at ±1.8%, +$2.02 at ±8.1%;
  held ~97% in ~90h-median streaks; **daily-grain oracle retains 78%**
  (+$4.50/day), grain-4h retains 91% (+$5.29/day); wick-clean; capture bar
  **47%** for 10% APR. Descriptive lead: trailing-vol skip-AUC up to 0.85.
- **K14** — the same venue's best *static* arm: **+$0.915/day central at
  ±8.1%** — the number any gate must beat for the venue call to prefer
  gating over just holding wide.
- **K7 / K11** — the inheritance: on the control, selection quality never
  became capture (0/540, then 3/404 tune configs positive; the contiguity
  gradient negative everywhere). The two failure modes any E012 verdict
  must name if they recur: **fragmentation** (good picks arrive as
  fragments against the switch cost) and **smoothing-away-selectivity**
  (contiguity bought by blurring the signal until it selects nothing).
- **K15** — wick honesty at per-swap granularity is mandatory on every
  held set. **K9** — all positives are full-share upper bounds. **K10 /
  bot ADR 0008** — no capital on any of this.
- **B6's bar** (pre-registered before this memo): ≥ **+$2.74/day central
  full-window** AND held-out August survival AND beat the best static arm.

## 2 · Target properties measured this cycle (pre-work from committed E011 artifacts — describes the *target*, touches no candidate outcome)

Measured 2026-09-04 from `e011/out/stage1_hours_arm_*.csv` (`held_central`)
and `e011/out/descriptive.json`, committed by E011:

- **Correction to B6's language.** The card says "skip episodes are
  multi-day vol regimes". The committed verdict-arm mask says otherwise:
  the oracle skips **13 episodes of 1–18h (median 5h, total 87h = 3.0%)**,
  clustered inside loud *weeks* — May 4/8/13/22/30 (5 episodes, 33h),
  Jun 15 (4h), **Aug 11–22 (7 episodes, 50h)**. The ±8.1% arm skips only
  4 episodes (32h), all in August. What is multi-day is the *held streaks*
  (median ~93h) and the loud seasons the bursts cluster in — not the
  skips. **The gate's job is dodging sharp sub-day bursts and re-entering
  between them**, not classifying long regimes. (The oracle re-enters
  between the August bursts — e.g. ~87h held between Aug 15 12h and
  Aug 19 03h — and those between-burst holds are part of the ceiling.)
- **Asymmetry.** Held hours average **+$0.95/h** of stage-1 payoff;
  skipped hours average **−$11.9/h**, worst single hour **−$230.5**
  (Aug 19 15 UTC). Being wrongly *in* during a burst costs ~12× what being
  wrongly *out* forgoes → the optimal band is asymmetric: **exit fast,
  re-enter carefully** (Dixit band with a hair trigger on one side).
- **The tune/test split is brutal by construction.** May–Jul contains
  **37 skipped hours, −$194** of dodgeable stage-1 damage; August contains
  **50 skipped hours, −$840**. 81% of what the gate exists to dodge sits in
  the held-out month. E012 is an out-of-sample test even before its
  isolation rules; a gate that memorizes May's bursts buys almost nothing.
- **Where the signal lives.** `rv_prev_1h` (intra-hour swap RV of the last
  completed hour): held p50 **0.00028** vs skipped p50 **0.0017** (6.1×),
  and held p75 (0.00067) < skipped p25 (0.00075) — quartile-level
  separation (AUC 0.85 as a skip signal). RV-12h separates at 0.72
  (flipped); RV-48h is nearly useless (0.56 flipped). **Fast windows carry
  the signal; long windows smooth it away** — which reorders the candidate
  ranking below and flags the mandated HAR blend as the at-risk shape.
- **Fragmentation is affordable here, finally.** The oracle itself pays
  ~13 round trips ≈ $165 ≈ **$1.39/day** at M005 §3's ~$12.7. A causal
  gate at 4h grain that doubles that still fits inside the ceiling; K7's
  killer (median-1h fragments) is structurally excluded by grain +
  hysteresis, not by hope.

## 3 · External research (searched 2026-09-03..04; found → cited, looked-for-and-NOT-found recorded)

**Realized-vol persistence and forecasting at daily/weekly aggregation —
the HAR thread (M001 §1 continued).**
[Corsi (2009), "A Simple Approximate Long-Memory Model of Realized
Volatility"](https://statmath.wu.ac.at/~hauser/LVs/FinEtricsQF/References/Corsi2009JFinEtrics_LMmodelRealizedVola.pdf)
— the additive cascade of daily/weekly/monthly RV components reproduces
long-memory persistence with three coefficients; the canonical daily-grain
vol forecaster. Crypto transfers:
[HAR on Ethereum RV with structural breaks (Cogent Econ. & Finance, 2024)](https://www.tandfonline.com/doi/full/10.1080/23322039.2023.2300925)
and an
[extended-HAR Bitcoin study (JRFM/IJFS 2026)](https://www.mdpi.com/2227-7072/14/4/81)
find HAR-class models competitive for BTC/ETH daily RV;
[Hansen & Lunde's RV-forecasting survey](https://public.econ.duke.edu/~get/browse/courses/201/spr11/DOWNLOADS/VolatilityMeasures/SpecificlPapers/hansen_lunde_forecasting_rv_11.pdf)
for the measurement background. M001 §1 verified the aggregation-persistence
mechanism on our control data (rank corr ~0.52–0.59 at 12–24h hops).
*Read against §2:* HAR forecasts the **level** well; our target is the
**tail burst**. A blend that averages 1d/3d/1w windows will lag burst
onset by construction — the E008 "smoothing-away-selectivity" shape. It
stays in the set (B6 mandates it) with that risk named as its
falsification mechanism.

**Vol-regime gating of returns — the vol-managed / vol-targeting
literature (a well-trodden daily-grain field).**
[Moreira & Muir (2017), "Volatility-Managed Portfolios", J. Finance](https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12513)
([NBER w22208](https://www.nber.org/papers/w22208)) — scaling exposure by
inverse trailing variance raises Sharpe across factors; vol changes are
not compensated by proportional return changes, and the effect survives
monthly (coarse) rebalancing — vol timing pays at exactly our decision
grain. Counterweight: the out-of-sample implementability critique
(real-time versions of the spanning-regression strategy underperform —
see the "Understanding/downside-risk" follow-ups in
[JBF 2021](https://www.sciencedirect.com/science/article/abs/pii/S0378426621001576)) —
one more reason E012's August isolation is the deciding clause.
[Bongaerts, Kang & van Dijk (2020), "Conditional Volatility Targeting", FAJ](https://repub.eur.nl/pub/130215/Bongaerts-Kang-van-Dijk-Conditional-volatility-targeting-2020-FAJ.pdf)
— unconditional vol targeting churns (turnover 2.0–2.6×/yr) for little;
conditioning the de-risking on **high-vol states only** keeps the benefit
and cuts the turnover — the exact shape of a high-quantile skip gate.
Harvey et al. (2018),
["The Impact of Volatility Targeting"](https://researchgate.net/publication/328870981_The_Impact_of_Volatility_Targeting)
— vol scaling reduces tail risk mostly in the assets whose vol is
persistent (crypto qualifies); implementation literature converges on
**buffer bands / no-trade boundaries** to control turnover
([optimal rebalancing boundary for target-vol, JAM 2025](https://link.springer.com/article/10.1007/s11408-025-00486-5)).
Direct support for two-threshold-plus-coarse-grain shapes.

**Hysteresis and dwell under switch costs.** M002 §2's thread carries
unchanged ([Dixit 1989](https://www.semanticscholar.org/paper/Entry-and-Exit-Decisions-under-Uncertainty-Dixit/05d7585f0c2051d2d1f3a45bb1ca1ed5bba6bbdd);
Davis & Norman 1990; [Delgado, Dumas & Puopolo 2015](https://www.sciencedirect.com/science/article/abs/pii/S0378426614003963);
the Schmitt trigger). New at this venue's numbers: the two sides of the
band are wildly asymmetric (−$11.9/h in-during-burst vs ~−$1/h
out-during-calm net of gamma, §2), so the calibration question is not
M002's "how wide a band" but "how *asymmetric*" — exit threshold near the
distribution's tail, re-entry near its middle.

**Vol-regime durations.** Markov-switching GARCH on crypto
([multi-scale MS-GARCH, arXiv 2606.06190](https://arxiv.org/html/2606.06190v1);
MS-GARCH outperforms single-regime for BTC/ETH/XRP/LTC in structural
instability) and general HMM regime work report calm-state dwells of
~25–45 trading days and turbulent dwells of ~8–14 days at daily grain,
with turbulent states resolving faster than calm ones — consistent with
our finer-grain picture (multi-day loud *weeks* containing 1–18h damage
bursts). Nothing in this literature decides between "skip the week" and
"skip the burst"; §2's between-burst holds say the money is in the latter.

**The AMM mechanism — why a vol gate should work at all.**
[Milionis, Moallemi, Roughgarden & Zhang (2022), "Automated Market Making
and Loss-Versus-Rebalancing"](https://arxiv.org/pdf/2208.06046) — LP bleed
to arbitrageurs (LVR) scales with **σ²** × marginal liquidity, while fee
income scales roughly with volume (~σ¹): net LP PnL turns negative beyond
a vol threshold. A vol gate truncates the σ² tail and keeps the fee body —
this is the theory under E011's measured held-hours f/g 2.10 vs 1.34
always-in. Strategy-level corroboration:
[Fan et al., "Strategic Liquidity Provision in Uniswap v3" (AFT 2023)](https://drops.dagstuhl.de/storage/00lipics/lipics-vol282-aft2023/LIPIcs.AFT.2023.25/LIPIcs.AFT.2023.25.pdf)
and the practitioner literature agree that at high vol the LP's optimal
action is withdrawal.

**Looked for and NOT found:** any LINK-specific realized-vol persistence
or forecasting study (closest: a prediction-market vol paper that includes
LINK 5-day RV as a target, [arXiv 2604.01431](https://arxiv.org/pdf/2604.01431) —
macro-contract signals, not usable here); any public 2025–26 JIT /
adverse-selection measurement for mainnet LINK/WETH 0.30% (M005 §4's
not-found stands; K9 unchanged); any academic treatment of vol-gating a
**delta-hedged concentrated** LP position at sub-daily grain — the precise
object E012 tests appears unstudied, so the general vol-timing and LVR
threads above are the closest anchors.

## 4 · Ranked candidates — E012's pre-named set (≤ 6 rules, ≤ 3 params each, grids frozen here)

**Common definitions (shared by all candidates; part of the pre-naming):**

- **Close series:** hourly USD closes `c_t = p0·u0` at hour boundaries
  from the committed `stage1_hours_*.csv` (pool price × ETH mark);
  `r_t = log(c_t/c_{t-1})`. **Swap-RV series:** intra-hour realized vol
  from the swap stream (`signals11.py`'s construction): for the hour
  ending at boundary t, `rv_swap(t) = sqrt(Σ Δlog(price)²)` over that
  hour's swaps. Both are causal at boundary t (use data ≤ t only).
- **Trailing RV:** `RV_n(t) = std(r_{t-n+1..t}, ddof=1)` — e006/e011's
  `trailing_signals` definition, unchanged.
- **Decision grain g:** the gate's state may change only at UTC epoch
  boundaries divisible by g hours (e007 `dp_grain` convention). Pre-named
  per candidate below; only g ∈ {4h, 24h} appears.
- **Hysteresis semantics (M002-S1 shape on a vol selector):** two
  thresholds θ_in < θ_out. If OUT and signal ≤ θ_in → enter; if IN and
  signal ≥ θ_out → exit; otherwise hold state. **Skip = loud** (the E011
  inversion): the selector is vol itself, exit-on-loud, enter-on-quiet.
- **Thresholds as quantiles, frozen to absolute values:** θ's are
  specified as quantiles of the signal's distribution over the TUNE
  window's valid hours (2026-05-01→08-01), converted once to absolute
  signal values and **frozen on disk** before any August or full-window
  evaluation. August is never touched by any quantile computation.
- **Warm-up / undefined signal → IN.** The gate is a skip-overlay on
  always-in; before a signal's window fills, the state is IN.
- **Initial state IN** at the window start (after warm-up rule, identical).
- **Evaluation:** the mask's maximal held runs are re-simulated exactly
  through E011's stage-2 evaluator (`exact11.run_streaks` — fresh mint at
  streak start, lag1h_rh1h inside, burn+flatten at exit, cash outside),
  per arm, per coupled envelope point. No stage-1 shortcut anywhere in
  tuning or verdict.

**The set, ranked by expected capture (mechanism → expected effect →
falsification):**

- **V1 — trailing-RV hysteresis, 4h grain** *(the B6-mandated S1 shape;
  rank 1).* Signal `RV_n` on hourly closes. Params: n ∈ {12, 24, 48},
  q_in ∈ {0.30, 0.50}, q_out ∈ {0.80, 0.95} → **12 configs/arm.**
  *Mechanism:* RV-12h separates at 0.72 flipped and persists at exactly
  the burst-cluster timescale; the asymmetric band exits into the tail
  and re-enters at mid-distribution, riding through single quiet hours.
  *Expected:* exits within ≤ 4h+n-lag of burst onset, re-enters between
  bursts → captures 50–75% of dodgeable damage; central estimate
  **+$2 to +$4.5/day at ±0.6%** if the onset lag doesn't eat the burst's
  first (worst) hours — the May 4 burst was 2h long and is likely missed
  entirely; the 12–18h August bursts are the prize.
  *Falsified by:* full-window central < +$0.915/day, or August ≤ $0 (the
  onset-lag story: trailing vol reacts after the damage).
- **V4 → rank 2 — prev-hour swap-RV hysteresis, 4h grain** *(the AUC-0.85
  separator, used raw).* Signal: median of the last m completed hours'
  `rv_swap`. Params: m ∈ {1, 4}, q_in ∈ {0.30, 0.50}, q_out ∈
  {0.80, 0.95} → **8 configs/arm.** *Mechanism:* the fastest causal
  signal available (1h data lag vs 12–48h window lag); quartile-level
  separation (§2); m=4 trades 3h of extra lag for chatter suppression.
  *Expected:* best burst-onset latency of the set; more round trips than
  V1 (the signal is spiky) — the test of whether **fast + hysteresis**
  beats **slow + smooth**. Same band as V1: +$2 to +$4.5/day at ±0.6% if
  capture works at all. *Falsified by:* fragmentation — if its tune-best
  cells pay > ~30 round trips/119d, K7's shape has returned at this venue.
- **V5 — EWMA-RV hysteresis, 4h grain** *(RiskMetrics shape).* Signal:
  `σ²_t = λσ²_{t-1} + (1−λ)r²_t` on hourly closes (seeded from the first
  48h; undefined → IN). Params: λ ∈ {0.97, 0.99, 0.995} (half-lives
  ~23h / ~69h / ~139h), q_in ∈ {0.30, 0.50}, q_out ∈ {0.80, 0.95} →
  **12 configs/arm.** *Mechanism:* exponential memory reacts to a burst
  within 1–2h (new r² enters immediately) yet decays smoothly —
  a one-parameter compromise between V1 and V4. *Expected:* between V1
  and V4; λ=0.97 is the live candidate. *Falsified by:* same clauses; if
  only λ=0.995 survives tuning, the rule has become a slow regime
  classifier and §2 says those miss the bursts.
- **V2 — single-threshold + minimum dwell, 4h grain** *(the B6-mandated
  dwell/min-hold variant; M002-S3 shape).* Signal `RV_n`; skip when
  `RV_n ≥ θ`; after any state change, no change for D hours. Params:
  n ∈ {12, 24}, q ∈ {0.70, 0.90}, D ∈ {24, 48, 96} → **12 configs/arm.**
  *Mechanism:* buys contiguity by fiat rather than by band asymmetry —
  the control's S3, transplanted to a venue where the payoff for
  contiguity is real. *Expected:* **worse than V1/V4** — §2 shows the
  oracle re-enters between clustered bursts within ~1–4 days; a 96h dwell
  after an exit forfeits exactly those between-burst holds (~$0.95/h).
  Included because B6 mandates the shape and because its failure mode
  (dwell tax > chatter saved) is the cleanest measurement of whether
  contiguity-by-fiat can ever beat contiguity-by-hysteresis here.
  *Falsified by:* trailing V1 at every tune cell.
- **V6 — trailing-RV hysteresis at 24h grain** *(the daily-cadence
  variant).* V1's rule, decisions only at 00:00 UTC. Params: n ∈
  {24, 48, 72}, q_in ∈ {0.30, 0.50}, q_out ∈ {0.80, 0.95} →
  **12 configs/arm.** *Mechanism:* the constrained oracle says daily
  decisions retain 78% of the ceiling — if vol regimes are *day-scale*
  persistent, a midnight-boundary rule captures the retained ceiling with
  ~30 decisions/window of chatter exposure. *Expected:* the mean 12h
  reaction lag halves what V1 captures of any burst that starts mid-day
  (Aug 15's began at 00h UTC — luck cuts both ways); **+$1 to +$3/day at
  ±0.6%** if day-scale persistence dominates, near-zero if burst timing
  dominates. Its gap to V1 measures how much of the capture problem is
  *cadence* vs *signal*.
- **V3 — HAR-blend hysteresis, 24h grain** *(the B6-mandated HAR /
  multi-window blend; rank last, risk named).* Signal: equal-weight mean
  of z-scored {RV_24h, RV_72h, RV_168h} (z from tune-window mean/sd —
  Corsi's cascade without fitted coefficients; no regression, nothing to
  overfit). Params: q_in ∈ {0.30, 0.50}, q_out ∈ {0.80, 0.95} →
  **4 configs/arm.** *Mechanism:* if the loud *weeks* (not the bursts)
  are the true unit of damage, the blend's stability wins August by
  sitting out Aug 11–22 wholesale. *Expected:* the smoothing risk is
  named up front — RV-48h already separates at only 0.56-flipped, so the
  168h leg likely dilutes to uselessness: **the E008
  "smoothing-away-selectivity" failure mode is this candidate's predicted
  outcome**, and measuring it cleanly at the venue where smoothing
  *should* work (if it works anywhere) is the point. *Falsified by:*
  held-fraction ≈ 1 with no August dodging (blur), or fragmentation-free
  but negative capture.

**Excluded, with reasons:** Binance-side/external selectors (E007 C4
falsified the family; no new mechanism); DVOL/funding-based gates (M001
§4 unchanged — funding is a carry input, not a burst predictor); learned
policies and fitted-coefficient HAR regressions (parameter budget, G2
posture, nothing to pre-name); calendar/seasonal gates (E011 measured the
calendar at 0.56 August OOS — dead on this venue); per-hour (grain-1h)
variants (K7's fragmentation shape, and grain-4h retains 91% of the
ceiling so nothing is bought by going finer).

**Data needs:** all local — `e011/out/stage1_hours_*.csv` (closes, hourly
payoffs for diagnostics), E010's committed LINK/WETH parquets + funding
CSVs (exact evaluation), `e011` machinery by import. **No new fetches; no
new data purchases; ~10 MB of new artifacts.**

**Cost to test:** ~60 configs × 2 arms exact-simulated on the tune slice
(minutes each at worst) + 12 frozen finals × 3 envelope points — hours,
not days, on the existing frozen stack.

**The falsification bar for the whole family** is E012's decision rule
(pre-registered next, inheriting B6): SUPPORTED needs a pre-named
candidate with frozen params to clear **+$2.74/day central full-window**,
positive held-out August, and beat the same-arm always-in on both;
REFUTED if none beats **max(+$0.915/day, the best static arm)** — i.e. no
gate beats just holding ±8.1% — or every target-clearing candidate fails
August. A REFUTED here, after E007 and E008, closes the "causal vol gate"
family on this venue's ceiling and returns the venue call to the operator
with the ceiling marked *unrealizable at current knowledge*.
