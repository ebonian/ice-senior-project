---
id: E010
family: H-pool (capital-parameterized)
date: 2026-09-03
verdict: INCONCLUSIVE
---

# E010 — At $10k reference capital, some HL-hedgeable venue (mainnet now in scope) clears the gates the $1,420 menu could not

## Pre-registration (write BEFORE running)

**Hypothesis** — At a **$10,000 reference capital** (operator amendment
2026-09-03: capital is a test size, not a cap; the target is the rate), at
least one Uniswap V3 venue with every non-stable leg hedgeable on
Hyperliquid — with **Ethereum mainnet now in scope** — passes the full E005
gate set: best-arm **fees/gamma ≥ 1.5 central** (full window), **> 1.0 in
every calendar month**, and **net ≥ 10% APR central** through the full
frozen cost stack with a chain-correct gas envelope. Carried inside it, the
named **feeProtocol hypothesis** ([B4](../../discovery/BACKLOG.md), memo
[M004](../../discovery/memos/M004-capital-reopens-the-venue-menu.md)):
mainnet pools reading `feeProtocol = 0x0` would multiply LP fee income
×1.33, mapping E005's 0.86–0.97 near-misses to 0.87–1.29 — M004 §2.1's
governance record predicts this case is dead, and the per-pool on-chain
read decides, never the record.

**The one variable** — the **capital parameterization and the venue menu it
reopens**, vs E005 as the named baseline. Everything else stays frozen at
E005's values: engine unmodified; cost model `gate1-2026-08-29`; HPL hedge
envelope `e003-2026-08-29` (optimistic 1.984 / central 3.359 / pessimistic
8.320 bps); window **2026-05-01 → 2026-08-28 UTC**; width arms
±0.1/0.2/0.5/2.0/8.3% mapped per tick spacing; primary loop lag1h_rh1h,
recenter-only rehedge as sensitivity; constant re-mint LP notional.
Capital mapping keeps the C2 split: LP notional = capital × (1015/1420),
hedge equity = capital × (405/1420) → at $10k: **$7,147.89 LP / $2,852.11
hedge**. The **scaling law** is reported for every headline number at
$1,420 / $10,000 / $50,000 via the fixed-vs-proportional decomposition
(fixed = per-tx gas lines; proportional = every bps line).

**Three parts, all pre-named:**

- **Part A — mechanical restatement (no new data).** Verify from
  `cost_model.py` + the committed decision artifacts that the frozen stack
  is bps-proportional except per-tx gas; restate E003 / E006 / E007 / E008
  headline numbers and verdict signs at $10k and $50k by exact
  decomposition (e.g. E008's S5 −$0.025/day at $1.42k with ~$0.007/day
  fixed gas → ≈ −$0.13/day at $10k). **Expected: no sign flips**; any flip
  is a loud finding, not a footnote.
- **Part B — Arbitrum re-bind.** Recompute implied in-range share at the
  $10k LP notional (× 7147.89/1015 ≈ 7.042) for every E005-screened
  pool × arm from `e005/out/decision.json`; re-apply the ≤ 1% honesty gate;
  quantify the watchlist impact (expected: LINK/WETH ±8.3% 0.91% → ~6.4%
  dead; wstETH/WETH ±0.1% 0.28% → ~2.0% — LP-leg honesty dies, funding
  carry unaffected as it never depended on pool share).
- **Part C — the mainnet screen (new data).** M004 §3's pre-named venue
  set, raced over E005's exact UTC window: mainnet wstETH/WETH 0.01%,
  WETH/USDC 0.05%, WETH/USDC 0.30%, WETH/USDT 0.05%, WBTC/WETH 0.05%,
  LINK/WETH 0.30%, WBTC/WETH 0.30%, UNI/WETH 0.30%; Base WETH/USDC 0.05%
  (B3 folded in, secondary scope); probes mainnet LINK/WETH 0.05% and
  wstETH/WETH 0.05% (resolved + recorded; raced only if eligible). Any
  data limit vs the window is stated, never silently narrowed.

**Validity gates — all blocking; candidate numbers are unquotable until
they pass:**

1. **Engine-extension gate.** The extended (chain-parameterized) pipeline
   re-runs E005's Arbitrum control (`weth_usdc_0p05` on E003's parquets and
   funding CSV) and must reproduce the committed control row within
   **±0.05 on fees/gamma and ±5% on net $/day** at all three matching arms
   (E005 §4 recorded 0.00000 / 0.00% — any drift is regression).
2. **feeProtocol read, never assumed.** Per pool: `slot0().feeProtocol`
   read on-chain, cross-checked against a **second independent RPC
   provider**, plus a **SetFeeProtocol event scan over the full window**;
   a mid-window change applies piecewise accrual (E005 refused non-constant
   schedules; E010 implements piecewise because M004 §2.1's staged rollout
   makes mid-window flips plausible for thin pools).
