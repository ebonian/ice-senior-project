# E012 — the causal vol-gate capture test: REFUTED. No pre-named gate beats holding the wide arm; the slow gates select post-hoc and the fast gate cannot pay for its own selection

**Verdict (pre-registered rule): REFUTED**, by clause 1 — no pre-named
candidate's full-window central exceeds **max(+$0.915/day, the best static
arm)**. The best frozen cell anywhere is V1 (RV-48h hysteresis) on ±8.1%
at **+$0.577/day central**, below the +$0.915/day of simply holding that
arm always-in. Every verdict-arm (±0.6%) cell is negative full-window
(best −$1.43/day); every cell's August is negative (best −$68); no cell
approaches the +$2.7397/day target. The SUPPORTED clause could not fire;
the INCONCLUSIVE zone was never entered. Applied by
[`tables12.py`](tables12.py) → [`out/decision.json`](out/decision.json).

E011's ceiling (K16) is untouched by this verdict — the +$5.79/day of
perfect-foresight structure is still there. What is refuted is the first
(and best-credentialed) causal key proposed for it: trailing-vol skip
rules at 4–24h grain, M006's pre-named set, under the E007/E008 tuning
discipline. Capital stays parked (bot ADR 0008); the venue call
escalates per PROTOCOL §7.

## 1 — Per-cell results ($/day over 118.99 days unless marked; coupled envelope o/c/p; tune = May–Jul only)

| cell | frozen cfg | tune $/d | full o / **c** / p | Aug c ($) | held % | streaks | beats own always-in full/Aug |
|---|---|---:|---|---:|---:|---:|---|
| V1 ±0.6% | n48, q.30/.95 | +3.48 | −0.05 / **−4.33** / −21.06 | −840.6 | 84.3 | 3 | Y/Y |
| V1 ±8.1% | n48, q.50/.95 | +1.95 | +0.98 / **+0.58** / −0.94 | −117.7 | 84.9 | 3 | N/N |
| V2 ±0.6% | n24, q.90, D96 | +2.87 | −1.13 / **−5.26** / −21.47 | −895.7 | 79.8 | 7 | N/Y |
| V2 ±8.1% | n24, q.90, D96 | +1.48 | +0.63 / **+0.15** / −1.67 | −125.7 | 79.8 | 7 | N/N |
| V3 ±0.6% | q.50/.95 | +3.03 | +0.05 / **−4.17** / −20.71 | −780.8 | 80.7 | 3 | Y/Y |
| V3 ±8.1% | q.50/.95 | +1.65 | +0.75 / **+0.36** / −1.08 | −115.3 | 80.7 | 3 | N/N |
| V4 ±0.6% | m4, q.30/.95 | +1.63 | +1.87 / **−1.43** / −14.26 | −326.1 | 71.8 | 20 | **Y/Y** |
| V4 ±8.1% | m4, q.30/.95 | −0.32 | −0.21 / **−0.78** / −2.99 | −68.4 | 71.8 | 20 | N/Y |
| V5 ±0.6% | λ.97, q.50/.95 | +2.95 | −0.53 / **−4.73** / −21.19 | −840.6 | 82.9 | 3 | N/Y |
| V5 ±8.1% | λ.97, q.50/.95 | +1.89 | +0.93 / **+0.53** / −0.97 | −117.4 | 82.9 | 3 | N/N |
| V6 ±0.6% | n72, q.50/.95 | +3.52 | +0.60 / **−3.79** / −20.97 | −780.8 | 84.9 | 3 | Y/Y |
| V6 ±8.1% | n48, q.50/.95 | +1.94 | +0.97 / **+0.53** / −1.13 | −122.7 | 86.5 | 3 | N/N |

