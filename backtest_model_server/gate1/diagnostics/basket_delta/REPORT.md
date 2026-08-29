# E004 — basket-delta reconciliation

**The engine's chain read is correct, and it is corroborated to the wei by evidence the
engine's own decoder never touches. The REFUTED branch does not fire: there is no engine
bug, E002's IL line does not need re-checking, and E003 is not blocked.**

Both derivations were reproduced from raw inputs and the gap between them closes to
$0.000000 on both trials. It is not one error but two, and both are on report 01's side:

| Trial | report 01 | engine | gap | cause |
|---|---:|---:|---:|---|
| T5 | +$8.5214 | +$9.4988 | +$0.9774 | ETH leg inverted at an off-chain price (**+$0.78**), price source (+$0.20) |
| T4 | +$1.2031 | −$4.2720 | −$5.4751 | **two cycles closed at exit transactions that reverted (−$5.07)**, ETH leg (−$0.48), price source (+$0.08) |

Against the pre-registered decision rule, applied as written:

- **REFUTED — does not fire.** The Mint event is *consistent* with the transaction's token
  flows, exactly (§1).
- **SUPPORTED — fires on T5.** Feeding report 01's method the chain-read amounts moves it
  to **+$9.2976**, which is **+9.1%** of the published +$8.52 and inside the ±10% band.
- **T4 — INCONCLUSIVE as pre-registered.** The same single substitution gives **+$0.7199**,
  −40.0% against +$1.20, outside the band. The pre-registered test was the wrong instrument
  for T4, because T4's divergence is not an amount problem. It is fully located anyway (§3),
  it is independently proven on chain, and it is still a report-01 defect rather than an
  engine one.

One finding supersedes the hypothesis it was written to test. The gate1 REPORT §3.3 guessed
that report 01 went wrong by "inverting liquidity from a five-minute AUM snapshot". The
snapshot is not the error — it agrees with the chain to 0.08%. The error is the **price**
fed to that inversion, amplified about **185×** by narrow-range V3 geometry (§4).

---

## 1 — The decisive check: is the Mint event real?

The engine reads the LP position's ETH leg off the pool's `Mint` event. If that read were
wrong, this would be an engine bug and everything downstream would be suspect. So the Mint
event was checked against a source that shares none of its decoding path: the ERC-20
`Transfer` logs in the same receipt, emitted by the WETH and USDC token contracts rather
than by the pool. A V3 mint pulls both tokens in `uniswapV3MintCallback`, so the transfers
into the pool must equal `Mint.amount0/amount1` exactly.

**T5 breakout cycle, mint tx `0xf0f10b4fa0517e4dcfcf8f71e0b905ba8d2b714f2aecefc571542db374fd3bc7`**
(block 462761817, status `0x1`):

```
pool  Mint.amount0            250925078172474145 wei
WETH  Transfer -> pool        250925078172474145 wei     diff 0
pool  Mint.amount1            443561418                  (443.561418 USDC)
USDC  Transfer -> pool        443561418                  diff 0
```

The flagged deposit of **0.250925 ETH is real**. Report 01's implied ≈0.2316 ETH is the
number that is wrong. The breakout's exit (`0xcc2487ca57…`) checks out too: `Collect`
matches the tokens actually leaving the pool to the unit, and `Collect ≥ Burn` with the
difference being fees. **7 of 7 checks passed** across the sampled mints and burns.

The same check applied to T4's two divergent exits returned the finding that explains T4:

| recorded as | ts (UTC) | tx | status | logs |
|---|---|---|---|---|
| `executed_exit` | 2026-05-13 05:02:06 | `0x4c731432aaf1c5514659b741101406710520a53d784ad816acc80bab53a1c8ab` | **`0x0` reverted** | 0 |
| `executed_exit` | 2026-05-13 10:02:05 | `0x88dd8ddfc607fff8eaceb459886459d20c50f3c234581194685b826a55f13b0b` | **`0x0` reverted** | 0 |

Nothing was burned at either. Report 01 closes a cycle at both. This is finding F4, and
here is what it costs.

## 2 — The ladder

Both sides compute `basket_delta = a0 × (P_exit − P_entry)`. The formula is identical, so
the whole gap is in the inputs, and exactly three differ. Each rung substitutes one:

