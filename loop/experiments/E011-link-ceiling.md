# E011 — A perfect-foresight timing/width policy on mainnet LINK/WETH 0.30% clears the 10–20% APR band with modelable margin

**Family:** H-timing (new venue — the program's first honest fee-edge surface).
**Card:** [B5](../../discovery/BACKLOG.md) · **Memo:** [M005](../../discovery/memos/M005-link-ceiling-and-two-leg-funding.md) (committed first; E011 tests only its §5 pre-named measurements C1–C4).
**Operator context:** E010 fork resolved (iii) 2026-09-03 — E011 runs in parallel with the bot repo's T1 build; **capital held until E011 reports**; the carry/fee-edge/both venue call is made with this ceiling known.

## Pre-registration (write BEFORE running)

**Hypothesis** — On mainnet LINK/WETH 0.30%
(`0xa6cc3c2531fdaa6ae1a3ca84c2855806728693e8`), an hour-level in/out timing
policy with **perfect foresight** (the oracle ceiling for any regime model)
earns enough after full frozen costs at the **$10k reference** that a
realizable model capturing a plausible fraction of the ceiling could reach
the 10–20% APR band (**+$2.7397–5.4795/day**, `0.10×10000/365` and double).
E010 §2 established the venue (f/g 1.099–1.337 at every raced width at
honest share, best static arm +$0.915/day central) and named this
measurement as the disambiguation. This is discovery card B5's claim.

**The one variable** — the in/out timing dimension, vs. the named baselines
`always_in` (E010's committed race rows, per arm) and `always_cash` ($0.00
exactly). Everything else frozen at E010's values:

- **Engine path unmodified**: `e005/race.py` (`PoolSpec`, `run_arm`,
  `always_cash`, `load_swaps`) + `gate1/engine/` by import, exactly as
  `e010/race10.py` loads them; cost model **`gate1-2026-08-29`**; HPL
  envelope **`e003-2026-08-29`** (total bps 1.984 / 3.359 / 8.320); fee
  credit capital-parameterized and share-aware (`L/(L_pool+L)` per swap).
- **Capital**: total $10,000 through E003's C2 split → LP notional
  $7,147.887… (`registry.lp_notional`); constant re-mint; lag1h_rh1h loop
  while held.
- **Window**: 2026-05-01 → 2026-08-28 (exclusive), E010's committed
  hash-verified parquets (41,194 swaps; sha256 re-verified against
  committed meta before any run — 4/4 OK 2026-09-03). No new swap fetches.
- **Gas**: E010's measured mainnet envelope
  (`e010/out/gas_envelope.json`: $0.049 / $0.08339 / $0.368 per tx),
  **coupled** — a number quoted at envelope point *g* uses gas point *g*
  with HPL point *g* (`CM.GAS_USD_PER_TX` patched exactly as race10.py
  does, restored after).
- **Hedge**: the engine's per-leg model as committed — the position's LINK
  amount shorted on HL LINK-PERP, its WETH amount shorted on HL ETH-PERP,
  hourly re-target, funding booked `rate_h × q_leg × mark_leg` per leg from
  the committed window CSVs (M005 §2 — no reinterpretation).
- **Arms**: every arm E010's grid carried for tick-spacing 60 — exactly
  three: `arm_0.1pct_0.2pct_0.5pct` (±0.60%, half 60), `arm_2pct` (±1.82%,
  half 180), `arm_8.3pct` (±8.11%, half 780).

**Method — E006's two stages, transferred (M005 §5 C1):**

1. **Stage 1, separable DP upper bound.** Per-hour payoff as if freshly
   centered at the hour's start: `fees_h + funding_h + gamma_pnl_h`, where
   fees use `fee_engine.accrue_fees` with lp_fee_share 5/6 and the $10k
   share-aware credit; funding books both legs; gamma is the two-leg hedged
   residual `[V(p1)u1 − V(p0)u0] + a0·(p0u0 − p1u1) + a1·(u0 − u1)` (the
   engine's own leg marks; reduces to E006's formula when u is constant).
   Switch costs charged in full: enter = 5.155 bps × both-leg notional +
   4 tx gas + HPL cost on the hedge open; exit = 5.155 bps + 2 tx gas + HPL
   close (M005 §3: ≈ $12.7 round-trip central). O(N) two-state DP per
   coupled envelope point. **This bounds every timing policy from above**
   (E006's argument transfers verbatim: free hourly re-centering,
   full-notional fee credit every held hour, no intra-streak costs).
2. **Stage 2, exact simulation.** The CENTRAL-point DP selection's streaks
   re-simulated exactly through `run_arm` on the swap slice — fresh mint at
   streak start (entry swap both legs + 4 tx + hedge open), lag1h_rh1h loop
   inside, burn + swap-back + 2 tx + hedge flatten at exit. Cash outside.
   $/day over the full 118.99-day window. Priced at all three coupled
   points: the central selection is the policy; opt/pess re-simulate the
   same streaks under their gas point and price at their HPL point.

**Blocking contracts (tests first, run refuses to proceed on failure):**

- **Baseline reproduction**: a single streak spanning the whole window
  through the stage-2 path must equal E010's committed
  `out/m_link_weth_0p30/lag1h_rh1h_cap10000_gas-{central,optimistic,pessimistic}/results.json`
  arms **float-consistently** (≤ 1e-9 relative or 1e-6 absolute on every
  Bucket field and per-day number). REFUSING discrepancy = abort, report.
- **always_cash ≡ $0.00** at every point.
- **Bound property**: stage-1 DP value ≥ stage-1 valuation of always-in and
  of always-cash, per arm per point; and ≥ every constrained DP variant run
  for the coarseness table.
- **Accounting identity** per simulated streak: `lp_value_abs_gap_usd`
  ≤ 1e-6.
- **Determinism**: byte-identical stage-1/stage-2 JSONs on re-run.
- **Funding-recompute cross-check**: the fresh LINK-PERP history fetch must
  reproduce E010's funding input on the overlap window (≥ 99.9% of the
  2,856 committed hours present, max |Δrate| ≤ 1e-12), E009 V1 pattern.

