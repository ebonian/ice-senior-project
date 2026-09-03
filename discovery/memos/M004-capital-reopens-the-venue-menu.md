---
id: M004
for: E010 (H-pool, capital-parameterized — the venue re-screen)
date: 2026-09-03
status: final — feeds E010's pre-registration
---

# M004 — Does $10k reference capital reopen a venue where the strategy (and the model) can work?

> Discovery-cycle memo per [`../PROTOCOL.md`](../PROTOCOL.md), for hypothesis
> card [B4](../BACKLOG.md). The operator's 2026-09-03 amendment
> ([GOAL](../../loop/GOAL.md) north star) makes capital a test size, not a
> cap: deployable capital extends to $10,000+, the target is the **rate**
> (10–20% APR), and venue evaluation moves to a **$10k reference** with the
> scaling law reported. The venue menu was closed under a $1,420 assumption
> (K3); this memo researches what the amendment reopens — most importantly
> **Ethereum mainnet** — and hands E010 its pre-named screen list.

## 1 · The constraints, with their numbers

Pulled from [`CONSTRAINTS.md`](../CONSTRAINTS.md), not memory:

- **K1 (amended)** — target is 10–20%+ APR under honest costs at a $10k
  reference; the frozen cost stack (`gate1-2026-08-29`) is bps-proportional
  **except $0.0101/tx Arbitrum gas**, so per-dollar verdicts are
  size-invariant *on that chain*. Mainnet gas is not $0.0101/tx — the one
  genuinely capital-dependent term is chain-dependent too.
- **K3** — every USD-quoted Arbitrum V3 × HL-hedgeable pool posts
  **fees/gamma 0.63–0.97** ([E005](../../loop/experiments/E005-pool-screen.md));
  the near-misses cluster at 0.86–0.97 (WBTC/WETH 0.30% 0.966, PENDLE/WETH
  0.971, WETH/USDC 0.30% 0.865). Exceptions pay via **funding carry at ~5–7%
  APR**, below K1.
- **K11** — ETH/USDC 0.05% Arbitrum is retired (operator pre-commitment, bot
  ADR 0009); H-timing closed. The model thesis has **no venue** unless some
  pool posts an arm with f/g ≥ 1.0.
- **K12** — the B2 carry path nets **+$0.186/day central (4.8% APR)** and is
  compressing (2024H1 +$0.77 → 2026H1 +$0.12/day). The wstETH go/no-go is on
  hold pending this re-screen ([GOAL](../../loop/GOAL.md) Current focus).
- **K8** — hedge margin: ~2.5× leverage on the hedge equity at the C2 split;
  any carry venue needs the bot-side margin design pass before capital.
- **K9** — fee credit assumes our modeled liquidity earns its recorded-pool
  share of every in-range swap; adverse selection/MEV unmodelled — every
  positive number is an upper bound. §2.3 below: this caveat is **worse on
  mainnet**, not better.
- **Share gates re-bind at $10k on Arbitrum** — E005's honesty gate (d)
  (implied in-range share ≤ 1%) was evaluated at $1,015 LP notional. At the
  $10k reference (LP notional ≈ $7,148 at the same C2 split) every implied
  share multiplies by ≈ 7.04×: LINK/WETH's honest ±8.3% arm at 0.91% →
  ~6.4% (dead); wstETH/WETH ±0.1% at 0.28% → ~2.0% (LP leg loses gate (d),
  carry leg unaffected — it never depended on pool share).

**The binding constraint** is K3-at-$1,420: the venue menu was closed under a
capital assumption the operator has now removed. It is binding because every
downstream path (model retrain G2, carry B2, capital deployment) currently
routes through "no venue clears f/g ≥ 1.0 honestly"; it is researchable
because mainnet — excluded from E005 by a pre-registered scope limit, not a
finding — has different fee economics, different gas, and 10–100× deeper
pools, all measurable with the existing machinery.

## 2 · External research

### 2.1 The feeProtocol hypothesis meets the governance record

B4's named mechanism: Arbitrum pools surrender 25% of fees
(`slot0().feeProtocol = 0x44`, [E005 §5](../../backtest_model_server/e005/REPORT.md));
if mainnet v3 pools still ran the fee switch **off** (0x0), LP fee income
multiplies ×1.33, mapping E005's 0.86–0.97 near-misses to 0.87–1.29.