| rung | what changes | T5 | T4 |
|---|---|---:|---:|
| S0 | report 01 as published | +8.5214 | +1.2031 |
| S1 | ETH leg from the `Mint` event | +9.2976 | +0.7199 |
| S2 | price from the pool at the block | +9.4988 | +0.7993 |
| S3 | cycle boundaries from the `Burn` events | +9.4988 | **−4.2720** |
| | engine as published | +9.4988 | −4.2720 |

| effect | T5 | T4 |
|---|---:|---:|
| amount (S1−S0) | **+0.7762** | −0.4832 |
| price source (S2−S1) | +0.2012 | +0.0795 |
| boundary / F4 (S3−S2) | +0.0000 | **−5.0713** |
| coverage (cycles one side lacks) | +0.0000 | +0.0000 |
| **identity residual** | **+0.000000** | **+0.000000** |

Both derivations were re-run from raw inputs, not quoted. The re-implementation of report
01's method reproduces its published totals to **$0.0014 (T5)** and **$0.0031 (T4)**, so the
ladder starts from report 01's actual arithmetic rather than an approximation of it. S2 for
T4 is the engine's existing `--assume-all-exits-burned` run (`out/T4-legacy-pairing`), which
is the engine at report 01's cycle boundaries — so the boundary effect is measured, not
inferred.

The **price source is not the problem in either trial** (+$0.20 and +$0.08 net). The
Binance-vs-pool difference is a few bp and sign-random, and it cancels in aggregate. That
matters, because it means the USDT/USDC basis noted in report 01 §9 is not what broke this
line.

## 3 — Cycle-level table

`a0` in ETH; ΔP and basket in USD. ⚑ marks a cycle the two sides close at different instants.

#### T5

| # | mint (UTC) | a0 report 01 | a0 chain | a0 err | ΔP r01 | ΔP chain | basket r01 | basket engine | diff | dominant cause |
|--:|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| 1 | 2026-05-14 05:02 | 0.251462 | 0.251457 | -0.00% | +12.45 | +12.52 | +3.131 | +3.147 | +0.017 | price source |
| 2 | 2026-05-14 08:02 | 0.228509 | 0.235206 | +2.93% | -6.53 | -6.62 | -1.491 | -1.556 | -0.065 | amount |
| 3 | 2026-05-14 11:02 | 0.230870 | 0.254349 | +10.17% | -2.58 | -2.64 | -0.595 | -0.671 | -0.076 | amount |
| 4 | 2026-05-14 14:02 | 0.231559 | 0.250925 | +8.36% | +43.00 | +43.81 | +9.956 | +10.987 | **+1.031** | amount |
| 5 | 2026-05-14 17:02 | 0.214611 | 0.217579 | +1.38% | -3.54 | -2.37 | -0.760 | -0.515 | +0.245 | price source |
| 6 | 2026-05-14 20:02 | 0.230728 | 0.225643 | -2.20% | -1.78 | -1.76 | -0.410 | -0.398 | +0.013 | amount |
| 7 | 2026-05-14 23:02 | 0.256951 | 0.252070 | -1.90% | -2.57 | -3.57 | -0.660 | -0.899 | -0.238 | price source |
| 8 | 2026-05-15 02:02 | 0.224890 | 0.212127 | -5.68% | -2.88 | -2.82 | -0.648 | -0.597 | +0.051 | amount |
| | **total** | | | | | | **+8.521** | **+9.499** | **+0.977** | |

#### T4

| # | mint (UTC) | a0 report 01 | a0 chain | a0 err | ΔP r01 | ΔP chain | basket r01 | basket engine | diff | dominant cause |
|--:|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| 1 | 2026-05-12 18:02 | 0.215201 | 0.237985 | +10.59% | +2.43 | +2.54 | +0.522 | +0.605 | +0.083 | amount |
| 2 | 2026-05-12 20:02 | 0.208384 | 0.221589 | +6.34% | -0.02 | -0.11 | -0.004 | -0.025 | -0.021 | price source |
| 3 | 2026-05-12 22:02 | 0.214969 | 0.213807 | -0.54% | -6.95 | -6.58 | -1.493 | -1.407 | +0.087 | price source |
| 4 | 2026-05-13 02:02 | 0.284651 | 0.261076 | -8.28% | +6.16 | +4.06 | +1.754 | +1.060 | -0.694 | price source |
| 5 | 2026-05-13 04:02 ⚑ | 0.239954 | 0.244610 | +1.94% | +3.44 | **−4.13** | +0.826 | -1.010 | **-1.836** | boundary |
| 6 | 2026-05-13 07:02 | 0.246983 | 0.243024 | -1.60% | +0.85 | -0.24 | +0.209 | -0.058 | -0.266 | price source |
| 7 | 2026-05-13 09:02 ⚑ | 0.232867 | 0.253946 | +9.05% | +3.21 | **−6.92** | +0.748 | -1.757 | **-2.505** | boundary |
| 8 | 2026-05-13 12:02 | 0.206090 | 0.232415 | +12.77% | -16.37 | -15.41 | -3.374 | -3.580 | -0.206 | amount |
| 9 | 2026-05-13 14:02 | 0.186149 | 0.181482 | -2.51% | +10.83 | +10.47 | +2.015 | +1.899 | -0.116 | price source |
| | **total** | | | | | | **+1.203** | **−4.272** | **−5.475** | |

