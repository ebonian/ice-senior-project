# M005 — The LINK/WETH 0.30% mainnet ceiling and the two-leg hedge's funding: constraints, external research, ranked measurements

> Discovery memo for card [B5](../BACKLOG.md) (operator go 2026-09-03, part of
> the (iii) parallel decision — E011 runs while the bot repo builds T1
> margin alerting; **capital held until E011 reports**). Committed before
> `loop/experiments/E011-link-ceiling.md` pre-registers against it; append-only
> once cited. Written 2026-09-03 by the E011 cycle.

## 1 · Constraints, with their numbers

Pulled from [`CONSTRAINTS.md`](../CONSTRAINTS.md), not from memory:

- **K1 (BINDING, definitional)** — the target is a **rate**: 10–20%+ APR under
  honest costs at a **$10k reference** (= +$2.74–5.48/day), arbitrated by the
  frozen Gate-1 engine (`gate1-2026-08-29`, HPL envelope `e003-2026-08-29`).
- **K3 (BINDING)** — no USD-quoted major pays its gamma on any chain
  (f/g 0.50–0.97 everywhere, [E005](../../loop/experiments/E005-pool-screen.md) ·
  [E010](../../loop/experiments/E010-capital-rescreen.md)). The honest
  exceptions pay **funding carry ~5–6% APR** — below K1. E011's venue is the
  *other* exception: the one honest **fee edge**.
- **K14** — mainnet LINK/WETH 0.30% (`0xa6cc3c2531fdaa6ae1a3ca84c2855806728693e8`)
  is the program's only venue with honest f/g > 1.0 and real negative gamma:
  **f/g 1.337 / 1.208 / 1.099** at ±0.6% / ±1.8% / ±8.1% ($10k, central),
  implied shares 0.876% / 0.299% / 0.073%, top-10 swap fee concentration 1.7%,
  best static arm ±8.1% **+$0.915/day (+3.3% APR)**, worst month (Aug) f/g
  0.701 ([E010 §2](../../backtest_model_server/e010/REPORT.md)).
- **K4/K5 (INFORMATIVE, from the retired control venue)** — E006's ceiling
  substance was **contiguity** (median 3h streaks chosen jointly with switch
  costs); on Arbitrum the mean round-trip switch cost was ≈ $0.76 and the
  viable decision scale **1–6h**; daily-grain calls lost money *with perfect
  foresight* ([M001 §2](M001-short-horizon-vol-signals.md)).
- **K7/K11 (family lessons that condition E011's critique)** — selection
  without contiguity cannot be monetized (E007: 0/540 configs positive);
  streak-aware rules did not buy contiguity either (E008: 0/6 candidates
  positive). **A ceiling without a causal key is a museum piece** — E011
  prices the ceiling only and must say what an E012 would have to prove.
- **K9/K15 (measurement honesty)** — fee credit assumes full liquidity share
  of every in-range swap; E010 §3 showed an aggregate share gate can hide a
  wick-carried fee line. E011 must run the per-swap concentration check **on
  the oracle's held hours** (a timing oracle is a wick-seeking machine by
  construction — this check is not optional).
- **K6 gas (E010 §6)** — measured mainnet envelope: **$0.049 / $0.083 /
  $0.368 per tx** (opt/central/pess, coupled to the HPL envelope points);
  ~$0.33 per 4-tx recenter central. Real but non-deciding for static arms;
  *deciding* for switching-frequency questions (this memo §3).

## 2 · How E010's race hedged this pool (read from the engine, not guessed)

`e005/race.py run_arm` with `hedge_mode="per-leg"`
(`e010/out/candidates.json`: token0 LINK → `hl_coin: LINK`, token1 WETH →
`hl_coin: ETH`): the position's **LINK amount is shorted on HL LINK-PERP and
its WETH amount is shorted on HL ETH-PERP** — two short legs, re-targeted to
the position's amounts every hour (`rehedge_hours=1`), notional churn priced
at the HPL envelope. Leg marks are pool-implied USD (pool price × Binance
ETHUSDT mark). Funding is booked as `rate_h × q_leg × mark_leg` **per leg,
positive rate credits the short**. So "the hedge's funding" for this venue =
LINK-PERP short funding + ETH-PERP short funding on roughly the LP notional
split across both legs (~$7,148 total at $10k). There is no long leg and no
LINK/ETH cross-perp anywhere in the engine.

## 3 · Local pre-work (committed window data, 2026-05-01→08-28)

**Funding was a tailwind, and LINK's rate sits harder on HL's floor than
ETH's.** From the committed hourly CSVs
(`e005/data/funding/hl_funding_{link,eth}_hourly.csv`, 2,856 rows each):

