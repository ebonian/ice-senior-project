---
id: M003
for: E009 (new family H-carry — funding persistence)
date: 2026-09-03
status: final — feeds E009's pre-registration
---

# M003 — Is the wstETH package's funding carry a property of the market or of one window?

> Discovery-cycle memo per [`../PROTOCOL.md`](../PROTOCOL.md), for hypothesis
> card [B2](../BACKLOG.md). E008 closed H-timing and retired the ETH/USDC
> 0.05% venue (operator pre-commitment, bot ADR 0009); B2 — the wstETH/WETH
> 0.01% LP + HL ETH-short package — is ACTIVATED. Its measured edge is
> **93.8% funding carry** ($0.2095 of $0.2233/day), and that carry was
> measured over exactly one 119-day window. This memo researches funding-rate
> persistence externally and ranks the **pre-named persistence estimators**
> E009 will freeze. E009 is a measurement experiment, not a policy search:
> the candidates below are tests, not strategies.

## 1 · The constraints, with their numbers

Pulled from [`../CONSTRAINTS.md`](../CONSTRAINTS.md) and E005's committed
outputs, not from memory:

- **K1 (the bar).** Net **+$0.389–0.78/day on $1,420** (10–20% APR) under the
  frozen Gate-1 cost stack (`gate1-2026-08-29`, envelope `e003-2026-08-29`).
  B2 does not claim to clear K1 — it claims its measured **+$0.22–0.27/day**
  (5.7–7.0% APR) is *real and durable*; whether a sub-K1 rate is worth
  deploying is an operator call that needs the durability answer first.
- **K3 (why B2 is the survivor).** Every USD-quoted Arbitrum-V3 ×
  HL-hedgeable pool posts fees/gamma 0.63–0.97; the only positive packages
  are correlated pairs paying via **funding carry** ([E005](../../loop/experiments/E005-pool-screen.md)).
- **K8 (why persistence is the binding constraint).** The package shorts
  ~$1,015 ETH-PERP against ~$405 HL equity (≈2.5× leverage). A
  negative-funding stretch is not just forgone income — the short *pays*
  while remaining mandatory for delta cover: carry bleed plus margin
  pressure, with liquidation risk on rallies unmodelled. Bot-side
  margin/liquidation design pass is a separate B2 prerequisite.
