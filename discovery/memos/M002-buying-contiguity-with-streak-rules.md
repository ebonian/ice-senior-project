---
id: M002
for: E008 (H-timing — streak-aware rules)
date: 2026-09-03
status: final — feeds E008's pre-registration
---

# M002 — Buying contiguity without losing selection: streak-aware in/out rules

> Discovery-cycle memo per [`../PROTOCOL.md`](../PROTOCOL.md), for hypothesis
> card [B1](../BACKLOG.md). E007 killed the per-hour threshold family and
> measured *why*: the best causal selector picks genuinely good hours but
> delivers them as median-1-hour fragments that switch costs erase. This memo
> researches the one pre-named residual — rules that choose **runs** of hours —
> and ranks the candidate set E008 will freeze. The binding constraint is K7;
> the resource it must be reconciled with is K4/K5/K6.

## 1 · The constraints, with their numbers

Pulled from [`../CONSTRAINTS.md`](../CONSTRAINTS.md), not from memory:

- **K1 (the bar).** Net **≥ +$0.389/day central** on $1,420 through the frozen
  Gate-1 engine (`gate1-2026-08-29`, envelope `e003-2026-08-29`), stage-2
  exact simulation, full frozen costs.
- **K4 (the resource).** The ceiling is real — perfect-foresight in/out nets
  **+$6.06/day at ±0.2%**, +$3.72 at ±0.5% — and its substance is
  **contiguity**: the oracle's hours arrive in median-3h streaks chosen
  *jointly* with switch costs ([E006](../../loop/experiments/E006-timing-oracle-bound.md)).
- **K5 (the price of motion).** Mean round-trip switch cost **≈ $0.76**
  (re-measured on the tune window, central point: $0.770 at w4 = $0.366 enter
  + $0.404 exit; $0.852 at w10). Daily-grain decisions lose *even with
  foresight* (24h grain negative at every width); the viable decision scale
  is **1–6h**, and a min-hold-6h oracle still keeps +$3.13/day at w4
  ([M001 §2](M001-short-horizon-vol-signals.md)).