3. **Measured mainnet gas envelope** (M004 §2.2 construction, frozen
   before any race): `baseFeePerGas` sampled from the window's own anchor
   headers; 3-point $/tx = (p25+0.02 / p50+0.05 / p95+0.10 gwei) × 250k
   blended gas/tx × window-mean ETH mark. Envelope points couple to the HPL
   envelope (optimistic gas with optimistic HPL, etc.). Base: same
   construction from Base headers + $0.005/tx L1-data adder. Arbitrum keeps
   frozen $0.0101/tx.
4. **Eligibility per venue** (validity, not verdict): median ≥ 48
   swaps/day; every non-stable leg HL-hedgeable (USDC/USDT stable-unhedged
   at mark ≡ 1.0; wstETH under the pre-registered ETH-beta exception);
   E003-family coverage gates (T1 chunk tiling, T2 participation, T3
   independent refetch) generalized per chain; **implied in-range share
   ≤ 1% at the $10k LP notional**; volume persistence — no month < 25% of
   that venue's peak month.

**Both lenses, per venue** — (i) best-arm fees/gamma, full window and worst
month; (ii) net APR at $10k central (all three coupled envelope points);
plus the **model-headroom flag**: does ANY width arm clear f/g ≥ 1.0 at an
honest share — the question that decides whether the range/timing model
thesis gets a venue back.

**Decision rule** —
- **SUPPORTED**: ≥ 1 venue × arm passes ALL gates with (a) f/g ≥ 1.5
  central full-window, (b) f/g > 1.0 central every calendar month, (c) net
  ≥ 10% APR central at $10k (≥ +$2.74/day), (d) implied share ≤ 1% at $10k,
  (e) volume persistence. Passing venues ranked by central net APR.
- **INCONCLUSIVE**: no full pass, but ≥ 1 venue clears **f/g ≥ 1.0** on an
  honest-share arm through all validity gates → named watchlist with what
  disambiguates.
- **REFUTED**: nothing ≥ 1.0 anywhere, mainnet included — B4 dies; the
  model thesis stays venue-less at any capital reachable here.
- **Separately and always**: the feeProtocol hypothesis outcome, stated
  explicitly — measured per-pool fee share (mainnet and Base), and where
  the actual multiplier (if any) lands E005's 0.86–0.97 near-misses.
- Part A signs and Part B share deaths are reported regardless of Part C's
  outcome.

**Abort criteria** — any validity gate fails (report the discrepancy, do
not proceed to candidate numbers); swap data unobtainable for a pre-named
venue (drop it, log it in the report — no silent caps); free disk < 2 GB
(checked in the runner before each fetch phase; budget ≤ ~3 GB compressed,
reduced at fetch time to engine-required fields); compute > 10× the
estimate (~3 h fetch + ~1 h race).

**Method** — artifacts under `backtest_model_server/e010/`; machinery
reused by import from `e005/` (registry pattern, keccak selectors, race
simulator, coverage gates) with the chain parameterized; mainnet RPC:
`ethereum-rpc.publicnode.com` primary with `eth.llamarpc.com` /
`1rpc.io/eth` failover (endpoints used are recorded per fetch); Base:
`base-rpc.publicnode.com` / `mainnet.base.org`; month block ranges derived
per chain by binary search on timestamps and committed; timestamp anchors +
`baseFeePerGas` from the same headers, committed; per-pool parquets
gitignored and re-derivable (blocks.json + meta.json sha256 committed);
ETH/BTC/LINK funding + marks reuse E005's committed CSVs bit-for-bit; UNI
funding + UNIUSDT marks fetched by the E005 recipe and committed.
Deterministic replay, no RNG. Blocking contract tests first
(`e010/tests/test_e010_contracts.py`): control reproduction, share math,
feeProtocol read vs independent source, determinism, scaling-law
arithmetic (per-venue $1.4k/$10k/$50k consistency with the
fixed/proportional decomposition).

## Result

