# E010 — the capital-parameterized re-screen: INCONCLUSIVE. Capital does not buy the fee edge; it does buy one honest venue candidate and kills the Arbitrum watchlist's LP legs

**Verdict (pre-registered rule): INCONCLUSIVE.** No venue × arm passes all
five SUPPORTED gates at the $10k reference. REFUTED is excluded because two
mainnet venues clear fees/gamma ≥ 1.0 on honest-share arms. Named watchlist:

- **mainnet LINK/WETH 0.30%** (`0xa6cc3c25…`) — the one venue with honest
  f/g > 1.0 and genuinely negative gamma: **f/g 1.337 / 1.208 / 1.099** at
  ±0.6% / ±1.8% / ±8.1% with implied shares **0.876% / 0.299% / 0.073%**,
  fee flow clean (top-10 swap concentration 1.7%). Best arm ±8.1%: net
  **+$0.915/day central (+3.3% APR)**. Fails (a) 1.5×, (b) worst month
  0.701, (c) target. This is E005's LINK signal reproduced at mainnet depth
  — the share gate that killed it on Arbitrum at $10k (6.0% measured) is a
  non-issue here.
- **mainnet wstETH/WETH 0.01%** (`0x109830a1…`) — headline **+$4.55/day
  central (+16.6% APR)** at ±8.3%, every arm f/g > 1 at share < 1%, every
  month net-positive — **and the fee line does not survive per-swap honesty
  inspection** (§3): 97% of the ±8.3% arm's window fees ($361 of $372) land
  in June, carried by a handful of multi-million-dollar depeg-wick swaps
  through momentarily near-empty ticks. The durable residue is the carry
  package: **≈ +$1.5/day (≈ 5.5% APR)**, consistent with its Arbitrum twin
  (+6.0% at $10k) and with E009/K12.

