# E011 — the LINK/WETH 0.30% timing/width ceiling: SUPPORTED. The ceiling clears the 20% band at ±0.6% — but its substance is regime-dodging, not hour-picking, and the margin is central-envelope-thin

**Verdict (pre-registered rule): SUPPORTED.** The REFUTED clause cannot fire
(stage-1 UB ≥ +$2.96/day central at every arm). The SUPPORTED clause fires at
**±0.6%**: stage-2 exact **+$5.785/day central** (≥ the +$5.4795/day = 20%
APR bar at $10k), with both pre-registered funding bounds passing — F1:
trailing-12m two-leg package **+$1.58/day** on wide-arm notionals (floor
−$1.00); F2: funding-substitution adjustment **−$0.14/day** → adjusted
ceiling **+$5.65/day**, far above the +$2.74/day floor. The mandatory
wick-honesty check is **clean**: held-hours top-10 swap weight 1.47% vs
1.73% full-window — the oracle is not wick-seeking; this is structure, not
dislocation income.

**What the SUPPORTED verdict is NOT:** a tradable rule (E007/E008
inheritance — a ceiling without a causal key is a museum piece), a
Gate-2-survivable number (K9: full-share fee credit, JIT/MEV unmodelled),
or an envelope-robust number (pessimistic point **−$13.51/day** at the
qualifying arm). No capital moves on these numbers (bot ADR 0008).

## 1 — Per-arm ceiling ($/day over 118.99 days, coupled envelope points)

| arm | width | always-in (E010, central) | stage-1 UB opt/cen/pess | stage-2 exact opt/cen/pess | held % | streaks (med len) | capture bar 10% / 20% |
|---|---|---:|---|---|---:|---|---|
| arm_0.1pct_0.2pct_0.5pct | ±0.60% | −4.456 | +20.79 / **+20.50** / +19.53 | +10.74 / **+5.78** / −13.51 | 96.7% | 14 (93h) | 47% / 95% |
| arm_2pct | ±1.82% | −0.874 | +9.03 / **+8.87** / +8.34 | +5.51 / **+3.64** / −3.42 | 97.9% | 8 (86h) | 75% / 151% |
| arm_8.3pct | ±8.11% | +0.915 | +3.05 / **+2.96** / +2.77 | +2.50 / **+2.02** / +0.19 | 98.8% | 5 (86h) | 136% / — |

Verdict-arm decomposition (central, whole window): fees +$4,748, hedged
gamma −$2,256 (**held-hours f/g 2.10** vs 1.34 always-in), funding +$184,
on-chain −$635 (229 recenters), hedge execution −$1,353 → **+$688 net**.
Width ordering inverts E010's static race (narrow wins under foresight), as
it did on the control (E006).

**Monthly nets, verdict arm: +$85.0 (May), +$267.2 (Jun), +$284.2 (Jul),
+$52.0 (Aug).** The oracle dodges the f/g-0.701 August winter — always-in
lost −$34.9/day there; the oracle's August is positive. Every month
positive is exactly what "the timing model has real winter to dodge" (B5)
predicted.

## 2 — What the ceiling actually is (read before modeling it)

The oracle holds **96.7–98.8%** of hours in **5–14 streaks of median
~90h** — this is *always-in minus roughly a dozen bad multi-day stretches*,
not E006's 3h-median hour-picking. The stage-1 → stage-2 retention (28% at
±0.6%) is dominated by intra-streak rehedge churn and recenter gas that the
bound never charges, i.e. the bound's looseness lives exactly where
always-in's costs live. Mainnet's ~$12.7 round-trip switch cost (M005 §3)
forces this coarseness — and the coarseness table shows it costs little:

| constraint (central) | ±0.60% | ±1.82% | ±8.11% |
|---|---:|---:|---:|
| unconstrained | **+5.78** | +3.64 | +2.02 |
| min-hold 6h | +5.66 | +3.64 | +2.02 |
| min-hold 12h | +5.66 | +3.64 | +2.02 |
| min-hold 24h | +4.94 | +3.34 | +1.98 |
| decisions every 4h | +5.29 | +3.20 | +1.98 |
| decisions every 24h | **+4.50** | +3.12 | +1.51 |