The two ⚑ cycles carry −$4.34 of T4's −$5.48. On both, the two derivations do not merely
price the same move differently — they **disagree on the sign of the move**, because report
01 closes the position an hour early at a burn that never happened, and ETH moved the other
way over the hour it actually stayed open.

## 4 — The one-cycle story: why T5's breakout ETH leg is 8% light

Report 01 does not observe the ETH leg. It infers it: take the position's USD value `V0`
from an AUM snapshot, take a price `P0`, back out liquidity `L`, read `a0 = L·x0(P0)`. The
gate1 REPORT guessed the snapshot was the weak input. It is not.

For the breakout cycle (range **[2243.998, 2266.549]**, 100 bp wide):

```
V0 from the AUM snapshot   1008.317   vs   engine 1009.118    -0.08%     <- fine
P0 Binance @ recorder row  2254.8487
P0 pool     @ mint block   2253.8867                          +4.27 bp   <- the error

a0 from (V0_r01, P0_binance)   0.231441      <- report 01's number
a0 from (V0_r01, P0_chain)     0.250608      <- same V0, only the price swapped
a0 from the Mint event         0.250925      <- ground truth, verified in §1
```

**Swapping only the inversion price closes 8.28 of the 8.36 percentage points.** The AUM
snapshot is exonerated; a 4.27 bp price difference is the whole error.

The reason such a small input error produces such a large output error is geometric. In a
concentrated range the ETH share of a position's value sweeps from 100% to 0% across the
range width, so with `V0` held fixed the inferred ETH amount is extremely sensitive to where
in the range you believe the price sits:

| | T5 | T4 |
|---|---:|---:|
| d(a0)/a0 per 1 bp of price error | **−184 bp** | **−189 bp** |
| entry-price error, Binance vs pool | −3.2 to +5.2 bp | −5.3 to +5.9 bp |
| mean abs ETH-leg error, as published | 4.08% | 5.96% |
| mean abs ETH-leg error, price fixed | **0.05%** | **0.02%** |

**A ~185× amplifier sits between the price you feed the inversion and the ETH leg you get
out of it.** At that gain the USDT/USDC basis alone (3–4 bp, report 01 §9) is enough to move
the ETH leg by 6–8%. The per-cycle errors are consequently sign-random (T5: −5.7% to
+10.2%; T4: −8.3% to +12.8%) rather than a bias, which is why they largely cancel in a
24-hour total (+$0.78 on a +$9.50 line) while dominating any single cycle — and the one
cycle where they do not cancel is the breakout, because that is the cycle with a $44 price
move for the error to multiply against.

The transferable rule: **never infer a V3 position's token split from a USD value and an
off-chain price.** Read it from the Mint event; if a counterfactual must size a position
from a capital figure, invert at the *pool's* price, never at a reference price.

## 5 — Corrected figures

Delta luck is report 01 §4's construction — the LP basket's directional gain plus the perp
short's directional P&L. Only the basket term changes here. The directional term is a
hedge-side number that none of the three substituted inputs reaches; re-deriving it
reproduces report 01's published values exactly (T5 −$4.5357 vs −$4.54; T4 +$3.4401 vs the
+$3.44 its figures imply), so it carries through unchanged. Observed net is the recorded AUM
change and is untouched.

