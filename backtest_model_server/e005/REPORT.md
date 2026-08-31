# E005 — the pool screen: INCONCLUSIVE. Two venues carry positively; none clears the pre-registered bar

**Verdict (pre-registered rule): INCONCLUSIVE.** No eligible pool × arm passes
all five SUPPORTED gates. REFUTED is excluded because eligible pools do clear
fees/gamma ≥ 1.0 over the full window — something no ETH/USDC width managed in
E003. The named watchlist:

- **wstETH/WETH 0.01%** (`0x35218a1c…`), ±0.1% arm — fees/gamma 36.2 full
  window, > 1.0 in every month, implied pool share 0.28%, volume persistence
  0.63 — **fails only gate (c)**: net +$0.223/day central vs the +$0.389/day
  target (≈ 5.7% APR on $1,420 vs the 10% north star). Its best arm nets
  +$0.271/day (±0.5%; 7.0% APR).
- **LINK/WETH 0.05%** (`0x91308bc9…`), ±8.3% arm — fees/gamma 1.204 full
  window (the only pool > 1.0 with genuinely negative hedged gamma), implied
  share 0.91%, net +$0.174/day central (4.5% APR) — fails (a) 1.5×, (b)
  August 0.624, and (c). Its narrower arms post f/g 1.12–1.27 but assume
  3.3–25% of the pool's in-range fee flow — gate (d) correctly rejects them.

Every USD-quoted candidate behaves like E003's control: fees/gamma 0.63–0.97
across F1 (higher tier), F2 (BTC/ETH pair), and F4 (retail flow), whatever
the width. The two escapes are the pre-registered F3 mechanism (near-zero
relative variance) and the correlated LINK/ETH pair at wide width — and both
lean on **perp funding carry**, not LP fees, for their positive net.

Artifacts: [`out/decision.json`](out/decision.json),
[`out/tables.md`](out/tables.md), per-pool `out/<slug>/lag1h_rh1h/`.

---

## 1 — The screen

$/day, full window 2026-05-01 → 2026-08-28 UTC (119 days), lag1h_rh1h primary
loop, $1,015 constant re-mint LP notional, central envelope. `f/g` =
LP fees ÷ |hedged gamma| (E003 §2 definition, frozen). Full table with all
arms, envelope points, and monthly cells: [`out/tables.md`](out/tables.md).
Best arm per pool:

| Pool | Family | Eligible | Best arm | f/g full | worst-month f/g | net central $/day | implied share |
|---|---|---|---|---:|---:|---:|---:|
| ETH/USDC 0.05% (control) | — | yes | ±0.1% | 0.750 | 0.685 | −16.481 | 0.70% |
| WETH/USDC 0.30% | F1 | yes | ±1.8% | 0.865 | 0.787 | −2.115 | 0.29% |
| wstETH/WETH 0.01% | F3 | yes | ±0.1% | **36.184** | **1.092** | **+0.223** | 0.28% |
| weETH/WETH 0.01% | F3 alt | **no — thin** | (±0.2%) | 0.628 | 0.198 | +0.148 | 16.8% |
| WBTC/WETH 0.05% | F2 | yes | ±0.1% | 0.731 | 0.690 | −11.117 | 0.29% |
| WBTC/WETH 0.30% | F2 | **DATA-FAIL (T2)** | ±1.8% | 0.966 | 0.716 | −0.408 | 1.18% |
| ARB/WETH 0.05% | F4 | yes | ±2.0% | 0.689 | 0.526 | −5.080 | 0.44% |
| ARB/WETH 0.30% | F4 | yes | ±8.1% | 0.743 | 0.452 | −0.996 | 4.76% |
| PENDLE/WETH 0.05% | F4 disc. | yes | ±8.3% | 0.971 | 0.522 | −0.660 | 7.87% |
| LINK/WETH 0.05% | F4 disc. | yes | ±2.0%* | 1.274* | 0.624 | −0.043* | 3.31%* |

\* LINK's ±2.0% arm has the best ratio but a 3.3% implied share; its honest
arm is ±8.3% (share 0.91%): f/g 1.204, net +$0.174/day.

**Decision-rule evaluation** ([`out/decision.json`](out/decision.json), the
rule as a program in [`tables.py`](tables.py)):

- **SUPPORTED**: no pool × arm passes (a)–(e). Nothing is close on all five:
  the single 4-of-5 row is wstETH ±0.1%, short only the profit floor (c).
- **REFUTED**: excluded — max eligible full-window f/g is 36.2 (wstETH), and
  LINK holds 1.12–1.27 across four arms.
- **INCONCLUSIVE watchlist** (named, with failed gates): wstETH/WETH 0.01%
  ±0.1% [c], ±0.2% [b, c], ±0.5% [b, c], ±2% [a, b, c]; LINK/WETH 0.05%
  ±8.3% [a, b, c], ±2% [a, b, c, d], ±0.5% [a, b, c, d], ±0.2% [a, b, c, d].

