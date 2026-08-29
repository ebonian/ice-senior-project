# E003 — the cost-honest width race

> **Experiment:** [`loop/experiments/E003`](../../loop/experiments/E003-cost-honest-width-race.md).
> **Run date:** 2026-08-29. **Cost model:** `gate1-2026-08-29`, imported from
> [`gate1/engine/cost_model.py`](../gate1/engine/cost_model.py) unmodified.
> **Envelope:** `e003-2026-08-29` ([`envelope.py`](envelope.py)).
> **Data:** 3,434,113 RPC-sourced swaps, 2026-05-01 → 2026-08-28, 100% hourly coverage.
> **Engine:** builds on [`gate1/`](../gate1/REPORT.md); `gate1/engine/` was not modified.

**Verdict: REFUTED.** The clause that fired is the pre-registered one — *"no arm
reaches ≥ $0/day even under the optimistic envelope"*. Over 119 days on
ETH/USDC 0.05%, every fixed-width always-in rule from ±0.20% to ±8.33% loses
money at every point of the hedge envelope, in every one of the four monthly
sub-windows. The best arm, W160 (±8.33%), nets **−$0.890/day** centrally
(−$0.811 optimistic, −$1.174 pessimistic) against a target of **+$0.389/day**.
That is 28 arm-months, zero of them positive.

The mechanism is not turnover. **LP fees never cover the gamma the hedge leaves
behind**, before a single dollar of execution cost is charged: fees/gamma runs
0.65–0.97 across every arm. Turnover then decides how much worse it gets, which
is why the frontier is monotone in width and its limit is `always_cash` at
$0.00/day. Per the pre-registration this routes to **H-pool screening and the
structural conversation, not to a retrain** — item F's acceptance bar cannot be
"beat this arm through this engine", because there is no arm to beat.

---

## 1 — The frontier

$/day, full 119-day window, LP notional held constant at $1,015 (see §6).

| Arm | ±% | recenters | optimistic | central | pessimistic |
|---|---:|---:|---:|---:|---:|
| `always_in_w4` | ±0.200% | 13,967 | −46.389 | −49.131 | −59.025 |
| `always_in_w6` | ±0.300% | 7,191 | −28.975 | −30.526 | −36.124 |
| `always_in_w10` | ±0.501% | 2,941 | −16.944 | −17.897 | −21.335 |
| `always_in_w20` | ±1.005% | 853 | −9.044 | −9.597 | −11.594 |
| `always_in_w40` | ±2.020% | 243 | −4.674 | −4.994 | −6.148 |
| `always_in_w80` | ±4.081% | 51 | −1.890 | −2.047 | −2.613 |
| `always_in_w160` | ±8.328% | 13 | −0.811 | −0.890 | −1.174 |
| `always_cash` | — | 0 | +0.000 | +0.000 | +0.000 |

**Read the monotonicity carefully.** "Wider is better" here does not point at a
good width — it points at the exit. As width grows the position converges on a
50/50 basket with a short against its ETH half, fee income falls toward zero,
and the strategy degenerates into a funding-carry trade. W160 already earns only
$1.757/day of fees and $0.092/day of funding. The frontier's argmax over an
unbounded width axis is `always_cash`, and `always_cash` is the zero line.

Monthly, central envelope ($/day). Every cell is negative:

| Arm | 2026-05 | 2026-06 | 2026-07 | 2026-08 | full window |
|---|---:|---:|---:|---:|---:|
| `always_in_w4` | −29.148 | −81.436 | −43.815 | −42.283 | **−49.131** |
| `always_in_w6` | −17.676 | −47.241 | −30.588 | −26.637 | **−30.526** |
| `always_in_w10` | −9.537 | −28.238 | −19.621 | −14.026 | **−17.897** |
| `always_in_w20` | −4.873 | −13.422 | −12.478 | −7.463 | **−9.597** |
| `always_in_w40` | −2.571 | −7.140 | −6.684 | −3.449 | **−4.994** |
| `always_in_w80` | −1.180 | −3.809 | −1.255 | −1.996 | **−2.047** |
| `always_in_w160` | −0.532 | −1.704 | −0.365 | −0.997 | **−0.890** |
| `always_cash` | +0.000 | +0.000 | +0.000 | +0.000 | **+0.000** |