**M001 §2's answer inverts on this venue.** On the control, a daily-grain
oracle *lost money*; here it retains **78%** of the unconstrained exact
ceiling (+$4.50/day — still above the 10% bar with a 61% capture margin).
The viable decision scale is not 1–6h; it is *anything up to daily*. A
realizable model needs coarse, persistent regime calls, not hour-scale
prediction — structurally the easiest modeling target this program has
measured.

## 3 — The two-leg funding look (E009's method on LINK-PERP)

The hedge is two shorts (LINK-PERP for the LP's LINK leg, ETH-PERP for its
WETH leg; positive funding credits both — M005 §2). Full HL history
(2023-05-18 → 2026-09-02, 28,451 hourly rows, fetch frozen at
2026-09-03T00:00Z; overlap with E010's committed window input exact to 0):

- **LINK leg:** full-history **+15.79%** ann on notional; trailing-12m
  **+10.12%**; floor-pinned 59.7% of hours; negative only 12.4%.
  Halves: 2023H1 −48.1% (thin early listing), 2023H2 +17.7, 2024H1 +34.8,
  2024H2 +19.9, 2025H1 +9.7, 2025H2 +14.0, 2026H1 +9.0, 2026H2 +11.7 —
  compressing like ETH's (K12) but toward a higher floor-pinned base.
- **ETH leg:** full +14.48%, trailing-12m +6.21% (E009's series, reused).
- **Package** (fixed notionals $3,435 + $3,713 = the wide arm's stage-1
  time-averages): full **+$2.93/day**, trailing-12m **+$1.58/day**; worst
  rolling 30d **−$1.97/day** (2023-08-16, early-listing episode); longest
  negative run **21 days**; negative days 5.2% trailing-12m; down-regime
  mean still **+$1.58/day** (funding stayed a tailwind in down-trends);
  HL-vs-Binance 8h sign agreement 79.0%.
- **F1 PASS** (+$1.58 > −$1.00). **F2 PASS** on the qualifying arm: window
  rates → trailing-12m rates on the held-hour leg notionals moves the
  ceiling by only −$0.139/day (the window's funding was *not* an outlier).

Coverage caveat (E009's, inherited): HL's era contains no full bear
market; the 2023H1 −48% half shows what a thin/bear LINK perp regime does,
and the K8 margin design must budget for funding reversals of at least the
−$1.97/day worst-30d scale.

## 4 — Wick honesty on the held hours (K15, mandatory)

Ranking held-hour swaps by `vol_usd / pool_liquidity`: top-10 carry
**1.47% / 1.39% / 1.36%** of total weight at ±0.6% / ±1.8% / ±8.1% —
*below* the full-window 1.73% (the oracle avoids dislocation hours rather
than seeking them; contrast wstETH's 99.97%, E010 §3). Top-10 fee *hours*
carry 5.4–6.9% of held fees. The fee line is broad-based; no wick-carried
ceiling.

## 5 — Descriptive signals (NOT the verdict; E012's raw material)

- **Same-hour (foresight) AUCs, verdict arm:** payoff 0.73, gamma 0.88,
  intra-hour RV 0.11 (held hours are the *quiet* ones — flipped, RV
  separates at 0.89). E006's structure transfers.
- **Trailing (causal) signals separate here — inverted:** every trailing
  vol/ER signal has AUC *below* 0.5 for held (high trailing vol ⇒ skip):
  prev-hour RV **0.15** (⇒ 0.85 as a skip signal), RV-12h 0.28, RV-24h
  0.35, RV-48h 0.44, ER 0.30–0.34. On the control these were useless
  (0.45–0.53, K6); here the oracle's 90h streaks live at exactly the
  timescale trailing vol persists at (the skip episodes are multi-day vol
  regimes).
- **Calendar (dow×hod):** in-sample 0.63, August out-of-sample 0.56 — weak;
  the calendar is not the key here, vol level is.
- Read with E007/E008's discipline: these are selection numbers without
  costs, contiguity, or held-out validation. They *suggest* E012's
  candidate family (a trailing-vol gate / hysteresis at 4–24h grain, M002's
  S1/S2 shapes on a vol selector); they prove nothing.

## 6 — Validation

59 blocking contracts, all PASS
([`tests/test_e011_contracts.py`](tests/test_e011_contracts.py)):
E010 race-row reproduction float-consistent (≤ 1e-9 rel) at all 3 coupled
gas points × 3 arms (worst gap 6.0e-12); always-cash ≡ $0; LINK funding
recompute exact on 2,856/2,856 overlap hours (max |Δ| = 0); DP dominates
always-in/always-cash at every arm × point and every constrained variant;
per-streak accounting identity ≤ 1e-6 (worst 3.5e-12); stage-1 wide-arm
recompute byte-identical to checkpoint.

## 7 — Reproducing

| Path | Purpose |
|---|---|
| [`common11.py`](common11.py) | E010 engine path by import; streak slicer; gas coupling |
| [`fetch11.py`](fetch11.py) | LINK funding recipes (HL hourly, Binance 8h + 1d), frozen end 2026-09-03T00:00Z |
| [`oracle11.py`](oracle11.py) | Stage 1: two-leg hourly payoffs, coupled switch costs, DP |
| [`exact11.py`](exact11.py) | Stage 2: exact streak re-simulation via e005 `run_arm` |
| [`coarse11.py`](coarse11.py) | M001 §2 constrained-oracle table (e007 DPs by import) |
| [`funding11.py`](funding11.py) | E009 estimators on LINK + two-leg F1/F2 |
| [`wick11.py`](wick11.py) | K15 held-hours per-swap concentration |
| [`signals11.py`](signals11.py) | E006 descriptive set (e006/signals.py by import) |
| [`tables11.py`](tables11.py) | Decision rule as a program; these tables |

Runbook: `fetch11.py` → `tests/` → `oracle11.py` → `exact11.py` →
`coarse11.py` → `funding11.py` → `wick11.py` → `signals11.py` →
`tables11.py` → `tests/` (all-PASS). Swap data: E010's committed parquets,
hash-verified (4/4). Deterministic, no RNG. Reused by import: e005 engine
(via race10), e006 DP/signals, e007 constrained DPs, e009 estimators.
Written new: the two-leg payoff table, coupled switch costs, F1/F2, wick
held-set check.

## 8 — What this does not answer

- **JIT / adverse selection (K9) — mandatory, unresolved, and priced by
  nothing here.** Every number credits our L its full recorded-pool
  share of every in-range swap. No 2025–26 JIT measurement exists publicly
  (M005 §4 looked); LINK/WETH's profile (altcoin pair, thin JIT economics)
  moderates but does not retire the caveat. The wick check (§4) rules out
  dislocation-carried fees; it cannot rule out share dilution on ordinary
  large swaps.
- **Whether any causal rule captures 47% of this ceiling.** E006's control
  ceiling had a 6.4% capture bar and still died twice (E007, E008). This
  bar is 7× higher — but §2/§5 show the target is coarse vol-regime
  dodging, a different (and easier-looking) shape than the control's. That
  is E012's question, and it must clear M005 §5's falsification framing
  before any capital chases this ceiling.
- **Perp cost calibration for LINK** — the HPL envelope's slippage points
  are ETH-calibrated (E005/E010 caveat, unchanged); LINK books are
  thinner, so the pessimistic point may still be optimistic for the LINK
  leg.
- **One market, 119 days.** All four months positive is necessary, not
  sufficient; the window contains no LINK-specific crash, no bear market,
  and one August vol episode that the oracle dodges. The funding look's
  2023H1 (−48% ann) shows the tail this window lacks.
- **Whether the operator's three-way venue call (carry / fee-edge / both)
  changes** — that decision is the operator's, made per PROTOCOL §7 with
  this report in hand; nothing here deploys anything.
