# E012 — A pre-named causal vol gate captures enough of the LINK/WETH 0.30% ceiling to clear the 10% APR bar

**Family:** H-timing (LINK venue, causal — the capture test for E011's ceiling).
**Card:** [B6](../../discovery/BACKLOG.md) · **Memo:** [M006](../../discovery/memos/M006-vol-gated-capture-of-the-link-ceiling.md)
(committed 2931a1d, before this file; E012 tests **only** its §4 pre-named
candidates V1–V6 on the grids frozen there).
**Operator context:** go 2026-09-03 — capital is parked on this verdict; the
three-way venue call (wstETH carry / LINK fee-edge / both) waits for it.

## Pre-registration (write BEFORE running)

**Hypothesis** — On mainnet LINK/WETH 0.30%
(`0xa6cc3c2531fdaa6ae1a3ca84c2855806728693e8`), some pre-named causal
trailing-vol gate (M006 §4: hysteresis / dwell / HAR-blend shapes at 4h or
24h decision grain, ≤ 3 params, grids pre-registered) — deciding **in/out
only**, width fixed per arm — captures enough of E011's measured ceiling
(+$5.79/day central at ±0.6%; +$2.02 at ±8.1%; capture bar 47%) to net
**≥ +$2.7397/day central full-window** through the frozen stack, survive
held-out August, and beat the same-arm always-in. This is card B6's claim,
under the full E007/E008 discipline that refuted the last two causal
families.

**The one variable** — the causal gating rule (which hours are held), vs
the named baselines `always_in` (E010's committed race rows, per arm) and
`always_cash` ($0.00 exactly), with E011's oracle as the ceiling
reference. Everything else frozen at E010/E011's values, byte-identical:

- **Venue/engine identical to E011**: `e011/common11.py`'s import surface
  unmodified — e005 `run_arm` via race10's R5, cost model
  **`gate1-2026-08-29`**, HPL envelope **`e003-2026-08-29`**, E010's
  measured mainnet gas envelope **coupled by point name**
  ($0.049/$0.08339/$0.368 per tx), share-aware fee credit at the $10k
  reference (LP notional $7,147.89), constant re-mint, lag1h_rh1h loop
  while held, per-leg two-short hedge.
- **Window**: 2026-05-01 → 2026-08-28 (exclusive), E010's committed
  parquets, **sha256 re-verified against committed meta before any run**.
  No new fetches of any kind.
- **Arms — two, pre-named**: `arm_0.1pct_0.2pct_0.5pct` (±0.60%, the
  E011 verdict arm) and `arm_8.3pct` (±8.11%, the robust arm whose
  always-in is the best static baseline +$0.915/day). ±1.8% is
  **excluded** (pre-named): it adds compute without touching either
  decision clause — its oracle sits between the two raced arms on every
  measure. The gate decides in/out only; width never changes within an
  arm (one variable).
- **Evaluation is stage-2 exact only**: a candidate's mask → maximal held
  runs → `exact11.run_streaks` (fresh mint at run start, burn + swap-back
  + hedge flatten at exit, cash outside), per arm, re-run under each
  coupled gas point and priced at its same-named HPL point; net via
  `common11.net_usd`; $/day over the full 118.99-day window. **No stage-1
  shortcut anywhere — tuning included.**
- **Signals** from committed data only: hourly USD closes `p0·u0` from
  E011's committed `stage1_hours_*.csv` and intra-hour swap-RV from the
  committed swap parquets (`signals11.py`'s construction). All signal
  definitions, grain semantics (state changes only at UTC boundaries
  divisible by g), warm-up/undefined → IN, initial state IN, and
  hysteresis semantics are fixed in M006 §4's common block.

**Candidates and grids (M006 §4, restated — the complete set; nothing else
may be evaluated):**

| id | rule | grain | params × grid | configs/arm |
|---|---|---|---|---|
| V1 | trailing-RV hysteresis | 4h | n∈{12,24,48} × q_in∈{.30,.50} × q_out∈{.80,.95} | 12 |
| V2 | RV threshold + min-dwell | 4h | n∈{12,24} × q∈{.70,.90} × D∈{24,48,96}h | 12 |
| V3 | HAR blend (z-mean RV24/72/168) hysteresis | 24h | q_in∈{.30,.50} × q_out∈{.80,.95} | 4 |
| V4 | prev-hour swap-RV (median of last m) hysteresis | 4h | m∈{1,4} × q_in∈{.30,.50} × q_out∈{.80,.95} | 8 |
| V5 | EWMA-RV hysteresis | 4h | λ∈{.97,.99,.995} × q_in∈{.30,.50} × q_out∈{.80,.95} | 12 |
| V6 | trailing-RV hysteresis | 24h | n∈{24,48,72} × q_in∈{.30,.50} × q_out∈{.80,.95} | 12 |

60 configs × 2 arms = 120 tune cells. Thresholds are quantiles of the
signal over the tune window's valid hours, converted once to absolute
values and frozen; August enters no quantile, no mean, no sd.

**Tuning protocol (blocking isolation — E007's pattern):**

1. **Tune on 2026-05-01 → 2026-08-01 (exclusive) ONLY.** Every grid point
   is evaluated stage-2 exact on the tune slice (a held run open at the
   tune boundary is force-exited there and charged the full exit cost —
   identical convention for every config). The tuner **raises** if any
   simulation request crosses the 2026-08-01T00:00Z epoch.
2. Best config per candidate × arm by tune central net $/day → all
   **12 cells frozen to `out/params_frozen.json`** (absolute thresholds,
   all params, tune numbers) in one write.
3. The final phase **refuses to run** until that file exists and contains
   all 12 cells; only then are the frozen rules evaluated on the full
   window (which contains August) at all three coupled points.
4. **Every grid point's tune result is reported** in the artifacts — the
   zero-positive-tune-configs framing is pre-committed: if 0 of 120 cells
   are positive in tune, the kill is in-sample and no overfit story
   applies.

**August accounting convention (pre-named):** monthly nets use the
engine's calendar-month buckets from the full-window frozen run — costs
land in the month they are booked, so a streak entered in July that spans
August books its entry in July (E011's monthly-table convention).
`always_in` August uses the same buckets from the baseline-reproduction
run. "August central" below means the 2026-08 bucket net at the coupled
central point.

**Blocking contracts (tests first — `tests/test_e012_contracts.py`; the
run refuses to proceed on any failure):**

- **Parquet integrity**: sha256 of E010's committed LINK/WETH parquets
  match committed meta (4/4) before anything loads.
- **Baseline reproduction**: the all-ones mask per arm through THIS
  evaluator ≡ one unbroken streak ≡ E010's committed
  `lag1h_rh1h_cap10000_gas-{opt,central,pess}` rows, float-consistent
  (≤ 1e-9 rel / 1e-6 abs on every Bucket field and per-day number), at
  all three coupled points, both arms.
- **always_cash ≡ $0.00** exactly at every point.
- **Oracle-mask reproduction**: E011's committed `held_central` mask per
  arm through this evaluator returns E011's committed
  `stage2_results.json` numbers (net and per-day, all three points)
  float-consistently — the evaluator that judges the gate is the one that
  priced the ceiling.
- **Causality by truncation**: for every signal series, the decision at
  boundary t recomputed from data truncated at t equals the full-series
  decision — exact equality at sampled boundaries (≥ 200 per signal,
  including every state-change boundary of every frozen rule).
- **Grain/dwell property**: every generated mask changes state only at
  its rule's allowed boundaries; V2 masks never violate D.
- **Tuning isolation**: the tuner raises on any row ≥ 2026-08-01T00:00Z;
  the final phase raises if `params_frozen.json` is absent or incomplete.
- **Determinism**: re-running tune on a sampled config and the frozen
  finals reproduces byte-identical JSON.
- **Accounting identity**: `lp_value_abs_gap_usd` ≤ 1e-6 per simulated
  streak, every run.

**Decision rule** (coupled central decides; all three points reported):

- **SUPPORTED** — some pre-named candidate, with params frozen from the
  tune window alone, achieves **full-window central ≥ +$2.7397/day**
  (10% APR at $10k) AND **held-out August central > $0** AND beats the
  **same-arm always-in** on both full-window and August central.
- **REFUTED** — no pre-named candidate's full-window central exceeds
  **max(+$0.915/day, the best always-in arm raced here)** — i.e. no gate
  beats simply holding the wide arm — OR every candidate clearing the
  +$2.7397/day target fails August (≤ $0 central).
- **INCONCLUSIVE** — anything else (e.g. a candidate beats +$0.915/day
  and always-in but lands under the 10% bar, or clears full-window while
  August sits at exactly $0); state exactly what would disambiguate.

**Report alongside (mandatory, non-deciding):**

- **Wick honesty (K15)** on every frozen candidate's held hours: top-10
  swap share of held-hour fee weight vs the 1.73% full-window reference —
  a gate that monetizes by holding through wicks is named as such.
- **Funding-substitution (F2-style)** on any SUPPORTED cell: window rates
  → trailing-12m rates on held-hour leg notionals; the adjusted number
  must be reported next to the headline.
- **Streak-length distributions** per frozen candidate vs the same-arm
  oracle's (13–14 streaks, median ~90h): does the gate hold streaks the
  way the ceiling does, or fragment / blur?
- **Round-trip counts and total switch cost** per frozen candidate (the
  fragmentation measurement, K7's number at this venue).
- **The E007/E008 failure-mode diagnosis, named**: if the best candidate
  selects well but fragments → E007's mode; if it holds streaks by
  smoothing away selectivity (held-frac → 1, no August dodging) → E008's
  mode; if selection and contiguity finally arrive together, say so with
  the numbers. The diagnosis is as durable as the verdict.
- Per-candidate×arm tables: tune / full-window / August, central +
  optimistic + pessimistic, held %, streaks, params.

**Inheritance stated up front (E007/E008, K7/K11; M006 §2):** two causal
families died on the control with excellent-looking selection numbers.
This venue's descriptive lead (skip-AUC 0.85, quartile separation) is
better than anything the control offered, AND 81% of the dodgeable damage
sits in the held-out month — the test cannot be won in-sample. Every
positive number restates **K9**: full-share fee credit, JIT/MEV
unmodelled, all positives are upper bounds; the **pessimistic coupled
point already eats the ceiling** (−$13.51/day at ±0.6%) and travels with
any positive result. **No capital moves on this verdict** (bot ADR 0008);
PROTOCOL §7 escalation follows it either way.

**Abort criteria** — baseline or oracle-mask reproduction outside
tolerance (report the discrepancy, stop); free disk < 2 GB at any
checkpoint; compute > 10× the estimate (tune ≈ 120 exact cells at
seconds-to-a-minute each; full run well under ~3 h). Artifacts under
`backtest_model_server/e012/` (`out/` checkpointed per candidate;
every grid point's result committed).

## Result

*(to be filled after the run)*

## Verdict

*(to be filled after the run)*

## Critique

*(to be filled after the run)*