## 2 — What the two watchlist pools actually earn

Per-day decomposition, central envelope, primary loop:

| Line | wstETH ±0.1% | LINK ±8.3% |
|---|---:|---:|
| LP fees | +0.057 | +0.919 |
| hedged gamma | +0.002 | −0.763 |
| on-chain | −0.036 | −0.020 |
| HPL execution (central) | −0.009 | −0.228 |
| funding | **+0.210** | **+0.268** |
| **net central** | **+0.223** | **+0.174** |

Both are, at current funding, **funding-carry trades with an LP position
attached**. wstETH's LP leg nets +$0.014/day without funding; LINK's LP leg
without funding is −$0.09/day. The funding line is real (recorded HL rates on
the short's notional — wstETH runs a full-notional ~$1,015 static ETH short,
LINK shorts both legs ≈ full notional across ETH + LINK perps), but it is the
one line that is a market rate, not a structural property of the venue. A
funding regime change flips both pools' sign; neither clears the target even
with it.

Two metric caveats, stated rather than hidden:

- **wstETH's f/g is degenerate in the numerator's favor.** Its "hedged gamma"
  is *positive* (+$0.19 over 119 days): the wstETH/WETH ratio accretes
  (staking yield) faster than it oscillates, and the pre-registered static
  ETH-beta short leaves that accretion in. fees ÷ |tiny positive number| is
  huge. The load-bearing fact is not 36.2 — it is that **every month at every
  arm nets positive** through the full frozen cost stack, on ~10 recenters
  per 119 days.
- **Gate (c) does not fall to capital scaling.** Fees, gamma, funding and
  costs all scale ≈ linearly with notional at these pool shares, so net APR
  is nearly size-invariant: wstETH's +$0.223/day is 5.7% APR at any nearby
  size, against a 10% target. The shortfall is a rate, not a size.

## 3 — Why the other families closed

- **F1 (fee tier)**: 6× gross fee per unit volume moved f/g from 0.74 to
  0.86 — the extra fee income comes with proportionally more gamma per
  recenter (coarser tick spacing forces ±0.60% as the narrowest arm). Only
  July cleared 1.0 monthly.
- **F2 (BTC/ETH relative variance)**: WBTC/WETH 0.05% sits at 0.66–0.73,
  indistinguishable from the control. The 0.30% tier reaches 0.94–0.97 —
  the closest USD-negative miss in the screen — but its own months break
  below 1.0 and the pool's burst structure tripped the T2 gate (§6).
- **F4 (retail flow)**: ARB/WETH 0.66–0.74. PENDLE/WETH is the anti-case:
  a trending pool where narrow always-in arms bleed −$34 to −$67/day
  (f/g 0.11–0.39) — uninformed flow does not pay for trend gamma — and its
  August volume fell to 24% of May's, firing the pre-registered
  incentive-cliff guard (e). LINK/WETH is the one real F4 signal: a
  correlated major pair whose relative variance is low against its fee flow.

## 4 — Engine-extension validity gate (control reproduction)

The generalized simulator ([`race.py`](race.py)) re-ran E003's control on
E003's own parquets and funding CSV. Required: ±0.05 on fees/gamma, ±5% on
net $/day. Measured, lag1h_rh1h:

| E003 arm | E005 arm | f/g e003 | f/g e005 | Δ | net central e003 | e005 | Δ |
|---|---|---:|---:|---:|---:|---:|---:|
| W10 | ±0.5% | 0.74007 | 0.74007 | 0.00000 | −9.25256 | −9.25256 | 0.00% |
| W40 | ±2.0% | 0.72952 | 0.72952 | 0.00000 | −3.16442 | −3.16442 | 0.00% |
| W160 | ±8.3% | 0.70603 | 0.70603 | 0.00000 | −0.84352 | −0.84352 | 0.00% |

Identical recenter counts (715/119/11) and all three envelope points at 0.00%
relative error — for USD-quoted pools the generalized path reduces
arithmetically to E003's (marks ≡ 1.0). Contract tests pin this plus the
frozen constants, width mapping, per-arm accounting identity (decomposed vs
tracked ledger ≤ 1e-6 on every published run), input completeness, and the
keccak-derived selectors: [`tests/test_e005_contracts.py`](tests/test_e005_contracts.py) — 38/38 pass.

## 5 — Eligibility and screened-out candidates

No silent drops. Full rows in [`out/candidates.json`](out/candidates.json)
and [`out/tables.md`](out/tables.md):