- **K6 (the selector).** The dow×hod calendar (E007's C3) is the best causal
  selector measured on this pool: **AUC 0.616**, held-set mean stage-1 payoff
  **+$0.42/h** full-window (72% oracle overlap at ~10% held). The smooth
  EWMAs (C2/C5) hold 4–5h streaks but select at AUC 0.54–0.57
  ([E007](../../loop/experiments/E007-causal-signal-test.md)).
- **K7 (the binding constraint).** Per-hour threshold rules cannot monetize
  selection: **0/540 tune configs positive**; C3's picks arrive as 272
  median-1h fragments whose ~$0.76 round trips erase a +$0.42/h edge.
  **Selection and contiguity must arrive together.**
- **K9 (the caveat that travels).** Fee credit assumes full liquidity share;
  adverse selection/MEV unmodelled — every positive number is an upper bound.
- **K10 (process).** One variable; decision rules pre-registered; tune
  May–Jul only, August held out; stage-2 exact is the only judge (M001 §2:
  stage 1 flatters coarse policies badly).

**New pre-work measurements** (tune window 2026-05-01→07-31 only; stage-1 and
selector *structure* only — no candidate outcome was computed; script output
recorded in the E008 report's validation section):

Calendar signal CAL_κ=0 (E007's C3, tune-window cells), conditional mean
stage-1 payoff of hours **above** each tune-window decile:

| θ ≥ | held frac | w4 mean $/h | w10 mean $/h |
|---|---:|---:|---:|
| P50 | 50% | +0.196 | +0.193 |
| P70 | 30% | +0.369 | +0.323 |
| P80 | 20% | +0.465 | +0.397 |
| P90 | 10% | +0.625 | +0.537 |

Two structural facts drive the whole memo:

1. **The fragmentation is shallow.** At w4 the above-P70 mask forms 514 runs
   (median 1h) with 511 interior gaps — **250 of them ≤ 2h**; at P80, 132 of
   366 gaps are ≤ 2h. The calendar's good hours are separated mostly by
   *short dips*, not long deserts: a mechanism that bridges 1–2h dips merges
   hundreds of round trips into few.
2. **The in-sample decile means are inflated by cell noise.** Each of the
   168 dow×hod cells is estimated from ~13 tune observations of a ±$1.5–2/h
   target, so neighbouring cells differ by sampling noise of the same order
   as the whole decile spread — this is *why* a genuinely informative
   calendar thresholds into 1h fragments. It also means realized quality is
   below the table above: E007 measured the P90 held set at **+$0.42/h**
   full-window against +$0.625 in-sample — a ×0.67 haircut to carry into
   every effect-size estimate. Stage 2 then keeps only ~0.65–0.69 of stage-1
   net even for the oracle's 3.8h-mean streaks (E006: 6.06/8.85 at w4).

**The break-even arithmetic** every candidate faces: a streak of L hours at
realized quality μ $/h must clear `μ·L·(stage-2 retention ~0.68) > round-trip
~$0.77` *plus* the dilution of whatever sub-threshold hours the mechanism
holds to buy L. At the target, the whole policy must clear +$35.8 over the
92-day tune window (+$46.3 over 119 days).

## 2 · External research

What the constraint rhymes with, searched 2026-09-03. Claims are cited;
what was looked for and **not** found is recorded at the end.

**Hysteresis bands under switching/transaction costs — the canonical answer.**
[Dixit (1989), "Entry and Exit Decisions under Uncertainty"](https://www.semanticscholar.org/paper/Entry-and-Exit-Decisions-under-Uncertainty-Dixit/05d7585f0c2051d2d1f3a45bb1ca1ed5bba6bbdd)
(JPE 97:620–638) is the exact shape of our problem: an agent paying sunk
costs to enter/exit an activity under an uncertain payoff should use **two
trigger levels** — enter well above break-even, exit well below it — and the
band of inaction is wide *even for small sunk costs*. The portfolio version
is the **no-trade region** of
[Davis & Norman (1990) / Dumas & Luciano (1991)](https://www.csef.it/WP/wp287.pdf)
(proportional costs ⇒ a no-trade cone whose width grows with the cost level;
see also [Delgado, Dumas & Puopolo (2015), "Hysteresis bands on returns,
holding period and transaction costs", J. Banking & Finance 57:86–100](https://www.sciencedirect.com/science/article/abs/pii/S0378426614003963)).
The engineering twin is the
[Schmitt trigger](https://www.allaboutcircuits.com/tools/hysteresis-comparator-calculator/):
a comparator with a single threshold "chatters" when the input hovers near
it — two thresholds separated by more than the noise amplitude eliminate the
chatter. Our K7 failure *is* comparator chatter: cell noise of ±$0.4–0.5/h
around a single decile threshold. Design rule imported: **the θ_hi/θ_lo gap
must exceed the calendar's cell noise**, which the pre-work sizes at roughly
2–4 deciles of the signal distribution.

**Minimum dwell / debounce — contiguity by constraint.**
Switched-systems control guarantees stability by forbidding fast switching:
[Hespanha & Morse (1999), "Stability of switched systems with average
dwell-time"](https://web.ece.ucsb.edu/~hespanha/published/avedwell.pdf)
(and the dwell-time literature descending from Morse 1996). The trading
version is the confirmation/holding-period filter: filter rules date to
Alexander (1961) and
[Fama & Blume (1966)](https://www.researchgate.net/publication/227374917_Filter_Rule_Tests_of_the_Economic_Significance_of_Serial_Dependencies_in_Daily_Stock_Returns),
whose central finding — profits die once transaction costs are charged — is
K7 stated sixty years early; band + holding-period variants appear throughout
the technical-trading literature
([Brock, Lakonishok & LeBaron 1992](http://technicalanalysis.org.uk/support-and-resistance/BrockLakonishokLeBaron1992.pdf)).
Mechanism imported: a dwell floor caps round trips per week mechanically;
its known cost is holding hours the selector wanted to drop — M001 §2
already priced the foresight version of that (min-hold 6h keeps 52% of the
w4 ceiling; min-hold 24h keeps −8%).

**Forecast-then-optimize / receding horizon — contiguity by optimization.**
[Boyd, Busseti et al., "Multi-Period Trading via Convex Optimization"
(2017)](https://pdfs.semanticscholar.org/aad0/1568eba08d6a53e7d4143ab674cb263d3f0d.pdf):
plan a trade sequence over a horizon against *forecast* returns with explicit
transaction costs, execute only the first step, re-plan each period — model
predictive control for portfolios. The stochastic-control ancestor is
optimal switching with switching costs
([Brekke & Øksendal (1994)](https://link.springer.com/article/10.1007/s00245-025-10341-8)
and the starting-and-stopping literature). This is *exactly* E006's DP with
foresight replaced by a forecast — the mechanism K4 says owns the ceiling.
The caution comes from
[Elmachtoub & Grigas, "Smart Predict-then-Optimize" (2022)](https://www.researchgate.net/publication/320583030_Smart_Predict_then_Optimize):
prediction accuracy and decision quality are not the same objective — a
forecast that is wrong in the *pattern* the optimizer exploits (here: cell
noise that the DP reads as bridgeable structure) produces confidently bad
plans. Design rule imported: shrink the forecast (κ) and/or inflate the
planning costs (c) as explicit knobs against optimizer-of-noise bias.

**Looked for and not found.**
- Any published **hour-scale in/out policy for AMM LPs under honest switch
  costs**. The Uniswap-v3 literature optimizes *range placement and width*
  ([Fan et al., "Strategic Liquidity Provision in Uniswap v3"](https://arxiv.org/html/2106.12033v5))
  or documents JIT liquidity at block scale
  ([Uniswap Labs](https://blog.uniswap.org/jit-liquidity)); nobody publishes
  the "when to be in the pool at all, hourly, net of mint/burn/hedge costs"
  problem. E006–E008 appear to be measuring something unpublished.
- A **closed-form band calibration** usable here: Dixit/Davis–Norman bands
  are continuous-time diffusion results; no discrete-time, forecast-driven,
  empirically-parameterizable formula for our payoff process was found —
  hence pre-registered grids rather than derived band widths.
- Evidence that **decision-focused (SPO-style) training** of a small
  forecast beats plug-in forecasts at this parameter budget — the literature
  is about learned models with many parameters; recorded as a G2-era idea,
  out of scope for a ≤3-parameter rule family.

## 3 · Ranked candidates (E008's pre-named set)

All six are **streak-aware policies on the selectors E007 already measured**
— the dow×hod calendar `CAL_κ` (C3's construction: cells from tune rows
only, shrinkage κ toward the tune global mean) and the payoff EWMA `PAY_λ`
(C1's construction) — evaluated at w4 (±0.2%) and w10 (±0.5%) only (M001
§6). ≤3 tuned parameters each; grids frozen here. Thresholds Pxx are
tune-window quantiles of the signal, fixed before any outcome is seen
(E007's convention). NaN signal ⇒ out. Initial state: out. Ties in tuning:
first config in the enumeration order below.

The set covers the three pre-named mechanism classes from E007 §6:
**(a) hysteresis** = S1, S2; **(b) dwell/debounce** = S3, S4;
**(c) DP / receding horizon over a causal forecast** = S5, S6.

| # | Candidate | Class | Tuned params (grid) | Configs/arm |
|---|---|---|---|---:|
| S1 | **Calendar hysteresis** — out→in iff CAL_κ(t) ≥ θ_hi; in→out iff CAL_κ(t) < θ_lo | a | κ ∈ {0,8,32}; θ_hi ∈ {P50,P60,P70,P80,P90}; θ_lo ∈ {P10,P20,P30,P40,P50} | 75 |
| S2 | **Blend hysteresis** — score(t) = min(F_PAY(PAY_24(t)), F_CAL(CAL_0(t))) where F are tune-window ECDFs (E007 C6's score, λ=24/κ=0 inherited from E007's tuned values); enter iff score ≥ q_hi, exit iff score < q_lo | a | q_hi ∈ {0.5,0.6,0.7,0.8,0.9}; q_lo ∈ {0.1,0.2,0.3,0.4,0.5} | 25 |
| S3 | **Minimum dwell** — enter iff CAL_0(t) ≥ θ; hold ≥ D hours; from age ≥ D exit iff CAL_0(t) < θ (κ=0 inherited) | b | θ ∈ P10..P90 (9); D ∈ {2,3,4,6,8,12} | 54 |
| S4 | **Exit debounce** — enter iff CAL_0(t) ≥ θ; exit only after M consecutive hours with CAL_0 < θ (bridges gaps < M, pays for the trailing hours; κ=0 inherited) | b | θ ∈ P10..P90 (9); M ∈ {2,3,4} | 27 |
| S5 | **DP over the calendar forecast** — E006's exact two-state DP run on ŷ_t = CAL_κ(t) with constant switch costs c·(ē, x̄), where ē, x̄ are tune-window mean stage-1 enter/exit costs (central); execute the DP mask | c | κ ∈ {0,8,32}; c ∈ {0.5,1,2,4} | 12 |
| S6 | **Receding-horizon DP (MPC)** — at each boundary t, forecast ŷ_{t+k} = CAL_0(t+k) + r_t·φ^k for k < K, where r_t = EWMA_λ of past residuals (payoff_h − CAL_0(h), h ≤ t−1) and φ = 2^(−1/λ); DP over the K-hour horizon from the policy's current state (switch costs ē, x̄ as S5 with c=1; exit charged if in at horizon end); execute hour t's decision only | c | λ ∈ {8,16,24}; K ∈ {6,12,24} | 9 |

Testing order = table order; every candidate tested is reported, no silent
drops. Total 202 configs/arm, 404 overall — the same order as E007's 540,
affordable under the shared per-streak cache.

**Per-candidate mechanism, expected effect, falsification** (all effect
sizes carry the ×0.67 realized-quality haircut and ~0.68 stage-2 retention
from §1; "expected" means the honest range, not a promise):

- **S1 — calendar hysteresis** (Dixit band / Schmitt trigger on CAL).
  *Mechanism:* the pre-work says the good hours are separated mostly by ≤2h
  dips; a θ_lo 2–4 deciles below θ_hi rides through dips whose cell values
  stay moderate, converting e.g. 369 P80-runs into O(150–200) longer streaks
  while holding dip hours whose in-sample mean is still positive (P40–P70
  band: +$0.11–0.37/h). It buys contiguity *without* smoothing the selector
  — the entry gate stays sharp; only the exit is patient. That asymmetry is
  what the E007 graveyard (smooth-but-wrong vs right-but-fragmented) never
  had. *Expected:* worked example at θ_hi=P80, θ_lo=P40, w4 — held ~28%,
  runs halved to ~180: stage-1 gross ≈ 618h × $0.28/h(realized) ≈ $173,
  minus 180×$0.77 = $139 switching ⇒ +$34 stage-1 ⇒ ~+$23 stage-2 over 92
  tune days ≈ **+$0.25/day**; if runs fall 3× instead of 2×, ~+$0.6/day.
  Straddles $0 and the target — which is what makes it a real experiment.
  *Falsified by:* dip hours' realized payoff enough below their in-sample
  mean that bridging costs more than the saved round trips (then hysteresis
  configs collapse onto θ_lo=θ_hi, reproducing K7's fragments).
- **S2 — blend hysteresis.** *Mechanism:* E007's C6 (state × calendar) was
  the least-negative candidate (−$0.074/day at w10) but at 0.7–1.1% held —
  starved, not wrong. Hysteresis on the same score opens the held fraction
  while the min() keeps both gates. *Expected:* −$0.1 to +$0.4/day; upside
  if the payoff-EWMA vetoes the calendar's bad weeks. *Falsified by:* the
  PAY_24 leg (AUC 0.54–0.56) adding churn instead of selection — visible as
  S2 tuning to q_lo=q_hi.
- **S3 — minimum dwell.** *Mechanism:* the bluntest contiguity purchase;
  it caps round trips at held/D directly. *Expected:* weakest of the six —
  the D−1 forced extension hours are calendar-arbitrary (all-hours tune mean
  is **negative**: −$0.19/h w4), so the dwell tax is real; M001 §2's
  foresight version already loses half the ceiling at 6h. −$0.4 to +$0.2/day.
  Kept because it is the cleanest single-knob falsifier of "contiguity per
  se suffices" — if S3 beats S1/S5, the calendar's *levels* were noise and
  only its *set membership* was real. *Falsified by:* dwell-extension hours'
  realized mean below ≈ −(saved switching)/(extension hours).
- **S4 — exit debounce.** *Mechanism:* duration-based version of S1 —
  bridges every gap shorter than M regardless of dip depth, pays for M
  trailing below-threshold hours per exit. *Expected:* between S1 and S3
  (−$0.2 to +$0.4/day): cheaper than S3 (extensions only at real exits) but
  blinder than S1 (bridges deep dips too). *Falsified by:* the same dip-
  quality failure as S1, plus M trailing-hour taxes at every genuine exit.
- **S5 — DP over the calendar forecast** (predict-then-optimize; the K4
  mechanism itself, foresight → forecast). *Mechanism:* the only candidate
  that chooses streaks *jointly* with switch costs — it bridges a dip iff
  the dip's forecast loss is smaller than a round trip, enters a block iff
  the whole block clears its costs. On a periodic forecast this yields a
  weekly in/out schedule — decided entirely by tune-window data, so it is
  causal by construction over any horizon. κ shrinks cell noise; c inflates
  planning costs against optimizer-of-noise bias (SPO's warning). *Expected:*
  the widest upside of the set: if realized block quality holds at ~0.67 of
  in-sample, +$0.2 to +$0.8/day; the M001 §2 constrained-oracle numbers
  (min-hold-6h ceiling +$3.13/day w4) bound the family from above at ~×0.5
  of the raw ceiling. *Falsified by:* full-window/August negative — meaning
  calendar levels do not survive out of window even after shrinkage, which
  would close the calendar-planning route entirely (the strongest single
  refutation available in the set).
- **S6 — receding-horizon DP** (Boyd-style MPC: calendar prior + state
  nowcast). *Mechanism:* S5's plan modulated by the current payoff residual
  — when the market runs hotter than the calendar expects, the forecast
  shifts down and the DP sits out even in calendar-good blocks; when
  quieter, marginal blocks activate. The horizon DP re-plans hourly but
  switch costs inside the plan damp flip-flops (the MPC literature's
  standard anti-churn property). *Expected:* S5 ± $0.2/day; the residual
  is C1-grade information (AUC 0.54–0.56) so the prior should dominate —
  S6 tests whether *any* state-awareness helps once contiguity is priced.
  *Falsified by:* underperforming S5 on the tune window (state term adds
  churn), or the same out-of-window failure as S5.

**Excluded, with reasons recorded:** Binance-side selectors (E007's C4 —
AUC 0.56–0.60, fragmented, and nothing in the streak machinery repairs a
selector's ranking; parameter budget); DVOL and funding dynamics (M001 §4,
unchanged); learned/many-parameter policies (G2 is blocked; SPO noted for
that era); grain-aligned decision clocks (M001 §2 measured them dominated by
min-hold at equal coarseness).

**Data needs:** all local — `e006/out/stage1_hours_w{4,10}.csv` for signals
and DP inputs, E003 parquets + funding CSV for stage-2 exact evaluation.
No new fetches.

**The falsification bar for the whole family** is E008's decision rule (next
file): SUPPORTED needs ≥ +$0.389/day central full-window *and* > $0 on
held-out August from some pre-named candidate; REFUTED if none beats $0
full-window (or all that do fail August). On REFUTED the operator
pre-commitment fires: the venue moves to the wstETH/WETH funding-carry path
(card [B2](../BACKLOG.md)) and **no further experiments run on ETH/USDC
0.05%** — this memo is the pool's last hypothesis set either way.
