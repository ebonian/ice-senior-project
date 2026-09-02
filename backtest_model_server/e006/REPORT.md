# E006 — the timing-oracle bound

> **Experiment:** [`loop/experiments/E006`](../../loop/experiments/E006-timing-oracle-bound.md).
> **Run date:** 2026-09-02. **Cost model:** `gate1-2026-08-29`, imported from
> [`gate1/engine/cost_model.py`](../gate1/engine/cost_model.py) unmodified.
> **Envelope:** `e003-2026-08-29` ([`../e003/envelope.py`](../e003/envelope.py)).
> **Data:** E003's exact 3,434,113-swap parquets and recorded funding CSV,
> 2026-05-01 → 2026-08-28 (119.00 days). No new fetches; `gate1/engine/` and
> `e003/` untouched.

**Verdict: SUPPORTED.** The clause that fired is the pre-registered one — *"the
stage-2 exact oracle nets ≥ +$1.56/day at some width"*. A perfect-foresight
hour-level in/out policy on ETH/USDC 0.05%, simulated exactly through E003's
own engine with full frozen costs, nets **+$6.06/day at ±0.2%** (optimistic
+$6.84, pessimistic +$3.24) and +$3.72/day at ±0.5%. Against the +$0.389/day
target, a causal model would need to capture **6.4%** of the ±0.2% ceiling.
Positive in all four months at every envelope point at ±0.2%.

The asterisk, and it is a big one: the same run's descriptive section shows the
two pre-named causal signal families — trailing realized vol and Kaufman ER —
**cannot see the hours the oracle picks** (AUC 0.45–0.53 across all six
signal×window combinations). The ceiling is tall; the named ladders to it are,
on this evidence, near-uninformative. That tension is E007's problem and is
spelled out in §5; it does not touch this verdict, which was pre-registered as
a pure ceiling measurement.

---

## 1 — The frontier

$/day over the full 119-day window (cash hours count in the denominator),
LP notional $1,015 per streak, lag1h_rh1h loop inside streaks.
`always_in` central column is E003's committed lag1h_rh1h run — the same
simulator, same bytes ([`../e003/out/lag1h_rh1h/results.json`](../e003/out/lag1h_rh1h/results.json)).

| Arm | ±% | always_in central | stage-1 UB central | **stage-2 exact central** | exact opt | exact pess | held % | streaks | capture needed |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| w4 | ±0.200% | −14.731 | +8.845 | **+6.058** | +6.840 | +3.235 | 57.9% | 435 | **6.4%** |
| w10 | ±0.501% | −9.253 | +5.734 | **+3.718** | +4.378 | +1.338 | 67.5% | 292 | 10.5% |
| w40 | ±2.020% | −3.164 | +1.294 | **+0.807** | +1.052 | −0.074 | 68.0% | 97 | 48% |
| w160 | ±8.328% | −0.844 | +0.135 | **+0.065** | +0.116 | −0.121 | 49.2% | 20 | — |

The width ordering **inverts** E003's. Always-in, wider is less bad because
turnover shrinks. Under an oracle that only holds good hours, narrow wins by a
factor of 75×: ±0.2% earns the most fees per hour when fees are worth earning,
and the oracle simply refuses the hours where its gamma bill dominates. The
REFUTED clause (stage-1 UB < +$0.78/day everywhere) missed at three of four
widths; the SUPPORTED clause (stage-2 ≥ +$1.56/day somewhere) hit at two.

Monthly, w4 exact central: **+$122.66** (May, $3.96/day) · **+$293.18** (June,
$9.77/day) · **+$185.85** (July, $6.00/day) · **+$119.23** (August, $4.42/day).
June — E003's worst month at every width — is the oracle's best: high volume is
good hours *and* bad hours, and foresight keeps only the first kind.

## 2 — Why timing works where width could not

E003's verdict rested on fees/gamma of 0.65–0.97 (0.73 for w4 under the same
lag1h loop used here): no width earns its variance bill *on average*. But the average hides an hourly mix. Freshly centered at
±0.2%, **56.9% of hours have positive payoff** (fees + funding − hedged gamma);
at ±8.3% it is 72.1% of hours (each mildly positive, too small to clear switch
costs with margin). Perfect foresight unbundles the mix:

| w4, stage-2 exact | held hours (57.9%) | E003 always-in (100%) |
|---|---:|---:|
| LP fees | +$1,863.05 | +$2,704.82 |
| hedged gamma (lp_value_change + hedge price P&L) | −$629.47 | −$3,720.64 |
| **fees / gamma** | **2.96** | 0.73 |
| on-chain cost | −$290.00 | −$462.61 |
| HPL execution (central) | −$227.42 | −$284.50 |
| funding | +$4.76 | +$9.92 |
| **net (central)** | **+$720.92** | −$1,753.00 |

Holding 58% of the hours keeps 69% of the fees and sheds **83%** of the gamma.
Mean held-hour payoff +$0.80 vs skipped −$1.89 (stage-1 valuation). The mean
round-trip switch (entry swap + 4 txs + hedge open; burn + 2 txs + swap-back +
hedge close) costs $0.76 central, and the DP pays it 435 times — ~3.7
enter/exit actions per day, on top of 361 in-streak breach recenters.

## 3 — The two stages, and how much the bound overstates

Stage 1 over-credits by construction (fresh centering every hour for free, fees
on the full $1,015 with no capital drag, a funding tick every held hour, no
in-streak recenter or rehedge charges) — that is what makes it an upper bound
on *every* timing policy, `always_in` and `always_cash` included. Stage 2
re-simulates the DP's chosen streaks exactly through
[`../e003/race.py`](../e003/race.py)'s `run_arm` — fresh mint at streak start,
the standard lag1h_rh1h loop inside (hourly rehedge, hourly funding, breach
recenters held to the next hour boundary), burn+flatten at exit, envelope
priced after the fact. Retention of the stage-1 value: 68.5% (w4), 64.8%
(w10), 62.4% (w40), 48.0% (w160). The same gap measured on the always-in path:
stage-1 values w4 always-in at −$946 vs the exact −$1,753.

Because stage 2 is an exact simulation of one realizable-with-foresight policy,
its +$6.06/day is simultaneously a *lower* bound on the true optimal timing
policy's value — the truth sits between the two stages.

## 4 — Oracle structure (descriptive)

Best arm w4, central point: 1,654/2,856 hours held in 435 streaks — mean 3.8h,
median 3h, p90 8h, max 46h. Held share is flat across months (56.0–58.6%) —
this is not one regime call, it is relentless hour-picking. 36% of gross held
payoff comes from the top decile of held hours.