| leg | mean ann. on notional | hours pinned at floor (1.25e-5/h) | hours negative | monthly ann. range |
|---|---:|---:|---:|---|
| LINK-PERP | **+10.64%** | **77.9%** | 6.5% | 8.8% (Jun) → 14.2% (Aug) |
| ETH-PERP | +7.21% | 57.6% | 13.6% | 3.3% (Jun) → 9.6% (Jul) |

In E010's race this books as **+$198–214 per arm over 119 days ≈
+$1.7–1.8/day** at always-in $10k leg notionals — two-thirds of the K1 floor
target, from funding alone. The E011 question is whether that is
representative (E009 found ETH's carry *compressing*: 2024H1 +$0.77/day →
2026H1 +$0.12/day at $1,015 notional, and HL's era holds no full bear
market). A LINK short's funding history has never been measured here.

**Switch costs are ~17× the old venue's, so the coarseness question inverts.**
Entering the $7,148 LP position from cash swaps *both* legs and opens *both*
shorts: onchain 5.155 bps × notional + 4 tx gas + HPL cost on the hedge open;
exit the mirror with 2 tx. Central at $10k ≈ **$12.7 per round trip** (vs
K5's $0.76 at $1,420 on Arbitrum) — 4.6 days of the 10%-APR target per
switch (E006: 2.0). Expect the DP to choose *fewer, longer* streaks than
E006's 3h median; the M001 §2 coarseness table must be re-measured here, not
assumed (its "1–6h viable" was priced at Arbitrum gas and $1,015 notionals).

## 4 · External research

**What was found (citations):**

- **Perp funding mechanics put a structural floor under short-side carry.**
  The funding formula's interest-rate baseline (0.01%/8h ≈ 11% ann.) plus
  clamping keeps funding at exactly the baseline for most hours on majors —
  BTC 78.2% and ETH 87.5% of an analysis period at exactly 0.01%/8h
  ([BitMEX 2025 Q3 derivatives report](https://www.bitmex.com/blog/2025q3-derivatives-report);
  mechanics: [Deribit Insights](https://insights.deribit.com/education/perpetual-swap-funding/),
  [Coinbase Institutional primer](https://www.coinbase.com/institutional/research-insights/research/market-intelligence/a-primer-on-perpetual-futures)).
  Our local LINK measurement (77.9% pinned) matches this floor-dominated
  regime. Altcoin funding skews positive in risk-on phases
  ([CoinDesk 2025-07-01](https://www.coindesk.com/markets/2025/07/01/xrp-trx-doge-lead-majors-with-positive-funding-rates-as-bitcoin-s-traditionally-weak-quarter-begins));
  aggregator commentary describes long negative stretches across majors in
  parts of 2026 — treated as unverified until our own fetch measures it.
- **The 0.30% fee tier is where LP flow is least toxic.** Markout studies of
  Uniswap v3 found ETH/USDC 0.05% LPs took large markout losses while 0.3%
  pool LPs were close to neutral
  ([Crocswap markout study](https://crocswap.medium.com/usage-of-markout-to-calculate-lp-profitability-in-uniswap-v3-e32773b1a88e),
  [follow-up](https://crocswap.medium.com/follow-up-analyses-of-lp-profitability-in-uniswap-v3-2cfc8c5e014e)) —
  directionally consistent with E010 finding its one honest f/g > 1 fee
  surface at a 0.30% tier, and with volatile pairs gravitating to it
  ([Keyrock LP study](https://keyrock.com/liquidity-providers-on-uniswap-v3-2/)).
- **JIT concentrates away from this pool's profile, but the caveat stands.**
  JIT attacks cluster on USDC–WETH pools (47% of attacks, 60% of revenue on
  the 0.3% USDC/WETH pool;
  [Imperial/IACR JIT study](https://eprint.iacr.org/2023/973.pdf)) and on
  large swaps; JIT requires ~269× the swap's volume in liquidity for ~0.007%
  ROI, so thin altcoin pools are less attractive targets
  ([Uniswap blog](https://blog.uniswap.org/jit-liquidity),
  [strategic analysis, arXiv 2509.16157](https://arxiv.org/pdf/2509.16157)).
  This *moderates* but does not retire K9 for LINK/WETH.
- **Data recipes exist for the fetch.** HL `fundingHistory` (hourly, paginated
  500) is the same endpoint E009 used for ETH
  ([Chainstack API reference](https://docs.chainstack.com/reference/hyperliquid-info-funding-history));
  Binance USDT-margined LINKUSDT 8h funding + daily klines mirror E009's
  descriptive proxy set.

**What was looked for and NOT found:**

- Any **public long-run LINK-specific funding statistics** (mean, regimes,
  negative-stretch lengths) — trackers show spot values only; the history
  must be fetched and measured (E011 does this).
- Any **2025–2026 post-fee-switch JIT/MEV measurement** on mainnet v3 — the
  literature stops at 2024 data (E010 §11 noted the same gap; it persists).
- Any **LP profitability study of an altcoin/ETH cross pair** specifically
  (LINK/ETH or comparable); the markout literature is USD-pair-centric.
- Any study of **fee seasonality / volume winters** on v3 pairs at monthly
  grain — E010's worst-month f/g 0.70 (Aug) has no external comparison point.

## 5 · Ranked pre-named measurements (E011 may test only these)

1. **C1 — the two-stage timing/width ceiling, per E010-raced arm.**
   *Mechanism:* E006 on the control showed hour-selection keeps ~69% of fees
   while shedding ~83% of gamma (held-hours f/g 0.73→2.96); here the surface
   *starts* at f/g 1.10–1.34, and the narrow arm's deficit is cost-driven
   (rehedge churn $11.9/day + gas $5.5/day central vs fees $44.8/day), which
   an in/out policy attacks directly. *Data:* E010's committed parquets
   (hash-verified) + committed funding/marks CSVs. *Expected effect:* bounded
   below by always-in (+$0.915/day best); if E006's fee-keep/gamma-shed
   fractions transferred naively to the ±0.6% arm the stage-1 surface would
   sit well above +$2.74/day — the honest uncertainty is switch-cost drag at
   $12.7/round-trip. *Falsified if* stage-1 UB < +$2.74/day central at every
   arm (no model, however good, reaches 10% APR here).
2. **C2 — the constrained-oracle coarseness table (M001 §2 transferred).**
   *Mechanism:* switch cost per target-day is 2.3× the old venue's, so the
   viable decision scale may shift coarser than 1–6h — which would *help* a
   realizable model (coarse = predictable); or the gamma may arrive in spikes
   that only fine timing dodges. *Data:* C1's stage-1 payoffs re-DP'd under
   min-hold {6,12,24}h and decision-every-{4,24}h, stage-2 re-simulated.
   *Falsified (of the "coarse is viable" reading) if* min-hold-24h retains
   < 50% of the unconstrained exact ceiling at every arm.
3. **C3 — LINK-PERP funding persistence and the two-leg net funding bound
   (E009's method transferred).** *Mechanism:* the package shorts LINK and
   ETH; if LINK's 77.9% floor-pin is structural, funding is a double
   tailwind; if it is a 2026-summer artifact, the window's +$1.7–1.8/day
   overstates the ceiling. *Data:* HL `fundingHistory` LINK full history
   (fetch recipe; E009 pattern; frozen end 2026-09-03T00:00Z); Binance
   LINKUSDT 8h funding + daily klines as descriptive proxy/regime split;
   E009's committed ETH long series reused for the ETH leg. *Expected
   effect:* long-window central two-leg expected funding on wide-arm
   notionals in the +$0.5–2.0/day band if representative; *the headwind
   bound:* substituting long-window central rates for window rates on the
   verdict arm's held leg-notional-hours must not move the stage-2 exact
   below +$2.74/day for SUPPORTED to stand. *Falsified if* the long-window
   central two-leg funding on always-in wide-arm notionals is ≤ $0/day
   (structural headwind — the fee edge must then clear K1 alone).
4. **C4 — descriptive signals transfer (non-deciding).** *Mechanism:* E006's
   findings (same-hour gamma AUC 0.90 vs trailing-signal AUC ≤ 0.53; rank
   persistence 0.62; calendar structure AUC 0.59–0.62) may or may not
   transfer to an altcoin pair with 77× fewer swaps (41k vs 3.4M). *Data:*
   C1's hourly payoff table + trailing RV/ER at 12/24/48h + dow×hod cells.
   *Output:* AUCs and persistence only — feeds a hypothetical E012, judges
   nothing.

Ranking rationale: C1 is the card's claim and the operator's decision input;
C2 prices whether a *realizable* (coarse) model could live here; C3 is the
venue-choice coupling (carry vs fee-edge — B2 stays HELD until E011 reports);
C4 is free context for whatever E012 becomes.

## 6 · What this memo changes

- Card B5 gains its memo; E011 pre-registers against §5's four pre-named
  measurements and may test nothing else.
- The B2/B5 coupling is explicit: **B2 is not resolved by this memo**; the
  three-way venue call (carry / fee-edge / both) is the operator's, made
  after E011's report with the LINK ceiling known.
- The JIT caveat inherits E010 §11's sharper form: every positive number is
  an upper bound (K9), and E011's REPORT must carry the per-swap
  fee-concentration check on held hours (K15) before any number is quoted.