The optimistic-envelope monthly table is in
[`out/lag0h_rh1h/tables.md`](out/lag0h_rh1h/tables.md); no cell in it is
positive either. June is the worst month for every arm and is also the
highest-volume month (1,405,733 swaps against May's 575,631) — more volume means
more fees *and* more realized variance, and the second wins.

## 2 — Why: fees against gamma

| Arm | LP fees $/day | hedged gamma $/day | fees/gamma | on-chain $/day | HPL central $/day | funding $/day | net central $/day | breakeven fee × |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `always_in_w4` | +66.721 | −69.169 | 0.965 | −40.076 | −6.698 | +0.092 | **−49.131** | 1.74× |
| `always_in_w6` | +45.038 | −51.866 | 0.868 | −20.004 | −3.790 | +0.095 | **−30.526** | 1.68× |
| `always_in_w10` | +27.269 | −35.006 | 0.779 | −7.929 | −2.327 | +0.097 | **−17.897** | 1.66× |
| `always_in_w20` | +13.738 | −19.846 | 0.692 | −2.232 | −1.352 | +0.095 | **−9.597** | 1.70× |
| `always_in_w40` | +6.908 | −10.587 | 0.652 | −0.626 | −0.781 | +0.093 | **−4.994** | 1.72× |
| `always_in_w80` | +3.480 | −5.104 | 0.682 | −0.133 | −0.383 | +0.093 | **−2.047** | 1.59× |
| `always_in_w160` | +1.757 | −2.510 | 0.700 | −0.036 | −0.193 | +0.092 | **−0.890** | 1.51× |

**Hedged gamma** is `lp_value_change + hedge_price_pnl`: what the delta hedge
leaves behind after it cancels the first-order exposure. It is the right cost
line for this strategy, and crystallized IL is not — IL is measured against a
HODL basket nobody here holds. The two are close but not identical (the full IL
and basket-delta ledger is in the cost-attribution section of
[`out/lag0h_rh1h/tables.md`](out/lag0h_rh1h/tables.md); the deliverable's
requested fee/IL ratio runs 0.635–0.968 and tells the same story).

The mechanism is Itô, not a modelling artifact. For a position hedged by
shorting `a0(P) = ∂V/∂P`,

    V(P_T) − V(P_0) − ∫ a0 dP  =  ½ ∫ V''(P) d⟨P⟩

and `V'' < 0` for every LP range, so the hedged price P&L is a loss proportional
to realized variance. Because quadratic variation is the same at any sampling
frequency, **hedging more often does not buy the gamma back** — it only buys
lower tracking variance at higher execution cost. The recenter-only sensitivity
demonstrates this directly: W160's gamma moves from −2.510 to −2.338 $/day
(−7%) while its HPL execution collapses from −0.193 to −0.004 $/day (−98%).
The verdict therefore does not rest on my choice of hedge cadence.

**The breakeven column is the actionable number.** It is the multiple by which
this pool would have had to pay the position more, everything else held fixed,
for the arm to reach $0/day. It sits at **1.51–1.74× across every arm** — and
1.30–1.69× under recenter-only rehedging. A shortfall that is near-constant
across a 40× range of widths is a property of the venue, not of the rule: on
this pool, over these four months, the 0.05% tier did not pay enough fee revenue
per unit of realized variance for a delta-hedged LP to clear zero. That is the
H-pool question, and it is what the REFUTED branch was pre-registered to route to.

## 3 — Turnover, and the pool share the counterfactual assumes

| Arm | recenters | /day | swapped notional | rehedge notional | ×capital/day | implied pool share |
|---|---:|---:|---:|---:|---:|---:|
| `always_in_w4` | 13,967 | 117.37 | $8,104,518 | $2,373,228 | 19.65× | 0.3984% |
| `always_in_w6` | 7,191 | 60.43 | $4,027,401 | $1,342,660 | 11.12× | 0.2663% |
| `always_in_w10` | 2,941 | 24.71 | $1,588,887 | $824,618 | 6.83× | 0.1601% |
| `always_in_w20` | 853 | 7.17 | $445,039 | $479,022 | 3.97× | 0.0803% |
| `always_in_w40` | 243 | 2.04 | $124,461 | $276,769 | 2.29× | 0.0403% |
| `always_in_w80` | 51 | 0.43 | $26,295 | $135,777 | 1.12× | 0.0203% |
| `always_in_w160` | 13 | 0.11 | $7,067 | $68,296 | 0.57× | 0.0102% |

W4 recenters 117 times a day and turns over 19.65× its capital daily on the
hedge leg alone. The implied pool share — back-solved from the fees the model
credited, `fees / (volume_in_range × 3.75 bps)` — peaks at 0.40%, so no arm is
assuming a position large enough to move the pool it is priced against.

## 4 — Data coverage

RPC-sourced only. Issue Y forbids the B2 path and the E001 `_data` CSV, and §5
shows why that mattered.

| Month | Window (UTC) | Blocks | Swaps | Hours | Coverage | T1 tiling | T3 refetch | T5 ts err (s) | sha256 |
|---|---|---|---:|---:|---:|---|---|---:|---|
| 2026-05 | 05-01 → 06-01 | 458,085,624–468,748,167 | 575,631 | 744/744 | 100.000% | PASS (214 chunks) | PASS (3 probes) | max 2, med 0 | `e0241c026c86…` |
| 2026-06 | 06-01 → 07-01 | 468,748,168–479,089,705 | 1,405,733 | 720/720 | 100.000% | PASS (271 chunks) | PASS (3 probes) | max 3, med 1 | `27b323db300c…` |
| 2026-07 | 07-01 → 08-01 | 479,089,706–489,802,913 | 783,198 | 744/744 | 100.000% | PASS (221 chunks) | PASS (3 probes) | max 1, med 0 | `03e618bd3179…` |
| 2026-08 | 08-01 → 08-28 | 489,802,914–499,082,672 | 669,551 | 648/648 | 100.000% | PASS (209 chunks) | PASS (3 probes) | max 2, med 0 | `dc0ca69ce33e…` |

All four months enter the race. Four distinct months including May 2026, the
trial period. What each test does ([`coverage.py`](coverage.py), full output at
[`out/coverage.json`](out/coverage.json)):

- **T1 chunk tiling** — the `eth_getLogs` chunks recorded in each `meta.json`
  must tile `[block_from, block_to]` with no gap and no overlap. A gap is
  unqueried chain; an overlap would double-count. 915 chunks, zero of either.
- **T2 hourly floor** — every hour in every window contains swaps. Thinnest hour
  in the whole dataset: 26 swaps (August); medians 534–1,312/hour.
- **T3 independent refetch** — 12 randomly chosen 40,000-block windows re-pulled
  at a **quarter** of the original chunk span, requiring the
  `(block, log_index)` sets to match exactly. This is the direct test for the
  one way an RPC pull can silently under-count: a truncated response. 12/12
  exact, including a 9,195-swap window; zero missing, zero extra.
- **T5 interpolation** — swap timestamps are interpolated between exact block
  headers every 2,000 blocks (~8 min). Rather than assert the error is small,
  240 exact headers were re-pulled and compared: **max 3 s, median ≤1 s** across
  all four months. The hedge and funding legs run on a 1-hour grid, so this
  cannot move a P&L line.

## 5 — Issue Y, measured

Every B2 swap is present in the RPC pull (`in B2 only = 0` everywhere), so this
measures B2's gaps, not E003's. On the week containing both live trials:

| Day | RPC hours | RPC swaps | B2 hours | B2 swaps | B2 as % of chain |
|---|---:|---:|---:|---:|---:|
| 2026-05-10 | 24/24 | 15,041 | 1/24 | 119 | 0.79% |
| 2026-05-11 | 24/24 | 18,172 | 14/24 | 6,431 | 35.39% |
| 2026-05-12 | 24/24 | 17,004 | 14/24 | 5,489 | 32.28% |
| 2026-05-13 | 24/24 | 16,706 | 10/24 | 3,059 | 18.31% |
| 2026-05-14 | 24/24 | 20,811 | 11/24 | 6,243 | 30.00% |
| 2026-05-15 | 24/24 | 22,930 | 13/24 | 10,831 | 47.24% |
| 2026-05-16 | 24/24 | 11,299 | 6/24 | 4,348 | 38.48% |

A B2-built width race would have seen **18–47% of the volume that actually
traded**, and would have understated LP fee income by roughly 2–5× while getting
IL and gamma from the same truncated path. The pre-registration's refusal to
reuse E001's `_data` CSV was not caution; it was necessary.

## 6 — The notional convention, and a defect found after seeing results

Stated plainly because it was changed after a first pass: **the primary run
re-mints a constant $1,015 LP notional every cycle.** The first implementation
compounded — re-minting whatever survived — and that run drove W4's LP balance
to −$281 over 119 days, which is unphysical. A per-day average taken across a
period in which the stake reached zero is not a rate, so the primary measurement
now holds notional constant and `--notional-mode compound` is reported
separately with explicit ruin detection.

This was a defect fix, not a goalpost move, and it moves the numbers **away**
from the hypothesis: at constant notional the losing arms lose more, because the
position stays full size instead of decaying. W4 goes from −$12.832/day
(compounding, i.e. averaged partly over a dead position) to −$49.131/day. No
frozen cost constant was touched.

The compounding run ([`out/lag0h_rh1h_compound/`](out/lag0h_rh1h_compound/)) is
worth reading on its own terms, because ruin is a result:

| Arm | outcome under compounding |
|---|---|
| `always_in_w4` | **LP stake exhausted 2026-06-25**, 56 days in, after 7,323 recenters |
| `always_in_w6` | **LP stake exhausted 2026-08-19**, 110 days in, after 6,152 recenters |
| W10 and wider | survive the window, declining throughout |

## 7 — Sensitivities

Each holds the policy identical across arms, so none tilts the width comparison;
each could move the absolute level, which is what the decision rule tests. Best
arm (W160) central $/day, and the verdict in every case:

| Run | W160 $/day | W10 $/day | verdict |
|---|---:|---:|---|
| `lag0h_rh1h` — pre-registered | −0.890 | −17.897 | REFUTED |
| `lag1h_rh1h` — 1h decision loop | −0.844 | −9.253 | REFUTED |
| `lag0h_rh4h` — 4-hourly rehedge | −0.762 | −16.142 | REFUTED |
| `lag0h_rhrec` — rehedge only at recenters | −0.522 | −15.382 | REFUTED |

The 1-hour decision-loop run is the most realistic of the four for a bot that
cannot act mid-hour: it holds a breach until the next hour boundary and
recenters only if the price is still outside. It cuts W10's recenters from 2,941
to 715 and its loss from −$17.897 to −$9.253/day — a large improvement that
still does not reach zero, and the improvement is *hysteresis*, which is
H-frequency's question, not H-width's.

## 8 — What was replayed, what was modelled, what is unknown

| Line | Source | Status |
|---|---|---|
| Swap stream | `eth_getLogs`, whole months | replayed |
| LP fees | `gate1/engine/fee_engine.accrue_fees`, unmodified | closed form over replayed swaps, protocol-fee correct (E002 F1) |
| Position value, ETH delta, IL | `gate1/engine/il_ledger`, `harness` | closed form |
| Funding | recorded hourly HL ETH rates, 0 missing over 2,855 hours | replayed |
| On-chain cost | `gate1/engine/cost_model.onchain_cost`, unmodified | modelled |
| Hedge execution cost | three-point envelope | modelled as a **bound** |
| Hedge ratio | short the LP's ETH delta | **not varied** across arms or envelope points |

The envelope, all three points derived from the frozen constants plus published
measurements ([`envelope.py`](envelope.py) carries the provenance of each):

| Point | maker share (notional) | fee bps | slippage bps | chase bps | total bps |
|---|---:|---:|---:|---:|---:|
| optimistic | 95.00% | 1.584 | 0.4 | 0.0 | **1.984** |
| central | 64.63% (E002 F5) | 2.459 | 0.9 | 0.0 | **3.359** |
| pessimistic | 0.00% (all taker) | 4.320 | 2.0 | 2.0 | **8.320** |

The central maker share is the **notional-weighted** 64.63%, not the
count-weighted 86.06% — E002's finding F5, and a contract test asserts E003 is
not using the trap value. The LP path and rehedge-notional path are simulated
once per arm and priced three ways afterwards, so no envelope point can change
behaviour.

**What this does not answer.**

- **Dwell, hysteresis, deadbands.** Out of scope by pre-registration
  (H-frequency). The narrow arms here therefore carry an *upper bound* on
  turnover cost, and §7 shows the bound is loose — a 1-hour loop nearly halves
  W10's loss.
- **Placement behaviour.** `MaxOrderAge`, ALO policy and ramp parameters sit
  inside the unsimulatable region (04-backtest-design.md §4.5). The envelope
  bounds them; it does not answer them.
- **Regime.** One pool, one market, four months. June's volume spike dominates
  the full-window average, and the monthly table is there so that is visible
  rather than hidden.
- **The shipped model.** No DQN arm — E001 settled that, and mode C is a rule.
- **Basket-delta reconciliation** (E002 §3.3) is still open. E003 does not
  depend on it: hedged gamma is computed from the position-value path directly,
  never from report 01's delta-luck figures.
- **Adverse selection / MEV** is not modelled. The fee credit assumes the
  position earns its liquidity share of every in-range swap, which is what V3
  pays but is an upper bound on what a passive LP nets against informed flow.
  This biases the result *toward* the hypothesis, and it still failed.

## 9 — Validation

- **Contracts** ([`tests/test_e003_contracts.py`](tests/test_e003_contracts.py)) —
  34 assertions, all pass. Width mapping matches the harness's
  `compute_lp_range_from_width` for every arm and reproduces T5's recorded
  `-198970..-198870` mint as exactly W10; every frozen constant matches
  `gate1-2026-08-29` and the module resolves inside `gate1/engine/`;
  `onchain_cost` reproduces T5's audited $5.1049 total to $5.1212; the envelope
  is monotone and its central point equals `cost_model.hpl_fees_from_shares`.
- **Data provenance** ([`tests/test_vs_gate1_t5.py`](tests/test_vs_gate1_t5.py)) —
  E003's month-scale pull is **swap-for-swap identical** to gate1's independently
  fetched T5 window: 21,625 swaps, zero in either set alone. Feeding those swaps
  to gate1's own `accrue_fees` with gate1's own liquidity reproduces all 8 T5
  cycle fees at **0.00e+00 relative error**.
- **Accounting identity** — every arm's P&L decomposition is checked against a
  directly tracked cumulative ledger each run. Worst gap across all arms and all
  five runs: **$3.6 × 10⁻¹¹** on totals of thousands of dollars.
  `IL + basket_delta − lp_value_change` is 0.000e+00 exactly for every arm.
- **Determinism** — no RNG in the replay path; results are a pure function of
  the committed block ranges, anchors and the funding CSV. `coverage.py`'s probe
  selection is the only randomness and is seeded (42).

## 10 — Reproducing this

```bash
cd ~/developments/llaminet/research
bash backtest_model_server/e003/run_all.sh
```

Steps 3–6 of that script need no network and are a pure function of the parquets
under `e003/data/swaps/` plus the recorded funding CSV. Step 1 re-fetches chain
data (~20–50 min per month on the public `arb1.arbitrum.io/rpc`; already-assembled
months are skipped, and the fetch is phased and resumable through the endpoint's
HTTP 429s). Step 2 re-verifies it against chain.

### Layout

| Path | Purpose |
|---|---|
| [`fetch_months.py`](fetch_months.py) | Month-scale `eth_getLogs` pull, four checkpointed phases |
| [`coverage.py`](coverage.py) | T1–T5 coverage gate; writes `out/coverage.json` |
| [`envelope.py`](envelope.py) | Envelope points, width arms, capital — with provenance per number |
| [`race.py`](race.py) | The mode-C simulator |
| [`tables.py`](tables.py) | Every table above, plus the decision rule as a program |
| [`tests/`](tests/) | Contract and provenance tests |
| `out/<run>/results.json`, `frontier.csv`, `tables.md` | Per-run outputs |
| `data/swaps/<month>.{blocks,anchors,meta}.json` | Block ranges, exact header timestamps, sha256 |

The parquets themselves are gitignored (~30 MB/month) and re-derivable exactly
from the committed block ranges and anchors; `data/.gitignore` says so.

**Credentials.** None. The public `arb1.arbitrum.io/rpc` needs no key. The
Alchemy key in `model/.env` was not used — it was rate-limited during earlier
gate1 work, and the public endpoint is archive-capable back through May 2026.

## 11 — What this changes

- **H-width is answered, negatively.** There is no fixed width on this pool at
  this size that clears zero, let alone +$0.39/day. The width/PnL frontier above
  replaces every in-env width claim, including E001's (whose arms were scored in
  a training environment that overstates fee income by 33.3% and charges no
  gamma at all).
- **Item F's retrain does not unblock on this.** The pre-registered SUPPORTED
  branch would have given the retrain an acceptance bar; the REFUTED branch
  routes to H-pool screening instead. A model that picks widths cannot beat a
  frontier whose every point is below zero — the decision the model makes is not
  where the money is going.
- **The next question is the venue, not the policy.** The breakeven multiple is
  1.5–1.7× and near-constant in width, which says fee revenue per unit of
  realized variance is the binding constraint. Candidates that change that
  number: a higher fee tier, a pool whose volume/volatility ratio is higher, or
  a size at which the fixed on-chain cost stops mattering — though note that
  on-chain cost is *not* the binding term for the wide arms (W160 pays $0.036/day
  of it against a $0.89/day loss), so scaling capital alone does not fix this.
- **One number worth carrying forward:** an always-centred W10 position on this
  pool earned **$27.27/day of LP fees per $1,015 deployed** over these four
  months — roughly 980% APR gross. The strategy still loses, which is the whole
  finding. Fee APR is not the number to optimise; fees minus gamma is.