**The feeProtocol hypothesis (B4's named mechanism) is measured DEAD.**
Every mainnet pool reads `slot0().feeProtocol = 0x44` (LPs keep 3/4;
0.01%/0.05% tiers) or `0x66` (5/6; 0.30% tier) — identical to Arbitrum —
with **zero** SetFeeProtocol events in the window and a two-provider
cross-check on every read. The UNIfication rollout (M004 §2.1) reached
everything we screened before 2026-05. The ×1.33 multiplier is exactly 1.0;
E005's 0.86–0.97 near-misses stay where they were.

**The venue property is chain-invariant.** Every USD-quoted major on
mainnet and Base posts best-arm f/g 0.50–0.78 — at, or below, Arbitrum's
0.63–0.97 band (K3). Mainnet's deep pools make the honesty gate trivial
(shares 0.03–0.2%) and change nothing else. Base (B3, folded in): 0.78.

Artifacts: [`out/decision.json`](out/decision.json),
[`out/tables.md`](out/tables.md),
[`out/wick_sensitivity.json`](out/wick_sensitivity.json),
[`out/parts_ab.json`](out/parts_ab.json), per-venue
`out/<slug>/lag1h_rh1h_cap*_gas-*/`.

---

## 1 — The screen

$10k reference capital (LP notional $7,147.89, C2 split), window 2026-05-01
→ 2026-08-28 UTC, lag1h_rh1h, **coupled envelope** (gas point g priced with
HPL point g). Best arm per venue; full grid in [`out/tables.md`](out/tables.md):

| venue | chain | best arm | f/g full | worst-mo f/g | net cen $/d | opt | pess | APR cen | share | headroom | fails |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| wstETH/WETH 0.01% | mainnet | ±8.3% | 11.18* | 0.006* | **+4.55** | +4.57 | +4.47 | **+16.6%** | 0.97% | YES* | b |
| WETH/USDC 0.05% | mainnet | ±8.3% | 0.503 | 0.403 | −11.91 | −11.34 | −14.05 | −43.5% | 0.036% | no | a,b,c |
| WETH/USDC 0.30% | mainnet | ±8.1% | 0.572 | 0.416 | −10.55 | −10.06 | −12.40 | −38.5% | 0.166% | no | a,b,c |
| WETH/USDT 0.05% | mainnet | ±8.3% | 0.721 | 0.695 | −5.64 | −5.07 | −7.76 | −20.6% | 0.196% | no | a,b,c |
| WBTC/WETH 0.05% | mainnet | ±8.3% | 0.628 | 0.489 | −1.50 | −1.00 | −3.33 | −5.5% | 0.033% | no | a,b,c |
| **LINK/WETH 0.30%** | mainnet | ±8.1% | **1.099** | 0.701 | **+0.915** | +1.38 | −0.82 | **+3.3%** | 0.073% | **YES** | a,b,c |
| WBTC/WETH 0.30% | mainnet | ±8.1% | 0.992 | 0.652 | +0.354 | +0.67 | −0.81 | +1.3% | 0.252% | no | a,b,c |
| UNI/WETH 0.30% | mainnet | ±8.1% | 0.794 | 0.693 | −7.60 | −6.17 | −12.85 | −27.7% | 0.524% | no | a,b,c |
| WETH/USDC 0.05% | base | ±8.3% | 0.780 | 0.684 | −4.62 | −4.06 | −6.63 | −16.9% | 0.212% | no | a,b,c |
| LINK/WETH 0.05% (probe) | mainnet | ±8.3% | 0.884 | 0.633 | −0.95 | −0.20 | −3.69 | −3.5% | 3.75% | no | a,b,c,d |
| wstETH/WETH 0.05% (probe) | mainnet | — | | | | | | | | | INELIGIBLE-thin (~1 swap/day) |

\* degenerate: hedged gamma is a small POSITIVE accretion drift (fees ÷
|tiny positive|), and the fee line is wick-carried — see §3. The starred
YES does not survive §3; the un-starred headroom finding is LINK/WETH 0.30%.

**Decision-rule evaluation** (the rule as a program,
[`tables10.py`](tables10.py) → [`out/decision.json`](out/decision.json)):
SUPPORTED — no row passes (a)–(e); INCONCLUSIVE clause fires — honest
f/g ≥ 1.0 rows exist (8: five wstETH arms, three LINK 0.30% arms);
REFUTED excluded.

## 2 — The model-headroom answer

The question that decides whether the range/timing model thesis gets a
venue back: **does any width arm clear f/g ≥ 1.0 at honest share?**

**Yes — mainnet LINK/WETH 0.30%, at every raced width** (1.099–1.337), with
real negative gamma, clean fee flow, volume persistence 0.35, and monthly
f/g 0.70–0.88 in the worst month. It is the best honest fees-vs-gamma
surface measured anywhere in this program (Arbitrum LINK managed 1.20 only
at ±8.3%, and dies the $10k share gate). What it is NOT: profitable at the
target — narrow arms lose to rebalance costs (−$4.46/day at ±0.6%), the
wide arm nets +3.3% APR against the 10% bar. A timing/width model would
have to buy roughly +$1.8/day of improvement on the ±8.1% arm — an
E006-style ceiling measurement on THIS pool is the natural next question,
and is not answered by E010.

## 3 — The wstETH twin's fee line fails per-swap honesty (K9, quantified)

Gate (d) bounds the aggregate implied share (0.97% — passes). The per-swap
inspection ([`wick_diag.py`](wick_diag.py) →
[`out/wick_sensitivity.json`](out/wick_sensitivity.json)) does not pass:

- Ranking swaps by `vol_usd / pool_liquidity` (the fee-credit weight in the
  small-share regime, independent of our position size): the **top 10 of
  36,164 swaps carry 99.97% of the total weight**.
- The race's monthly fee decomposition agrees: ±8.3% arm fees are **$0.07 /
  $361.44 / $8.46 / $1.90** across May–Aug — 97% in June.
- The carrying events are depeg wicks: e.g. 2026-06-03 20:57 UTC, a $4.0M
  swap at tick 3563 (median 2132 — a ~15% dislocation) through recorded
  in-range liquidity 2.8e18, ~10⁻⁷ of the pool's normal 1e25. Our simulated
  wide-range L would have been essentially the only liquidity there, credited
  up to ~93% of the swap's fee — while the adverse inventory round-trip
  inside the hour is invisible to the 1h mark grid.

Ex-June, the ±8.3% fee line is ≈ $0.12/day, and the venue's durable net is
the carry package: funding **+$1.25/day** + accretion drift **+$0.28/day**
+ residual fees ≈ **+$1.5/day ≈ 5.5% APR** — the same animal as the
Arbitrum wstETH position (measured +$1.64/day best, 6.0% APR, at $10k in
Part B), not a fee engine. In live trading those wicks are exactly where
JIT/MEV competition and adverse selection concentrate (M004 §2.3); no
capital decision should price them as income.

## 4 — Part A: the mechanical restatement (no sign flips)

Linear restatement at $10k (pre-registered fixed/proportional arithmetic;
fixed gas recovered exactly as `onchain − swapped_notional × 5.155bps` where
the artifact carries a ledger, or the stated n-streak approximation for
E007/E008 finals). [`out/parts_ab.json`](out/parts_ab.json):

| experiment | headline at $1.42k | at $10k (linear) | verdict sign |
|---|---:|---:|---|
| E003 best arm (±8.3%) | −$0.844/day | −$5.91/day | REFUTED stays |
| E006 oracle ceiling (w4) | +$6.06/day | +$44.8/day (upper bound²) | SUPPORTED stays |
| E007 best causal (C6 w10) | −$0.074/day | −$0.46/day | REFUTED stays |
| E008 best streak rule (S5 w10) | −$0.025/day | −$0.121/day | REFUTED stays |

**No sign flips anywhere**; E008's August cells stay negative at $10k for
all 12 candidates. ² E006's linear number is an upper bound twice over: the
engine's fee credit is share-aware and **concave in capital** (contract
test §8 measures it: fees/$ strictly decreasing, path invariant), and w4's
implied share ~0.7% at $1.42k is ~5% at $10k.