The governance record says the optimistic case is **probably dead**:

- **Dec 2025 — "UNIfication" executed on mainnet.** Uniswap governance
  approved the UNIfication proposal (on-chain vote concluding ~Dec 25,
  2025), activating protocol fees on v2 and on a subset of v3 pools
  comprising **80–95% of LP fees collected on Ethereum mainnet**, diverting
  **1/6 to 1/4 of LP fees** (by pool) into TokenJar contracts that fund UNI
  burns. Sources: [DLNews](https://www.dlnews.com/articles/defi/uniswap-dao-to-activate-fee-switch-and-burn-100m-uni-tokens/),
  [Cointelegraph](https://cointelegraph.com/news/uniswap-fee-switch-set-to-launch-before-2026),
  [Forklog](https://forklog.com/en/uniswap-to-activate-protocol-fees-and-burn-tokens/),
  [Talos State of the Network #346](https://www.talos.com/insights/state-of-the-network-346),
  [Agora proposal 93](https://vote.uniswapfoundation.org/proposals/93).
- **Feb 2026 — extension to all remaining v3 pools + 8 chains.** A follow-up
  proposal (Snapshot concluding **2026-02-23**) activates protocol fees on
  **all remaining mainnet v3 pools** and expands to Arbitrum, Base, OP
  Mainnet, Celo, Soneium, X Layer, Worldchain, Zora
  ([The Block, 2026-02-19](https://www.theblock.co/post/390456/uniswap-governance-considers-activating-protocol-fees-on-all-v3-pools-expanding-to-eight-additional-chains)).
  E005's own on-chain measurement corroborates execution reaching L2s before
  our window: Arbitrum pools read 0x44/0x66 throughout 2026-05→08, and the
  only SetFeeProtocol events in the window are no-ops (4→4, 6→6).

**Implication for E010** (stated before any mainnet read): the likely
mainnet reading is 0x44 on 0.01%/0.05% tiers and 0x66 on 0.30% —
**the same haircut Arbitrum already pays**, i.e. no ×1.33 anywhere. The
hypothesis stays testable per-pool: ground truth is ALWAYS the per-pool
`slot0().feeProtocol` read plus a full-window SetFeeProtocol event scan
(never the governance record, never this memo), and any pool reading 0x0 —
or flipping mid-window, which the Dec→Feb staged rollout makes possible for
thin pools — gets the multiplier (piecewise where a flip lands in-window).
What was **not** found: a public per-pool list of which v3 pools the Dec
2025 subset covered, or the exact execution transactions/dates of the Feb
2026 extension. The event scan supersedes both.

### 2.2 Mainnet gas regime 2026 — the analogue of the hedge envelope

The 2026 regime is historically cheap: L2 migration plus the gas-limit rise
to 60M leaves mainnet block utilization ~25–35%, pushing basefees to
records. Point readings: **~0.073 gwei** standard (Etherscan gas tracker,
2026-09-02); daily averages **~0.15–0.5 gwei** through April–May 2026;
mid-2026 daily averages ranged **0.16–9 gwei** — spikes remain real.
Sources: [Etherscan gas tracker](https://etherscan.io/gastracker),
[ethereum.org "Building on Ethereum in 2026"](https://ethereum.org/latest/building-on-ethereum-in-2026/),
[SQ Magazine Ethereum gas statistics 2026](https://sqmagazine.co.uk/ethereum-gas-fees-statistics/),
[Dwellir on eth_feeHistory](https://www.dwellir.com/blog/ethereum-gas-fees-explained).

**Pre-named envelope construction** (measured in-run, not assumed): sample
`baseFeePerGas` from the block headers already fetched as timestamp anchors
across the exact analysis window; convert to a 3-point **$/tx envelope**
using 250k blended gas/tx (Uniswap v3 mint ≈ 300–450k, burn+collect ≈
200–300k, swap ≈ 120–180k, against the frozen 3-tx-per-rebalance /
2-per-exit action model) and the window-mean ETH mark from the committed
Binance CSVs:

| Point | basefee | priority tip |
|---|---|---|
| optimistic | window p25 | 0.02 gwei |
| central | window p50 | 0.05 gwei |
| pessimistic | window p95 | 0.10 gwei |

Order-of-magnitude honesty at $10k: 0.25 gwei all-in × 250k gas × 4 tx ×
$4,500/ETH ≈ **$1.1 per rebalance ≈ 1.6 bps of a $7.1k LP position** —
amortizable at low recenter counts, ruinous for the 6-recenter/day narrow
arms (~$6.8/day). Gas does not close the venue; it prices out the narrowest
arms, and the pessimistic point must be quoted because the p95 tail (gwei
spikes) is 10–40× the p25.

Base (secondary scope): execution basefee ~0.005 gwei
([Basescan gas tracker](https://basescan.org/gastracker)) plus the
post-4844 L1 data fee; per-tx totals are cents — treated like Arbitrum's
(a fixed small $/tx measured the same way, plus a $0.005/tx L1-data adder,
recorded in-run).

### 2.3 Mainnet microstructure — the K9 caveat gets worse, quantified

- **JIT liquidity concentrates exactly where E010 screens.** Wan & Adams
  (Uniswap Labs, [SSRN 4382303](https://papers.ssrn.com/sol3/Delivery.cfm/SSRN_ID4382303_code5661794.pdf?abstractid=4382303&mirid=1),
  [blog](https://blog.uniswap.org/jit-liquidity)): JIT-executed volume never
  exceeded **0.5% of monthly volume** in their sample, but **over half of
  all JIT liquidity ever supplied targeted the mainnet USDC/WETH 0.05%
  pool** — the top of our screen list.
- **When JIT hits a swap, passive LPs lose ~85% of that swap's fee share.**
  Xiong, Ferreira Torres, Aung & Sathiamoorthy, "Demystifying JIT Liquidity
  Attacks" ([eprint 2023/973](https://eprint.iacr.org/2023/973.pdf)): 36,671
  attacks over 20 months, average **85% dilution** of passive LPs' share on
  targeted swaps, profits whale-concentrated (one bot: 92%), average
  attacker ROI 0.007% — a thin-margin, large-swap game. Adams et al. 2023
  measure ~0.6 bps price improvement per $1M order, i.e. JIT rides the
  biggest, fee-richest swaps.
- **Partial mitigation already in the data:** the engine credits fees
  against the pool's **recorded in-range liquidity at each swap**
  (the Swap event's `liquidity` field), which includes same-block JIT
  mints — so JIT dilution of *existing* fee flow is partly priced into the
  E005/E010 fee credit. What stays optimistic: our simulated liquidity is
  added on top of history (share gate ≤1% bounds this), and adverse
  selection (LVR-style toxic flow) is unmodelled entirely.
- **Not found:** any public measurement of JIT share or passive-LP fee
  capture for 2025–2026 (post-fee-switch), for wstETH/WETH mainnet, or for
  Base. Absence recorded; the mandatory REPORT caveat carries it.

Net for E010: mainnet positives are upper bounds with **more** slack than
Arbitrum positives at the same measured f/g — the verdict language must say
so, and the gate-(d) share cap is the only quantitative protection.

### 2.4 Candidate universe — mainnet × HL-hedgeable, plus Base

Per-leg hedgeability on Hyperliquid (perp existence verified in-run via the
HL meta API, as in E005): ETH, BTC, LINK, UNI perps are live; wstETH maps
to the pre-registered ETH-beta exception. USDT is treated as the USD par
stable (unhedged leg, mark ≡ 1.0), same convention as USDC; its depeg risk
is noted, not modelled. Addresses are never written in the registry —
`discover.py` resolves each pair × tier via the mainnet factory
(`getPool`), exactly as E005 did on Arbitrum.

Mainnet pools 10–100× deeper than Arbitrum twins ⇒ the $10k share gate that
kills Arbitrum's watchlist passes trivially on mainnet majors; that depth
is *the* structural reason capital reopens this menu.

### 2.5 Looked for and NOT found

- Per-pool Dec-2025 fee-switch subset list; exact Feb-2026 execution txs
  (superseded by our own event scan).
- 2025–2026 JIT/MEV shares post-fee-switch (§2.3).
- Any published always-in delta-hedged LP profitability study on 2026
  mainnet with honest cost accounting — nothing found; E010's screen appears
  to be the first such measurement we can cite for this window.

## 3 · Ranked candidates (E010's pre-named screen list)

Part C's venue set — ranked by mechanism strength; every row is raced at the
E005 width arms mapped to its tick spacing, both lenses (static-carry APR
and model headroom f/g ≥ 1.0), at $10k reference with the scaling law at
$1.4k/$10k/$50k. Probes that resolve NO-POOL or fail eligibility are
recorded, never silently dropped.

| # | Venue (chain, pair, tier) | Family analogue | Mechanism (why it could clear where Arbitrum didn't) | What refutes it |
|---|---|---|---|---|
| 1 | mainnet wstETH/WETH 0.01% | F3 twin | The one Arbitrum escape whose LP leg was real (+$0.014/day at $1.4k); mainnet is wstETH's primary venue — deeper, more flow per unit relative-vol; carry leg (K12) venue-independent | LP-leg f/g < 1 with the measured fee share; share gate still failing at $10k |
| 2 | mainnet WETH/USDC 0.05% | control twin | Deepest V3 pool anywhere; share at $10k ≈ 0.01–0.05% (honesty gate trivial); if mainnet flow/vol microstructure is materially richer than Arbitrum's, this is where it shows | f/g in the K3 band 0.63–0.97 — the venue property is chain-invariant, hypothesis dead for USD-quoted majors |
| 3 | mainnet WETH/USDC 0.30% | F1 | E005's F1 posted 0.865 — the closest USD near-miss family; if any residual fee-share advantage or richer retail flow exists on mainnet, ×1.15–1.33 on 0.865 crosses 1.0 | reads 0x66 AND f/g ≤ Arbitrum's 0.865 |
| 4 | mainnet WETH/USDT 0.05% | F4 flow | Mainnet's second ETH/stable venue; USDT-side retail + CEX-arb flow is the uninformed-flow mechanism F4 never truly tested on Arbitrum | f/g in the K3 band; or USDT-leg data quality fails coverage |
| 5 | mainnet WBTC/WETH 0.05% | F2 | Relative-variance mechanism at mainnet depth | f/g ≈ Arbitrum's 0.73 |
| 6 | mainnet LINK/WETH 0.30% | E005's F4 signal | LINK/WETH was the one genuine f/g > 1 with negative gamma at honest share ($1.4k); mainnet LINK liquidity sits at 0.30% with real depth — the $10k share death on Arbitrum is the exact thing mainnet depth fixes | share still > 1% at $10k, or f/g < 1 at every honest arm |
| 7 | mainnet WBTC/WETH 0.30% | F2b | Arbitrum's 0.966 was the closest USD miss of all; deeper mainnet book + any fee-share edge crosses 1.0 | reads 0x66 AND f/g ≤ 0.97; or T2-style burstiness DATA-FAILs again |
| 8 | mainnet UNI/WETH 0.30% | F4 | HL UNI perp live; mainnet UNI pool is the token's home venue; retail-flow mechanism | thin (median < 48 swaps/day scaled gate) or f/g in band |
| 9 | Base WETH/USDC 0.05% | B3 folded in | Busiest Base pool; cheap gas; retail order flow; the B3 card's claim, now in its proper scope | f/g in the K3 band — the venue property spans a third chain |
| P | probes: mainnet LINK/WETH 0.05%, wstETH/WETH 0.05% | — | resolved and recorded; raced only if they pass eligibility | NO-POOL / INELIGIBLE-thin rows |

**Data needs:** mainnet + Base swap logs over E005's exact UTC window
(2026-05-01 → 2026-08-28) via public RPC `eth_getLogs` (recipe committed,
reduced parquets ≤ ~3GB total); month block ranges derived per chain by
binary search and committed; timestamp anchors + `baseFeePerGas` from the
same headers; UNI funding + UNIUSDT marks fetched by the E005 recipe
(ETH/BTC/LINK funding and marks reuse E005's committed CSVs bit-for-bit).

**Expected effect against the constraint:** the honest expectation after
§2.1 is that the fee-share multiplier is **absent** (mainnet ≈ Arbitrum
haircuts), so clearing K3's 0.63–0.97 band requires mainnet flow/vol
microstructure to be genuinely richer — measurable, previously untested,
and worth one experiment; plus the two mechanical restatements (Parts A/B)
that the amendment makes obligatory regardless of the mainnet outcome.
**Falsifier for the whole card:** no venue × arm anywhere (mainnet included)
reaches f/g ≥ 1.0 honestly — B4 then dies, the model thesis stays
venue-less, and the operator conversation becomes B2-vs-stop.

E010 tests only this set.