Eleven venues resolved (9 screen + 2 probes); LINK/WETH 0.05% mainnet probe
sampled eligible (654 swaps/day) and raced; wstETH/WETH 0.05% mainnet
INELIGIBLE-thin (~1 swap/day, recorded). All validity gates passed before
any candidate number was read: control reproduction at 0.00% error on all
three matching arms (and < 1e-9 vs E005's committed control), two-provider
feeProtocol reads all matched, measured gas envelopes (mainnet $0.049 /
$0.083 / $0.368 per tx from 860 window basefee anchors, ETH mean $1,943.76;
Base $0.017–0.056), coverage T1/T2/T3/T5 clean on all 40 pool-months.
38/38 contract tests. Full numbers: `backtest_model_server/e010/REPORT.md`,
`out/decision.json`, `out/tables.md`.

**feeProtocol hypothesis: measured DEAD.** Every mainnet and Base pool
reads 0x44 (LPs keep 3/4; 0.01%/0.05% tiers) or 0x66 (5/6; 0.30%) —
Arbitrum's own haircuts — with zero in-window SetFeeProtocol events. The
×1.33 multiplier is 1.0; E005's near-misses stay.

**Part C.** Every USD-quoted major on mainnet and Base posts best-arm f/g
0.503–0.780 — the K3 venue property is chain-invariant. Honest f/g ≥ 1.0
exists at two venues: **mainnet LINK/WETH 0.30%** (f/g 1.337/1.208/1.099
across all arms at shares ≤ 0.876%, genuinely negative gamma, clean fee
flow; best net +$0.915/day central = +3.3% APR) and **mainnet wstETH/WETH
0.01%** (+$4.55/day, +16.6% APR at ±8.3% — but the fee line is carried 97%
by one month and 99.97% by ten depeg-wick swaps through near-empty ticks;
the durable residue is the ~5.5% APR carry package; REPORT §3).

**Part A.** No sign flips: E003 best −$0.844 → −$5.91/day at $10k; E006
ceiling +$6.06 → +$44.8 (upper bound; fee credit is share-aware concave —
measured in contract §8); E007 best −$0.074 → −$0.46; E008 best S5 −$0.025
→ −$0.121, August cells all still negative. All four verdicts unchanged.

**Part B.** The ×7.0423 linear share scaling kills 14 E005 arms including
both watchlist honest arms; measured re-races agree (wstETH ±0.1% 1.47%,
±0.2% 1.01%; LINK ±8.3% 6.03% — all > 1%). The wstETH carry survives
size-invariant: +$1.47–1.64/day (5.4–6.0% APR) at $10k, still under the
10% bar. Scaling law measured at $1.42k/$10k/$50k for every venue: USD
majors rate-invariant; thin-pool positives decay with size (Arbitrum LINK
flips negative at $50k).

## Verdict

**INCONCLUSIVE** — no venue × arm passes all five SUPPORTED gates; REFUTED
is excluded (honest f/g ≥ 1.0 exists — the pre-registered clause fires on
mainnet LINK/WETH 0.30% and wstETH/WETH 0.01%). Watchlist, with failed
gates: mainnet LINK/WETH 0.30% ±8.1% [a,b,c], ±1.8% [a,b,c], ±0.6%
[a,b,c]; mainnet wstETH/WETH 0.01% ±8.3% [b] (and §3's per-swap honesty
failure, which the aggregate gate cannot see). Disambiguation: (i) an
E006-style timing-ceiling measurement on mainnet LINK/WETH 0.30% — the
only venue where a model has honest headroom to buy; (ii) a per-swap
share-cap fee-credit rule for peg pools (the wick artifact is a
measurement-honesty gap, not a venue property); (iii) per-venue perp cost
calibration for LINK (envelope slippage is ETH-calibrated).

## Critique

1. *Proxy or goal?* Goal — net $/day through the frozen stack at the
   reference capital; but the single number that would have cleared the
   target (wstETH mainnet +16.6% APR) is a fee-credit artifact at
   dislocation wicks, and we said so rather than reporting the headline.
2. *Would it survive Gate 2?* The LINK 0.30% wide arm survives sign at
   +3.3% APR but not the target; the wstETH carry survives at ~5–6% APR
   (E009's caveats travel). Nothing else survives sign.
3. *Environment faithful enough?* The K9 full-share fee credit is the
   binding idealization and E010 both quantified its failure mode (§3) and
   showed the honest-share gate is insufficient at per-swap granularity.
   Hedge ratio still idealized; LINK/UNI perp slippage ETH-calibrated.
4. *Exactly one variable?* The capital parameterization and the menu it
   reopens — engine, costs, HPL envelope, window, arms all frozen;
   verified by exact control reproduction. Chain gas is part of the venue,
   measured under a pre-registered construction, not tuned.
5. *Symptom-fix of the previous iteration?* No — E008 closed the timing
   family on the old venue; this re-asked the venue question under the
   operator's amended constraint.

## What this changes

G-pool reopens and closes again, now chain-invariantly: **no USD-quoted
major on Arbitrum, mainnet, or Base pays its gamma at any width or any
capital**; capital was not the binding constraint the fee thesis needed.
The model thesis gets exactly one candidate venue (mainnet LINK/WETH
0.30%) and its ceiling is unmeasured. The B2 wstETH decision (on hold per
GOAL) gains: carry is size-invariant to $10k+ but its LP-leg share gates
die above ~$7k LP notional on Arbitrum at widths below ±0.5%; the mainnet
twin is the deeper home for the same carry (share 0.2–0.3% at ±0.5–2%)
once the K8 margin pass exists. Escalation to the operator per PROTOCOL
§7: the structural options are (a) accept carry at ~5–6% APR (B2, either
chain's wstETH pool, sized by the K8 pass), (b) fund a timing-ceiling
measurement on mainnet LINK/WETH 0.30% (new memo + experiment), or
(c) close the strategy family at the 10% bar. Harvest: K3 extended
chain-invariant; new K13 (fee switch universal), K14 (LINK mainnet
headroom), K15 (per-swap fee-credit honesty gap). No capital moves from
this repo (bot ADR 0008).