Baselines (regenerated, contract-equal to E010's committed rows):
**always-in ±0.6%** +0.79 / **−4.46** / −25.00 $/day, August −$941.5;
**always-in ±8.1%** +1.38 / **+0.92** / −0.82 $/day, August −$111.3.
always_cash ≡ $0. Full grid (all 120 tune cells) in
[`out/tune_results.json`](out/tune_results.json).

## 2 — Why it failed (the part that outlives the verdict)

**(a) The tune window had nothing to teach.** Always-in on the tune slice
nets **+$4.40/day (±0.6%) and +$2.32/day (±8.1%)** — May–Jul was a
*good* season, its 37 oracle-skipped hours worth only −$194 of stage-1
damage, about one round-trip budget ($12.7 × ~13) above zero.
**0 of 120 grid cells beat same-arm always-in in tune** (91/120 were
positive — positivity was free; *gating value* was absent). The
pre-registered zero-positive framing therefore lands with a twist: the
kill is in-sample, but one level up — the family's objective, "dodge
bursts profitably", had no positive in-sample instance to tune toward.
Every frozen parameter set is a least-bad compromise, not a learned key.
M006 §2 predicted this shape (81% of dodgeable damage sits in August);
the prereg accepted it knowingly — a gate that cannot demonstrate value
on 92 days of tune was always going to face August on theory alone.

**(b) The slow gates (V1, V2, V3, V5, V6) select post-hoc.** Against the
oracle's 7 August skip episodes, their skip coverage is 0 on five of
seven — they exit around Aug 21 (after the damage) and stay out. All of
them **held through 9 of the 10 worst stage-1 hours** of the window,
including the −$230.5 hour (Aug 19 15:00 UTC). A 12–168h trailing window
cannot clear its own 95th percentile until a 1–18h burst is mostly over:
the reaction lag *is* the burst length. Their August "dodging" amounts to
−$780 to −$896 vs always-in's −$941 — they bought ~$60–160 of the $993
August prize while sacrificing 13–20% of held hours across the whole
window (June alone: V1 ±8.1% +$35 vs always-in's +$75 — false exits eat
good months). This is E008's smoothing-away-selectivity horn, measured at
the venue where smoothing had its best-ever excuse.

**(c) The fast gate (V4, prev-hour swap-RV) selects genuinely — and
still loses.** Skip coverage **6 of 7** August episodes; dodged **8 of
the 10 worst hours**; August halved (−$326 vs −$941); it beats its own
arm's always-in on both full-window (+$3.03/day improvement) and August —
**the first candidate in three falsification campaigns (E007, E008,
E012) to beat a same-arm always-in out-of-sample**. And it is still
negative everywhere: 20 streaks (~$254 of round trips), 71.8% held (a
quarter of the fee base sacrificed to false positives), full-window
central **−$1.43/day** at ±0.6% and −$0.78/day at ±8.1% (where its tune
was already negative). It captures ~30% of the oracle's *improvement*
over always-in at the verdict arm; the SUPPORTED bar needed 47% of the
ceiling itself. This is E007's fragmentation horn — at a venue where
fragmentation was supposed to be structurally affordable.

**(d) The diagnosis, named (E007/E008 inheritance).** Selection and
contiguity did not arrive together — a third time, and this time the
failure is two-horned and symmetric: at the burst timescale (M006 §2:
skips are 1–18h, not multi-day), **every trailing-vol signal is either
too slow to select or too noisy to hold**. Slow windows give contiguity
(3 streaks, 819–863h medians — longer than the oracle's 93h!) with
post-hoc selection; the 1h window gives real selection with 20-streak
fragmentation and a 28% fee sacrifice. The multi-day timescale that B6
hoped would let both arrive together turned out not to exist: what is
multi-day about the target is the *held* streaks, and always-in already
owns those for free. The gate's only earnable edge — the bursts — sits
below the reaction floor of causal trailing vol priced at ~$12.7 round
trips.

## 3 — Wick honesty (K15, mandatory)

Held-hour top-10 swap weight: V1/V2/V3/V5/V6 **1.96–2.19%** vs 1.73%
full-window — the slow gates' held sets are slightly *more*
wick-concentrated than the pool (they hold through dislocations;
consistent with (b)). V4: **1.61%**, below the pool (it dodges
dislocation hours; consistent with (c)). No positive claim rests on any
held set, so K15 has nothing to disqualify — recorded for the pattern
library.

## 4 — Funding substitution (F2)

Not run — pre-registered to run only on SUPPORTED cells, and there are
none. Recorded in [`out/checks_results.json`](out/checks_results.json).

## 5 — Validation

**66 blocking contracts, all PASS**
([`tests/test_e012_contracts.py`](tests/test_e012_contracts.py)):
committed-parquet sha256 4/4; close-series arm-invariance; signal
definitions equal e006's; causality-by-truncation exact on every signal
and mask prefix; grain/dwell properties; always-cash ≡ $0; E010 race-row
reproduction float-consistent at all 3 coupled points × 2 arms; E011
oracle-mask reproduction float-consistent (net central $688.347068 vs
$688.347068 at ±0.6%); tuning-isolation raise verified; freeze
completeness 12/12; determinism on re-evaluated tune and final cells;
accounting gaps ≤ 5.5e-12.

**Deviation (recorded per prereg discipline):** the prereg wrote the
baseline contract as "the all-ones mask ≡ E010's committed rows". That
form is unsatisfiable to float precision simultaneously with the
oracle-mask contract, because the two committed artifacts anchor the
window head differently (E010 race rows swap-anchored at ts[0]; E011
stage-2 streaks hour-anchored at hs[0]). Implemented as E011's own
spanning-streak contract (swap-anchored, float-exact vs E010) plus a
bound check on the mask path's head sliver (≤ $0.27 and 0.87h across all
6 arm×point cells). Gate cells stay hour-anchored — identical to how the
ceiling was priced. No number in §1 moves by more than the sliver bound
under either choice.

## 6 — Reproducing

| Path | Purpose |
|---|---|
| [`common12.py`](common12.py) | E011 surface by import; signals; gate-mask engine; guarded evaluator |
| [`gates12.py`](gates12.py) | M006 §4 candidate registry, grids verbatim |
| [`tune12.py`](tune12.py) | tune loop (checkpoint + cache), `--freeze` |
| [`final12.py`](final12.py) | frozen finals, 3 points; refuses unfrozen |
| [`checks12.py`](checks12.py) | K15 wick, streaks, tune-baseline framing, August autopsy |
| [`tables12.py`](tables12.py) | decision rule as a program; tables |

Runbook: `tests pre` → `tests repro` → `tests oracle` → `tune12.py` →
`tune12.py --freeze` → `final12.py` → `checks12.py` → `tables12.py` →
`tests all` (66 PASS). Data: E010's committed parquets (sha-verified) and
E011's committed stage-1 CSVs; **no new fetches**. Deterministic, no RNG.
Total compute ≈ 3 minutes.

## 7 — What this does not answer

- **Whether a non-vol causal key exists.** Only trailing-vol shapes were
  pre-named (M006's reading of E011 §5). The AUC-0.85 lead was real and
  is now explained: it is mostly *within-episode* separation, monetizable
  only by a rule faster than the bursts themselves. Order-flow,
  liquidity-migration, or cross-venue leads were not in the set (M006
  excluded them with reasons); nothing here tests them.
- **Whether V4's shape could be repaired.** Its selection is genuine
  (6/7 episodes, causally); its losses are fee-sacrifice and round trips.
  A cost-aware exit (skip only when expected burst damage > round trip)
  is a *new* candidate family, not a tuned V4 — it would need its own
  memo and prereg. The measured bind it must beat: V4 bought $3.03/day of
  improvement and needed $2.35/day more to reach even the static bar.
- **The grids are the grids.** 60 pre-named configs per arm; a finer
  q_out lattice or asymmetric grains were not explored, by design. The
  monotone patterns across the grids (q_out=0.95 dominating everywhere;
  every V4 wide-arm cell negative in tune) argue the surfaces are smooth,
  but that is an argument, not a measurement.
- **One window, one venue.** 119 days, one August. The tune-window
  emptiness (§2a) is a property of this window's seasonality, not a law;
  a window with tunable winters could re-open the family — at the cost of
  a new prereg against K17.
- **K9 (JIT/adverse selection) remains unpriced** — moot for these
  negatives (real costs only deepen them), binding for any future
  positive.
- **The ceiling itself (K16) stands.** This experiment prices one causal
  family against it, not the ceiling's existence.