| Candidate | Outcome |
|---|---|
| 8 pre-registered pools | all exist on the factory, all HL perps live, all RESOLVED |
| weETH/WETH 0.01% | **INELIGIBLE-thin** — median 43 swaps/day < 48 (raced for context before the gate computed; excluded from the verdict) |
| WBTC/WETH 0.30% | **DATA-FAIL** under the generalized T2 (empty-hour runs to 49 h) while T1 tiling and T3 refetch pass exactly — burst structure, not truncation (§6); verdict-neutral either way (f/g < 1.0) |
| F4 discovery | 7-token HL-perp shortlist × {WETH, USDC} × {0.05%, 0.30%}: 28 combinations probed, 26 rows recorded NO-POOL / SAMPLED-NOT-CHOSEN; **PENDLE/WETH 0.05%** (~2,933 swaps/day) and **LINK/WETH 0.05%** (~1,078/day) chosen |
| Protocol fee (issue W) | 0.05%/0.01% pools run feeProtocol 0x44 → LPs keep 3/4; **0.30% pools run 0x66 → LPs keep 5/6**; the window's only SetFeeProtocol events are no-ops (4→4, 6→6), so every pool's share is constant piecewise-trivially |

## 6 — What was replayed, what was modelled, deviations from pre-registration

Replayed: every swap via `eth_getLogs` over E003's exact month block ranges;
hourly HL funding per perp (committed CSVs, `data/funding/`; the HL ETH
series equals the bot repo's recorded CSV bit-for-bit); Binance 1h USD marks
(`data/marks/`). Modelled: on-chain cost and the three-point hedge envelope,
both frozen (`gate1-2026-08-29`, `e003-2026-08-29`). Unknown, as in E003:
maker fill reality per venue — and the envelope's slippage points were
calibrated on ETH-perp fills; LINK/PENDLE/ARB perp books are thinner, so
their pessimistic points are optimistic bounds.

Deviations, all validity-preserving and none decided after seeing a number
they could move:

1. **F4 discovery narrowed** from "top V3 pools by swap count" (unscannable
   on the public RPC) to the shortlist above, sampled over 10 spread days.
2. **T2 generalized** (pre-registration left per-pool generalization open):
   zero-swap days = 0 AND max contiguous empty-hour run ≤ 24 h. It marked
   WBTC/WETH 0.30% DATA-FAIL where T1/T3 prove the fetch complete — recorded
   as implemented rather than re-judged post hoc; the pool's numbers appear
   for context and cannot change the verdict.
3. **weETH raced though INELIGIBLE-thin** (ordering slip; excluded from the
   verdict as pre-registered).
4. **USD conversion at 1 h resolution** (Binance open-at-hour); perp marks
   are pool-implied (pool price × quote mark) — WBTC/BTC and stETH basis
   ignored, consistent with the frozen hedge-ratio idealization.
5. **On-chain swap cost frozen at 5.155 bps** of swapped notional for every
   venue (Arbitrum-calibrated constant; conservative for the 0.01% pools).
6. **±8.3% maps to ±797 ticks on spacing-1 pools** (8.296%) vs ±800
   (8.328%) on spacing 10; exact widths recorded per arm. On spacing 60 the
   three narrow arms merge into ±0.60%.
7. **Constant-notional only** (compound mode was E003's secondary reading;
   the pre-registration froze constant re-mint).

## 7 — Sensitivity: recenter-only rehedge (lag1h_rh0h)

Direction unchanged everywhere; levels move with rehedge cost. LINK ±0.5%
turns +$1.23/day and PENDLE ±8.3% +$0.83/day under rh0h — but rh0h is the
sensitivity, not the primary loop, and those arms fail gates (d)/(e)
respectively regardless. wstETH is rehedge-invariant (static short). Full
runs: `out/<slug>/lag1h_rh0h/`.

## 8 — Reproducing

| Path | Purpose |
|---|---|
| [`pools.py`](pools.py) | Candidate registry, frozen window/blocks, width-arm mapping |
| [`keccak.py`](keccak.py) | Self-tested keccak256 → selectors/topics (no guessed constants) |
| [`discover.py`](discover.py) | Factory resolution, feeProtocol (+events), HL universe, F4 sampling |
| [`fetch_pool_months.py`](fetch_pool_months.py) | Per-pool month fetch; E003 block ranges + anchors reused |
| [`funding.py`](funding.py) | HL funding + Binance marks → committed CSVs |
| [`coverage.py`](coverage.py) | T1/T2/T3/T5 per pool + eligibility stats → `out/coverage.json` |
| [`race.py`](race.py) | The generalized mode-C simulator |
| [`tables.py`](tables.py) | Every table above + the decision rule as a program |
| [`tests/`](tests/) | 38 contract tests incl. the control-reproduction gate |
| `data/swaps/<slug>/` | Parquets gitignored; blocks.json + meta.json (sha256) committed |

Runbook: `discover.py` → `funding.py` → `fetch_pool_months.py --slug S` →
`coverage.py --slug S` → `race.py --slug S` (and `--rehedge-hours 0`) →
`tables.py` → `tests/test_e005_contracts.py`. Public
`arb1.arbitrum.io/rpc`, no credentials. Deterministic replay, no RNG (probe
seeds fixed at 42).