**Funding-persistence look (M005 §5 C3, E009's method transferred):**
HL `fundingHistory` for LINK, full available history, frozen end
2026-09-03T00:00Z, committed as recipe + reduced CSV; E009's committed
long ETH series reused for the ETH leg; Binance USDT-margined LINKUSDT 8h
funding + daily klines as the descriptive proxy/regime split. Report:
trailing-12m central expected rate; worst rolling-30d; longest
negative-carry run; negative-day fraction; floor-pin share; regime split by
Binance-kline trend; the **two-leg package** expected funding on the wide
arm's always-in leg notionals. Pre-named estimators only; no tuning.

**Decision rule** (coupled central decides; all three points reported):

- **REFUTED** — the stage-1 upper bound is < **+$2.7397/day central at
  every arm**: no timing/width model, however good, can plausibly reach
  10% APR here; the fee-edge venue cannot revive the model thesis at $10k.
- **SUPPORTED** — the stage-2 exact oracle nets ≥ **+$5.4795/day central at
  some arm** AND the funding look clears both pre-named bounds:
  (F1) the long-window central two-leg expected funding on the wide arm's
  always-in leg notionals is > **−$1.00/day** (not a structural headwind
  that swamps the carry the window booked at +$1.7–1.8/day); and
  (F2) the **funding-substitution adjustment** keeps the ceiling: on the
  qualifying arm, `stage2_central/day + Δ_fund ≥ +$2.7397/day`, where
  `Δ_fund = Σ_{h∈held(central)} [(r̄_LINK − r_LINK,h)·ntl0_h +
  (r̄_ETH − r_ETH,h)·ntl1_h] / days` over stage-1's held-hour leg
  notionals, r̄ = trailing-12m mean hourly rate (E009's central estimator).
- **INCONCLUSIVE** — anything else; state exactly what disambiguates.

**Report alongside (mandatory, non-deciding):** capture bar
(target ÷ stage-2 ceiling) per arm; held-fraction and streak-length
distribution; the constrained-oracle coarseness table (min-hold 6/12/24h,
decisions-every 4/24h — M001 §2 transferred; is the viable scale still 1–6h
under mainnet gas?); worst-month behavior (does the oracle dodge August's
f/g 0.701?); the descriptive signals section (same-hour AUC, trailing
signal AUCs, persistence, dow×hod calendar — E006's set, judging nothing);
the LINK-PERP persistence numbers with E009-style bounds; and the
**per-swap fee-concentration check on the oracle's held hours** (K15/E010
§3: top-10 swap share of held-hour fee weight `vol_usd/L_pool`; a
wick-carried ceiling must be named as such, not reported as structure).

**Inheritance stated up front (E007/E008, K7/K11):** this experiment prices
the **ceiling only**. No causal-signal claim is made or implied by any
verdict. E006's ceiling on the control survived two full falsification
campaigns without yielding a tradable rule; the Critique must state what an
E012 would have to prove — a causal selector with contiguity at THIS
venue's switch costs — before any capital chases this ceiling. Every
positive number restates K9: fee credit assumes full liquidity share;
adverse selection/JIT/MEV unmodelled; all positives are upper bounds; **no
capital moves on these numbers** (bot ADR 0008).

**Abort criteria** — baseline reproduction outside tolerance (report the
discrepancy, stop); LINK funding history unobtainable or > 2% of expected
hours missing in any 90-day span of claimed coverage; free disk < 2 GB at
any checkpoint; compute > 10× the estimate (stage 1 ≈ minutes on 41k
swaps; full run well under an hour). Artifacts under
`backtest_model_server/e011/` (`out/` JSONs checkpointed per arm; fetch
recipes + reduced CSVs committed).

## Result

*(pending)*

## Verdict

*(pending)*

## Critique

*(pending)*

## What this changes

*(pending)*