- **The measured package, full precision** (E005
  `out/wsteth_weth_0p01/lag1h_rh1h/results.json`, arm_0.1pct, central,
  2026-05-01→08-28, 118.9967 days): net **$0.223333/day**, of which funding
  **$24.9321 total = $0.209519/day**; the non-funding residual (LP fees
  + hedged gamma − on-chain − HPL execution) is **+$0.013814/day**. Funding
  source: HL `fundingHistory` for ETH, committed at
  `e005/data/funding/hl_funding_eth_hourly.csv` (2,856 hourly rows,
  bit-for-bit equal to the bot repo's recorded series on overlap).

**Binding constraint picked:** B2's carry leg is one 119-day observation of a
market rate. Nothing is known about its stationarity; K8 converts downside
regimes into levered bleed. No other B2 prerequisite (perp cost calibration,
margin design) matters if the carry is a one-window artifact.

**Pre-work probes (disclosed; no long-window statistic was computed):**

- HL `fundingHistory` for ETH reaches back to **2023-05-12T00:00Z** and is
  current through fetch time — ~40 months of hourly data, paginated at 500
  rows/request. Coverage timestamps only were probed.
- Binance USDT-margined `fapi/v1/fundingRate` for ETHUSDT serves data from at
  least **2020-03-01** (2019-09 probe returned empty); 8-hour intervals.
- Gate calibration on *committed E005 data only*: recomputing the funding leg
  as flat `rate_h × $1,015` over the committed CSV gives **$0.20055/day** vs
  the replay's $0.209519/day = **−4.28%**. The gap is the replay's
  marked-notional bookkeeping (q0 in WETH reset at each of 10 re-mints,
  marked on Binance ETH hourly), which the flat model ignores. So a flat
  frozen-notional recompute is a valid reproduction only within ~±5%, and
  E009's validity gate is calibrated accordingly (and disclosed as such).
- In-window facts already published by E005's committed CSV: mean hourly rate
  8.23e-6 (7.2% APR on notional), 13.6% of hours negative.

## 2 · External research

### 2.1 What funding *is*, on Hyperliquid specifically

HL funding is **hourly**: `F = avg_premium + clamp(interest − premium,
−0.0005, +0.0005)` per hour, where the interest component is fixed at
**0.01% per 8h = 0.00125%/h (~11.6% APR paid toward shorts at neutral
premium)**, the premium is sampled every ~5s against the oracle price, and
funding is capped at 4%/hour
([Hyperliquid docs — Funding](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding);
[dwellir guide](https://www.dwellir.com/guides/hyperliquid-funding-rates)).
Two structural consequences:

1. **The pin.** Whenever the hourly premium lies inside
   `[interest − 0.0005, interest + 0.0005] = [−4.875e-4, +5.125e-4]`, the
   clamp forces `F = interest = 1.25e-5` exactly. E005's committed CSV shows
   this literally (first row: rate 0.0000125, premium −0.000395). A fully
   pinned market pays the short **$0.3045/day at $1,015 notional** — *more*
   than the whole measured funding leg. How much of the carry is this
   structural pin vs transient premium is measurable and decisive for
   persistence (pin carry has parameter risk — HL governance changing the
   interest constant — not market risk).
2. **The tail.** The 4%/h cap bounds a single hour's bleed at ~$40.6 at
   $1,015 — 10% of the $405 HL equity in one hour is the worst-case funding
   shock, before any price-move margin effect.

### 2.2 Funding-rate dynamics in the literature

- [He, Manela, Ross, von Wachter — *Fundamentals of Perpetual Futures* (arXiv 2212.06888)](https://arxiv.org/html/2212.06888v5):
  in frictionless equilibrium the funding anchor is an interest-rate
  differential; arbitrage keeps perp-spot basis (and hence funding)
  mean-reverting around it.
- [Zhang — *Funding Rate Mechanism in Perpetual Futures* (SSRN 6185958, 2026)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6185958):
  treats funding as an algorithmic feedback rule; a linear rule induces an
  **endogenous mean-reverting basis**; analyzes clamp-style piecewise rules
  (HL's is one) and stability under risk-constrained arbitrageurs.
- [Ackerer et al. — *Perpetual Futures Pricing* (Mathematical Finance, 2026)](https://onlinelibrary.wiley.com/doi/10.1111/mafi.70018):
  estimates funding dynamics as **Gaussian OU with jumps too strong to
  ignore** — mean reversion is real but the process is jump-punctuated, so
  short windows misstate both the mean and the tails.
- [*The Two-Tiered Structure of Cryptocurrency Funding Rate Markets* (2026)](https://www.researchgate.net/publication/399936354_The_Two-Tiered_Structure_of_Cryptocurrency_Funding_Rate_Markets):
  documents mean reversion, volatility clustering and cross-venue structure;
  funding is heteroskedastic (earliest systematic evidence: Nimmagadda &
  Sasanka 2019, BitMEX).

Net: the literature supports "funding mean-reverts around a small positive
anchor" — and equally supports "the mean of a 4-month window is not the
long-run mean," because of jumps and regime dependence.

### 2.3 The carry trade that sets the equilibrium level

The short-perp leg of B2 is exactly the crowded trade: long staked-ETH
collateral, short ETH-PERP.

- Equilibrium logic: capital enters the carry until funding compresses to
  financing cost + frictions + a risk premium
  ([Boros — cross-exchange funding arbitrage](https://medium.com/boros-fi/cross-exchange-funding-rate-arbitrage-a-fixed-yield-strategy-through-boros-c9e828b61215)).
- Scale of the crowd: Ethena's USDe — the same trade at protocol scale —
  reached **~$15B supply by Oct 2025**; its funding yield went **30%+ APY
  (2024 peak) → ~10% (mid-2025) → high single digits (Q2 2026)**
  ([eco.com — USDe 2026](https://eco.com/support/en/articles/15254002-ethena-usde-and-susde-2026-delta-neutral-yield);
  [Bankless — The Year Ethena Took Over](https://www.bankless.com/read/the-year-ethena-took-over)).
  Over 2026 Ethena rebuilt USDe's backing away from the basis trade
  ([altitudedp — Ethena stops farming the basis](https://medium.com/altitudedp/ethena-stops-farming-the-basis-d6f6edb79a5b))
  — consistent with carry compressed near its floor.
- Measured level and range: ETH funding averaged **~11% APY over the
  2023–2025 cycle with range −6% to +75%**
  ([IntoTheBlock — ETH leveraged staking](https://medium.com/intotheblock/eth-leveraged-staking-strategy-d51bc9a11c13)).
  E005's window at 7.2% APR sits *below* that cycle average and just below
  HL's 11.6%-APR interest anchor — i.e., the measured window is not
  obviously a lucky-high draw; it is a compressed-regime draw.

### 2.4 Downside regimes on record (what a bad stretch looks like)

- **Sep 2022 (Merge):** ETH funding hit **−1,200% annualized** (shorts
  paying) with ~−0.94%/day accumulating on FTX's ETH perp; the prior record
  was **−998% in the March 2020 crash**
  ([K33 Research](https://k33.com/research/archive/articles/eth-perps-seeing-massively-negative-funding-rates)).
  Event-driven hedging demand, reverted to neutral within weeks
  ([Glassnode week 38, 2022](https://insights.glassnode.com/the-week-onchain-week-38-2022/)).
  Predates HL's history; visible only through the Binance proxy.
- **Aug 2024:** a funding inversion compressed delta-neutral carry APY
  **19% → 4% in 11 days**
  ([Ethena docs — Funding Risk](https://docs.ethena.fi/solution-overview/risks/funding-risk)).
- **Oct 2025 (leverage cascade):** funding flipped negative, USDe depegged
  to $0.65 on one venue, and supply collapsed $14.8B → $7.6B in under a
  month as levered carry unwound
  ([eco.com — USDe 2026](https://eco.com/support/en/articles/15254002-ethena-usde-and-susde-2026-delta-neutral-yield)).
  **Inside HL's history and inside a trailing-12-month window** — the
  persistence test gets at least one genuine stress episode for free.
- 2026 has already printed negative-funding spells on ETH
  ([Blocklist, Mar 2026](https://blocklist.co.kr/2026/03/11/eth-funding-rate-turns-negative-are-bears-taking-over/amp/)).

Regime asymmetry worth naming: deeply negative funding episodes have been
**event-shaped spikes (days–weeks)**, while *positive* regimes have run for
quarters — but a structural bear market (2022-style, pre-HL) sustained
mildly negative funding for months, and HL's own history starts mid-2023 and
therefore contains **no full bear market**. That is the honest coverage
limit of any HL-only answer.

### 2.5 The LP leg (+$0.0138/day residual)

Little literature exists on correlated-pair AMM fee durability specifically.
What is known: wstETH/WETH volume is arbitrage/rebalancing flow, not retail;
wstETH on-chain liquidity is concentrated on Balancer (~89%) with Uniswap V3
~8% ([PrismaRisk wstETH assessment](https://hackmd.io/@PrismaRisk/wsteth));
low-fee tiers are the equilibrium venue for correlated pairs
([Lido guide](https://blog.lido.fi/providing-liquidity-on-uniswap/);
[Loesch et al., Uniswap v3 characterisation, arXiv 2301.13009](https://arxiv.org/pdf/2301.13009)).
E005 already measured the within-window monthly spread (fees $1.03–$3.06/mo
across four months). A longer fee-flow observation is possible only by
fetching more months of swap logs; E009 treats the LP leg as **descriptive,
non-deciding**.

### 2.6 Looked for and NOT found

- Any study of funding persistence **on Hyperliquid specifically** (its
  hourly clamp formula differs from Binance's 8h design; published funding
  statistics do not transfer 1:1).
- Any documented retention limit for HL `fundingHistory` (probed empirically
  instead: reaches market launch) or for Binance's funding archive (probed:
  ≥ 2020-03; 2019-09 empty).
- Any academic treatment of LSD/ETH pair LP fee durability.
- Any source quantifying how much of HL funding sits at the clamp pin —
  E009's test E measures it directly.

## 3 · Ranked candidates (E009's pre-named estimator set)

Six pre-named tests. All carry legs in **$/day at E005's frozen package**:
flat $1,015 short notional, `carry_$ = Σ rate_h × 1015` over the stated
window ÷ window days; package net = carry + the frozen non-funding residual
**+$0.0138/day** (E005, held constant — its own durability is test L,
descriptive). No cost-model reinterpretation.

| # | Test | Mechanism (why it measures persistence) | Data needs | What refutes persistence |
|---|---|---|---|---|
| A | **Trailing-12-month expected package net** (central estimator) — mean hourly HL ETH funding over the last 365 days × 24 × $1,015 + $0.0138 | The forward-looking regime: post-Ethena compression *and* the Oct-2025 stress are both inside; the most defensible unconditional forecast of next-quarter carry | HL `fundingHistory` ETH, trailing 365d | Package net < **+$0.10/day** central (vs B2's claimed $0.22–0.27) |
| B | **Full-history and per-regime means** — full HL coverage (2023-05→now), calendar-half means, and ETH-trend-conditional means (trailing-30d Binance ETH return sign) | Literature says funding is regime-dependent; if carry is positive only in bull halves, the B2 claim rests on a regime call the package cannot make | A's data + Binance ETH 1h marks | Bear/down-regime conditional package mean ≤ **−$0.20/day** while down-regimes are ≥ 25% of hours — carry then depends on regime luck |
| C | **Worst-stretch statistics** — rolling 30d and 90d package net minima over full HL history; longest run of consecutive negative-carry days | K8: sustained negative carry = levered bleed with margin pressure; the bound is what the $405-equity account must survive | A's data | Worst rolling-30d package net < **−$0.50/day**, or longest negative-carry run > **21 days** |
| D | **Mean-reversion structure** — AR(1) half-life of daily carry; run-length distribution of negative stretches (hour & day grain); negative-hour fraction by quarter | OU-with-jumps: short half-life + thin negative-run tail = self-healing carry; fat tail = regime risk the 119-day window never saw | A's data | ≥ 2 disjoint negative-carry runs ≥ **14 days** in the history, or trailing-12m negative-day fraction > **35%** |
| E | **Structural-pin decomposition** — fraction of hours with `rate == 1.25e-5` (clamp pin, tolerance 1e-9); carry attribution pin vs premium; premium distribution | The pin is an HL *parameter* (11.6% APR to shorts at neutral premium, $0.3045/day at our notional); pin-dominated carry persists unless governance changes a constant — market-premium-dominated carry is the fragile kind | A's data incl. `premium` field | Pinned-hour fraction < **20%** AND premium-driven carry share > 80% — carry then rides transient sentiment, not structure |
| F | **Cross-venue corroboration (descriptive, non-deciding)** — Binance ETHUSDT 8h funding 2020-03→now: correlation with HL on overlap; behavior in Mar-2020 / May-2021 / Sep-2022 episodes HL cannot see | Distinguishes venue-idiosyncratic from market-wide carry; extends the regime library into a full bear market | Binance `fapi/v1/fundingRate` | (context only — cannot refute alone; discordance with HL on overlap would downgrade HL-only conclusions to INCONCLUSIVE) |

Plus one non-deciding companion: **L — LP-leg durability sketch**: extend
the wstETH/WETH 0.01% swap observation earlier than 2026-05 if the public
RPC makes that feasible inside the run budget (E005's fetch machinery,
timeboxed); otherwise report the four committed monthly cells. Descriptive
either way.

Thresholds in A–D are chosen **before any long-window fetch** (the only
long-window numbers seen at memo time are coverage timestamps; §1 discloses
the probes). Ordering: A is the central estimator (the verdict's spine); C
carries the downside bounds; B/D/E explain *why* whatever A and C show; F/L
are context. E009 tests only this set.