What the oracle is *actually* selecting (contemporaneous, lookahead — what a
model would need to predict): the hour's own hedged gamma (AUC 0.90), its own
fees (AUC 0.66), its own intra-hour realized vol (AUC 0.37 — i.e. **held hours
are the quiet ones**, consistent with the operator's low-vol prior). The oracle
is, to first order, a next-hour-realized-variance predictor with a fee tiebreak.

## 5 — Could a causal signal have known? (descriptive, NOT the verdict)

Trailing (strictly causal, hourly closes at or before each hour's start;
first 48h excluded) — full distributions in
[`out/descriptive.json`](out/descriptive.json):

| Signal | AUC for held | held p50 | skipped p50 |
|---|---:|---:|---:|
| Kaufman ER 12h | 0.526 | 0.256 | 0.240 |
| Kaufman ER 24h | 0.501 | 0.173 | 0.178 |
| Kaufman ER 48h | 0.476 | 0.126 | 0.138 |
| trailing vol 12h | 0.452 | 0.00391 | 0.00425 |
| trailing vol 24h | 0.456 | 0.00434 | 0.00451 |
| trailing vol 48h | 0.466 | 0.00445 | 0.00486 |
| previous hour's intra-hour RV | 0.460 | 0.00096 | 0.00105 |

**No pre-named signal separates.** The strongest is ER-12h at 0.526 — barely
above coin-flip; the vol signals point the right way (held hours follow
lower-vol trails) but at 0.45–0.47 AUC. The mechanism gap is persistence: the
target (next-hour realized vol) has autocorrelation only **0.22 at lag 1**,
decaying to 0.10 by lag 6, while the signals that persist beautifully (ER-48h
ACF 0.94 at lag 1, 0.54 at lag 12) measure the wrong thing. Sideways-ness is
predictable; the hour-scale quiet the oracle harvests largely is not — at least
not by these seven statistics. This is the headwind E007 must clear, and the
capture bar it must clear it against is 6.4%.

## 6 — Validation

[`tests/test_e006_contracts.py`](tests/test_e006_contracts.py), blocking, 71
checks, all pass:

- **Frozen inputs** — cost model is `gate1-2026-08-29` resolved inside
  `gate1/engine/`; envelope is `e003-2026-08-29` resolved inside `e003/`, all
  three points bit-equal to E003's; the four arms are E003's W4/W10/W40/W160.
- **Switch-cost→∞ reproduction** — with switching forbidden the oracle's one
  streak spans the whole window, and stage 2's simulator on that streak
  reproduces E003's committed lag1h_rh1h `always_in` results **float-exact
  (`==`)**: net at all three envelope points, LP fees, and recenter counts, for
  all four arms.
- **Domination** — at every arm × envelope point, the DP value ≥ 0
  (`always_cash`) and ≥ the stage-1 always-in valuation and ≥ E003's exact
  always-in net (both are points in its feasible set).
- **Accounting identity** — every simulated streak's decomposition equals its
  directly-tracked ledger; worst gap across all 844 streaks **8.9 × 10⁻¹⁵**
  (bar: 1e-6). All selected streaks simulated (none dropped).
- **Determinism** — no RNG anywhere; the DP tie-breaks toward the incumbent
  state; results are a pure function of the committed parquets + funding CSV.

## 7 — What this does not answer

- **Whether any *realizable* model captures 6.4%.** The oracle conditions on
  the future; §5 says the obvious causal signals do not proxy it. That is
  E007's question, now with a measured bar on both sides.
- **Adverse selection / MEV** — inherited from E003: fees credit our full
  liquidity share of every in-range swap. This over-credits a passive LP
  against informed flow, and the bias is *larger* here because held hours are
  selected for high fee-per-variance. The pessimistic envelope point (+$3.24/day
  at w4) does not cover this channel.
- **Hedge ratio and placement behaviour** — not varied, per E003 §8.
- **Regime** — four months, one pool, one market. The monthly table's
  stability (§1) is the strongest internal evidence, but 2026-05→08 is one
  market.
- **Capital scaling** — untested here; E003 §3's pool-share argument applies to
  the held hours unchanged (w4 always-in implied share 0.40%).

## 8 — Reproducing this

```bash
cd ~/developments/llaminet/research
bash backtest_model_server/e006/run_all.sh   # pure local compute, ~1 minute
```

Needs E003's parquets under `e003/data/swaps/` (re-derivable exactly via
`e003/fetch_months.py` from the committed block ranges) and the recorded
funding CSV. No network otherwise.

| Path | Purpose |
|---|---|
| [`oracle.py`](oracle.py) | Stage 1 — per-hour payoffs, switch costs, O(N) two-state DP; states the upper-bound property |
| [`exact.py`](exact.py) | Stage 2 — exact re-simulation of the selected streaks through E003's `run_arm` |
| [`signals.py`](signals.py) | Descriptive — causal signals, AUC, persistence, oracle structure |
| [`tables.py`](tables.py) | Every table above + the pre-registered decision rule as a program |
| [`tests/test_e006_contracts.py`](tests/test_e006_contracts.py) | The blocking contracts of §6 |
| `out/stage1_results.json`, `out/stage1_hours_w<W>.csv` | Per-hour payoffs and DP selections |
| `out/stage2_results.json`, `out/stage2_streaks_w<W>.csv` | Exact per-streak results |
| `out/descriptive.json`, `out/tables.md` | §4–5 numbers; rendered tables + verdict |

## 9 — What this changes

- **H-timing has a real ceiling on the control pool.** E003 closed width;
  E005 found no venue; this is the first positive number the family has
  produced under full frozen costs: +$6.06/day perfect-foresight at ±0.2%,
  with 6.4% capture sufficing for target. Timing does NOT close on this pool.
- **E007 (causal-signal test) is staged, per the pre-registered SUPPORTED
  route** — but its design must answer §5 honestly: the two named families are
  nearly powerless as-is, and the thing worth predicting is next-hour realized
  variance (persistence 0.22), not trend efficiency (persistent but
  non-separating). An E007 that just thresholds ER should expect REFUTED;
  candidate features need to target short-horizon vol (e.g. intra-hour
  microstructure, time-of-day seasonality, cross-venue leading indicators) or
  accept holding longer, smoother streaks at a lower ceiling.
- **The venue decision gains a live fourth option.** The operator's three-way
  call from E005 (accept 5–7% carry venue / re-screen elsewhere / judge the
  family) now has: stay on ETH/USDC 0.05% *if and only if* E007 finds a causal
  filter clearing ~6–10% capture at ±0.2–0.5%. No capital moves on an oracle
  number (bot ADR 0008).