| | T5 published | **T5 corrected** | T4 published | **T4 corrected** |
|---|---:|---:|---:|---:|
| LP basket delta | +8.52 | **+9.50** | +1.20 | **−4.27** |
| hedge directional P&L | −4.54 | −4.54 | +3.44 | +3.44 |
| **delta luck** | +3.98 | **+4.96** | +4.64 | **−0.83** |
| observed net (recorded) | −12.60 | −12.60 | −8.76 | −8.76 |
| **luck-stripped structural net** | −16.58 | **−17.56** | −13.40 | **−7.93** |

The exact substitution: `delta_luck = basket_delta + directional`, with `basket_delta`
replaced by the engine's chain-priced total (T5 +9.4988, T4 −4.2720) and
`luck_stripped = observed_net − delta_luck`.

Two consequences for the narrative, not just the arithmetic:

- **Report 01 §6's "both trials happened to gain ~$4 from under-hedge" is false for T4.**
  T4's delta luck was slightly *negative*. The corrected pair is +$4.96 and −$0.83, which
  straddle zero and so actually support the "expectation ≈ 0, strip it before projecting"
  instruction better than the original two same-signed figures did.
- **The two trials' luck-stripped nets move in opposite directions and converge**: T5 gets
  ~$1 worse, T4 gets ~$5.5 better, narrowing the spread from −16.6/−13.4 to −17.6/−7.9.
  T4 was the calm day; on the corrected numbers it is materially less bad than published,
  and the T5-vs-T4 gap is now dominated by IL (−10.90 vs −4.27) as report 01 §7 argued.

An alternative T5 figure exists and was not used: the engine's `exact_from_mint_burn`
variant gives **+$10.1006**, but only over the 7 cycles that actually burned, so it is not
comparable to an 8-cycle total. Restricted to the same 7 cycles the chain-priced total is
+$10.0958 — the closed-form and the raw-token-delta methods agree to **$0.005**, which is an
independent check on the engine's V3 arithmetic.

## 6 — What remains open

- **The luck construction subtracts quantities with different time coverage.** Basket delta
  is measured only while an LP position is open (T5 16h of 24h = 67%; T4 13h of 24h = 54%),
  while the directional hedge P&L spans all 24 hours including flat periods. "Delta luck" is
  therefore not a clean single-segment quantity. This is inherited from report 01, not
  introduced here, but it caps how precisely either figure can be read — and it is the same
  out-of-position exposure the flat-gap residual is already trying to price.
- **T5's last cycle is closed at a reverted exit on both sides.** The 2026-05-15 04:02 exit
  reverted (`0xb23a2565e6…`, status `0x0`); the position was still open when the window
  ended, and `engine/trials.py` deliberately closes a trailing cycle at the last orphan exit
  in that case. Report 01 does the same, so it cancels out of this reconciliation and its
  contribution is small (−$0.597), but "crystallized" is loose for that one cycle in both
  derivations.
- **T4's residual moves.** Correcting the basket by −$5.47 while IL stays put (engine
  −$4.2701 vs report 01 −$4.51, a passing line) pushes the change into T4's unexplained
  residual, which gate1 REPORT §4 already flagged as +$2.90 and the wrong sign versus T5.
  Basket is first-order in ΔP and IL is second-order, which is why an hour-long boundary
  shift swings one by $5 and barely moves the other — but the residual line should be
  re-read after this correction lands, not carried over.
- **Not re-derived here:** everything outside the basket-delta line. The four E002 lines
  were left alone; this diagnostic only re-priced the line that failed.

## 7 — Reproducing

```bash
cd /home/poon/developments/llaminet/research
nix develop .#gate1 -c python backtest_model_server/gate1/diagnostics/basket_delta/reconcile.py
nix develop .#gate1 -c python backtest_model_server/gate1/diagnostics/basket_delta/verify_chain.py
```

| file | what it is |
|---|---|
| `reconcile.py` | re-implements report 01's method, runs the substitution ladder, writes the corrected figures |
| `verify_chain.py` | checks `Mint`/`Burn`/`Collect` against the receipts' ERC-20 `Transfer` logs |
| `cycle_table.csv` | the §3 table, machine-readable, with per-cycle cause |
| `reconciliation.json` | every rung, per cycle and per trial, plus the corrected figures |
| `chain_verification.json` | receipts, decoded transfers, and each check's verdict |

`verify_chain.py` needs network. It tries `ARBITRUM_RPC_URL` from `model/.env` first and
falls back to public `arb1.arbitrum.io/rpc`; the keyed endpoint was returning HTTP 429
during this run, and the public node served every receipt identically. Nothing here writes
to `gate1/engine/` or to the bot repo.