The one capital-dependent cost term confirms K1: per-tx gas. Everything
else in `gate1-2026-08-29` is bps on notional — verified in code and by the
re-race decomposition (ex-fee net per LP dollar capital-invariant to
< 0.05% on every tested arm).

## 5 — Part B: the Arbitrum re-bind at $10k

Pre-registered linear share scaling (×7.0423) kills **14 arms** that passed
gate (d) at $1,420 — including both watchlist honest arms. The measured
re-races (engine's own concave fee credit, same parquets) agree on the
outcome and sharpen the numbers:

| pool / arm | share $1.42k | ×7.04 linear | measured $10k | gate (d) |
|---|---:|---:|---:|---|
| wstETH/WETH 0.01% ±0.1% | 0.28% | 1.97% | **1.47%** | DEAD both ways |
| wstETH/WETH 0.01% ±0.2% | — | — | 1.01% | DEAD (measured) |
| wstETH/WETH 0.01% ±0.5% | — | — | 0.65% | survives |
| LINK/WETH 0.05% ±8.3% | 0.91% | 6.41% | **6.03%** | DEAD both ways |

The wstETH **carry** is share-independent and survives intact: at $10k the
package nets **+$1.47 to +$1.64/day (5.4–6.0% APR)** across ±0.5%–±8.3%
arms (funding +$1.25–1.49/day), vs E005's 5.7–7.0% at $1,420 — the rate is
size-invariant, exactly as E005 predicted, and still under the 10% bar.
K8/K12 margin math is unchanged by E010.

## 6 — The measured mainnet gas envelope (validity gate iii)

From 860 window anchor headers (mainnet, stride 1000) and 1,034 (Base,
stride 5000), ETH mark window-mean $1,943.76
([`out/gas_envelope.json`](out/gas_envelope.json)):

| chain | basefee p25/p50/p95 (max) gwei | $/tx opt/cen/pess | $/4-tx recenter cen |
|---|---|---|---|
| mainnet | 0.080 / 0.122 / 0.658 (8.87) | 0.049 / 0.083 / 0.368 | $0.33 (≈ 4.7 bps of LP) |
| base | 0.005 / 0.005 / 0.005 (0.249) | 0.017 / 0.032 / 0.056 | $0.13 |

M004 §2.2's regime read holds: 2026 mainnet gas at $10k is a real but
non-deciding line — it prices out the 6-recenter/day narrow arms (~$2/day
central) and moves nothing at ±2% and wider. Every verdict-relevant deficit
is gamma-driven, not gas-driven. Arbitrum stays at the frozen $0.0101/tx.

## 7 — Scaling law (measured by re-race, central envelope)

Net $/day (APR) at $1,420 / $10,000 / $50,000, best arm per venue —
fee-credit concavity is why this is measured, not multiplied:

| venue | $1,420 | $10,000 | $50,000 |
|---|---:|---:|---:|
| mainnet wstETH/WETH 0.01% | +2.30 (+59%²) | +4.55 (+16.6%²) | +10.81 (+7.9%²) |
| mainnet LINK/WETH 0.30% | +0.11 (+2.9%) | +0.92 (+3.3%) | +4.58 (+3.3%) |
| mainnet WBTC/WETH 0.30% | +0.04 (+1.0%) | +0.35 (+1.3%) | +1.67 (+1.2%) |
| mainnet WETH/USDC 0.05% | −1.72 (−44%) | −11.91 (−43%) | −59.53 (−44%) |
| base WETH/USDC 0.05% | −0.66 (−17%) | −4.62 (−17%) | −23.70 (−17%) |
| arb wstETH/WETH 0.01% (B) | +0.27 (+7.0%) | +1.64 (+6.0%) | +7.92 (+5.8%) |
| arb LINK/WETH 0.05% (B) | +0.17 (+4.5%) | +0.89 (+3.3%) | −1.63 (−1.2%) |

² wick-carried (§3); the durable wstETH rate is ~5–6% at any size. The
USD-quoted majors are rate-invariant (bps economics); the thin-pool
positives decay with size (share concavity); Arbitrum LINK flips sign at
$50k — capital *hurts* on thin pools. **Nothing anywhere approaches 10%
APR honestly at any capital.**

## 8 — Validation

- **Engine-extension gate (i):** race10's control run on E003's parquets
  reproduces E003's lag1h_rh1h row at **0.00000 Δf/g and 0.00% Δnet** on
  all three matching arms and equals E005's committed control to
  **< 1e-9 relative** (max drift measured in the contract run). Recenter
  counts 715/119/11 identical.
- **feeProtocol (ii):** every RESOLVED pool read on two independent
  providers (publicnode + Tenderly), all matched; SetFeeProtocol scans
  from window start to head: zero in-window events anywhere.
- **Gas (iii):** measured envelope above; monotonicity + provenance pinned.
- **Coverage (iv):** T1/T2/T3/T5 pass on all 40 pool-months (10 venues; no
  DATA-FAIL; interp error ≤ 42s mainnet, 0s Base); all raced venues clear
  median ≥ 48 swaps/day and volume persistence.
- **Contract tests:** [`tests/test_e010_contracts.py`](tests/test_e010_contracts.py)
  — frozen constants, width-mapping identity, control gate, cross-provider
  reads, gas monotonicity, per-arm accounting identity (≤ 1e-6 on every
  published run), determinism (bit-identical re-race), and the scaling
  decomposition (ex-fee net per LP dollar invariant ≤ 0.05%; fee credit
  concave; path capital-invariant). All pass.

## 9 — What was replayed, what was modelled, deviations

Replayed: every swap on 10 venues (4.13M swaps total: 1.48M mainnet, 2.45M
Base, plus E003/E005's committed Arbitrum parquets) via recorded recipes;
hourly HL funding per perp (E005 CSVs + new UNI CSV, 2856 rows, 0 gaps);
Binance ETHUSDT 1h marks (E005's committed CSV). Modelled: the frozen cost
stack, the three-point HPL envelope, the measured chain gas envelopes, and
the fee credit `L/(L_pool + L)` per swap.

Deviations, all validity-preserving, none decided after seeing a number
they could move:

1. **Logs endpoint:** publicnode gates historical `eth_getLogs` behind a
   token (discovered at fetch probe); swap logs came from Tenderly's public
   gateway (recorded in every meta.json), state/headers from publicnode —
   which also supplies the independence for the feeProtocol cross-check.
2. **Segment-level checkpointing** added to `fetch10.py` mid-run (Base
   months exceed one foreground call); output schema unchanged.
3. **Probe handling per pre-registration:** LINK/WETH 0.05% mainnet sampled
   eligible (654/day) and raced; wstETH/WETH 0.05% INELIGIBLE-thin (~1/day),
   recorded, not raced.
4. **Part B carries both readings:** the pre-registered linear share
   scaling AND measured re-races; both kill the same arms.
5. **Scaling law measured by re-race** rather than linear arithmetic — the
   share-aware fee credit is concave in capital (contract §8); Part A keeps
   the pre-registered linear form and flags the same concavity.
6. **`wick_diag.py` added post-verdict-rule** as a K9 quantification; it
   changes no gate and no verdict — it changes what the watchlist entry for
   wstETH mainnet is allowed to claim.
7. E007/E008 fixed-gas decomposition approximated from n_streaks (their
   finals carry no cost ledger); stated in `parts_ab.py`.

## 10 — Reproducing

| Path | Purpose |
|---|---|
| [`registry.py`](registry.py) | Chains, candidates, capital parameterization, frozen imports |
| [`derive_blocks.py`](derive_blocks.py) | Month block ranges + anchors + basefees per chain (committed) |
| [`gas10.py`](gas10.py) | Measured 3-point gas envelope per chain |
| [`discover10.py`](discover10.py) | Factory resolution, feeProtocol + events + cross-check, HL perps, probe sampling |
| [`fetch10.py`](fetch10.py) | Chain-aware month fetch, segment-checkpointed |
| [`funding_uni.py`](funding_uni.py) | HL UNI funding CSV (committed) |
| [`coverage10.py`](coverage10.py) | T1/T2/T3/T5 per venue (e005's gates by import) |
| [`race10.py`](race10.py) | e005's simulator by import; capital + chain-gas parameterization |
| [`parts_ab.py`](parts_ab.py) | Part A restatement + Part B re-bind |
| [`tables10.py`](tables10.py) | Decision rule as a program; all tables |
| [`wick_diag.py`](wick_diag.py) | Per-swap fee-credit honesty diagnostic |
| [`tests/`](tests/) | Blocking contract tests |

Runbook: `derive_blocks.py --chain {mainnet,base}` → `gas10.py` →
`discover10.py` → `funding_uni.py` → `fetch10.py --slug S` →
`coverage10.py --slug S` → `race10.py --slug S --capital C --gas-point G`
(control: `--slug control_weth_usdc_0p05 --capital 1420`; Part B:
`--slug e005:<slug>`) → `parts_ab.py` → `tables10.py` → `wick_diag.py` →
`tests/test_e010_contracts.py`. Public endpoints, no credentials.
Deterministic replay, no RNG (probe seeds fixed at 42).

## 11 — What this does not answer

- **JIT / adverse selection (K9) — mandatory, and WORSE here.** Every
  positive number assumes our liquidity earns its recorded-pool share of
  every in-range swap. On mainnet this is more optimistic than on Arbitrum:
  JIT concentrates exactly on the USDC/WETH 5bps pool and on large swaps
  (M004 §2.3, Wan & Adams; Xiong et al. measure 85% dilution on targeted
  swaps), and §3 shows the failure mode concretely — the wstETH twin's
  "16.6% APR" is a fee-credit artifact at dislocation wicks. No 2025–2026
  post-fee-switch JIT measurement exists publicly; nothing here prices it.
- **Whether a timing/width model can buy +$1.8/day on mainnet LINK/WETH
  0.30%** — the E006-style ceiling on that venue is unmeasured. That is the
  next falsifiable question if the operator wants the model thesis alive.
- **Per-venue perp cost calibration** — the HPL envelope's slippage points
  were calibrated on ETH-perp fills; LINK/UNI books are thinner, so their
  pessimistic points are optimistic bounds (unchanged from E005).
- **wstETH carry durability** is E009's answer (K12: compressing, no bear
  market in-era), not E010's; the $10k re-bind changes its share gates and
  nothing about the carry itself.
