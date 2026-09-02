#!/usr/bin/env python3
"""E008 blocking contracts (pre-registered in loop/experiments/E008).

    nix develop .#gate1 -c python backtest_model_server/e008/tests/test_e008_contracts.py [N ...]

With no arguments all seven contracts run; passing numbers runs a subset
(chunkability for foreground-session budgets). ALL must pass before any
E008 result is quoted.

1. Reproduction: always_in through E008's evaluator == E003's committed
   lag1h_rh1h always_in, float-exact, w4 + w10, all three envelope points,
   LP fees, recenter counts. Run UNCACHED (fresh in-memory cache).
2. Zero: always_cash nets exactly $0 with zero streaks.
3. Oracle: the E006 oracle mask (held_central) through E008's evaluator
   returns E006's committed stage-2 numbers (+$6.058/day w4, +$3.718/day
   w10 central).
4. Causality: S1/S3/S4/S5 masks invariant to scrambled August payoffs
   (their only realized-data input is the tune-window calendar);
   S1/S2/S3/S4 decisions at sampled August boundaries equal a truncated
   re-run; S2's score recomputed from truncated payoff data matches; S6's
   decision at sampled boundaries recomputed from a truncated residual
   EWMA + the horizon DP matches the full run. S5/S6 optimizers consume
   only forecast series (asserted by scramble + step recompute).
5. Tuning isolation: tune_candidate raises on held-out rows; the final
   phase's freeze gate raises while any tune file is missing.
6. Determinism: signals and masks rebuilt from scratch are identical;
   grid enumerations are the frozen ordered lists.
7. Accounting identity: every cached streak's ledger gap <= 1e-6 (also
   asserted inside the evaluator on every use, cached or not).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

E008 = Path(__file__).resolve().parent.parent
BMS = E008.parent
for p in (BMS / "gate1", BMS / "e003", BMS / "e006", BMS / "e007", E008):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
import race                    # noqa: E402
import causal_signals as CS    # noqa: E402
import evaluate as EV          # noqa: E402
import streak_rules as SR      # noqa: E402
from run_e008 import tune_candidate, assert_all_frozen  # noqa: E402

N_CHECKS = 0
FAILED = []


def check(name: str, ok: bool, detail: str = "") -> None:
    global N_CHECKS
    N_CHECKS += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        FAILED.append(name)


ONLY = {int(a) for a in sys.argv[1:]} or set(range(1, 8))

swaps = race.load_swaps("2026-05-01", "2026-08-28")
funding = race.load_funding()
sigs = {w: SR.build_signals(w) for w in (4, 10)}

if ONLY & {1, 2}:
    print("contract 1+2: always_in reproduction (uncached), always_cash zero")
    e003_by_arm = {a["arm"]: a for a in json.loads(
        (BMS / "e003" / "out" / "lag1h_rh1h" / "results.json").read_text())["arms"]}
    for w in (4, 10):
        hs = sigs[w]["hs"]
        fresh = SR.E008Cache(w)
        fresh.data, fresh.dirty = {}, 0          # contract 1 runs uncached
        r_in = EV.evaluate_mask(np.ones(len(hs), bool), hs, swaps, funding, fresh)
        exp = e003_by_arm[f"always_in_w{w}"]["total"]
        for pt in ("optimistic", "central", "pessimistic"):
            got, want = EV.net_usd(r_in["total"], pt), exp[f"net_usd_{pt}"]
            check(f"w{w} always_in net_{pt} exact", got == want,
                  f"got {got!r} want {want!r}")
        check(f"w{w} always_in n_recenters exact",
              r_in["total"]["n_recenters"] == exp["n_recenters"])
        check(f"w{w} always_in lp_fees exact",
              r_in["total"]["lp_fees_usd"] == exp["lp_fees_usd"])
        check(f"w{w} always_in is one streak", r_in["n_streaks"] == 1)
        r_cash = EV.evaluate_mask(np.zeros(len(hs), bool), hs, swaps, funding,
                                  fresh)
        check(f"w{w} always_cash zero",
              EV.net_usd(r_cash["total"], "central") == 0.0
              and r_cash["n_streaks"] == 0)

if 3 in ONLY:
    print("contract 3: E006 oracle mask through E008's evaluator")
    stage2 = json.loads((BMS / "e006" / "out" / "stage2_results.json").read_text())
    days = stage2["window"]["days"]
    for w, quoted in ((4, 6.058), (10, 3.718)):
        cache = SR.E008Cache(w)
        held = sigs[w]["hours"]["held_central"].to_numpy(bool)
        r = EV.evaluate_mask(held, sigs[w]["hs"], swaps, funding, cache)
        got = EV.net_usd(r["total"], "central") / days
        want = stage2["arms"][f"w{w}"]["points"]["central"]["per_day_usd"]
        cache.save()
        check(f"w{w} oracle mask == committed stage-2 central/day",
              abs(got - want) <= 1e-9, f"got {got!r} want {want!r}")
        check(f"w{w} oracle mask quotes as +${quoted}/day",
              round(got, 3) == quoted, f"{got:.3f}")

if 4 in ONLY:
    print("contract 4: causality")
    # (a) scrambled-August invariance for the calendar-only candidates
    for w in (4,):
        hours = CS.load_hours(w)
        hs = hours["hour_epoch"].to_numpy(np.int64)
        payoff = hours["payoff_usd"].to_numpy(np.float64)
        scr = payoff.copy()
        scr[hs >= SR.AUG1_EPOCH] = 1e9
        sig_scr = SR.build_signals(w, payoff_override=scr)
        for cand, cfg in (("s1", {"kappa": 8, "hi_pct": 70, "lo_pct": 30}),
                          ("s3", {"theta_pct": 50, "D": 4}),
                          ("s4", {"theta_pct": 50, "M": 2}),
                          ("s5", {"kappa": 0, "c": 1.0}),
                          ("s5", {"kappa": 32, "c": 4.0})):
            m0 = SR.make_mask(cand, cfg, sigs[w])
            m1 = SR.make_mask(cand, cfg, sig_scr)
            check(f"{cand} {cfg} mask invariant to scrambled August",
                  bool(np.array_equal(m0, m1)))
    # (b) truncated re-run equality at sampled boundaries (state machines)
    w = 4
    hs4 = sigs[w]["hs"]
    aug_idx = np.where(hs4 >= SR.AUG1_EPOCH)[0]
    SAMPLE = [int(aug_idx[0]), int(aug_idx[len(aug_idx) // 2]),
              int(aug_idx[-1]), 500, 2000]
    for cand, cfg in (("s1", {"kappa": 0, "hi_pct": 80, "lo_pct": 40}),
                      ("s2", {"q_hi": 0.7, "q_lo": 0.3}),
                      ("s3", {"theta_pct": 70, "D": 6}),
                      ("s4", {"theta_pct": 70, "M": 3})):
        full = SR.make_mask(cand, cfg, sigs[w])
        ok = all(SR.make_mask(cand, cfg, sigs[w], n=t + 1)[t] == full[t]
                 for t in SAMPLE)
        check(f"{cand} truncated re-run equals full at sampled boundaries", ok)
    # (c) S2 score from truncated payoff data (August boundaries only —
    # tune-window ECDFs and cells are the registered estimation convention)
    payoff4 = sigs[w]["payoff"]
    cal0 = sigs[w]["cal"][SR.CAL_KAPPA_INHERITED]
    F_pay = SR.tune_ecdf(sigs[w]["pay"][sigs[w]["tune"]])
    F_cal = SR.tune_ecdf(cal0[sigs[w]["tune"]])
    ok2 = True
    for t in [int(aug_idx[0]), int(aug_idx[-1])]:
        pay_t = CS.ewma_shift1(payoff4[:t + 1], SR.PAY_HALFLIFE)[t]
        s_t = min(F_pay(np.array([pay_t]))[0], F_cal(np.array([cal0[t]]))[0])
        ok2 &= s_t == sigs[w]["score"][t]
    check("s2 score recomputed from truncated data matches", bool(ok2))
    # (d) S6 step recompute from truncated residual series
    lam, K = 16, 12
    cfg6 = {"lam": lam, "K": K}
    full6 = SR.make_mask("s6", cfg6, sigs[w])
    consts = sigs[w]["consts"]
    phi = 2.0 ** (-1.0 / lam)
    ok6 = True
    for t in SAMPLE:
        resid_trunc = (payoff4 - cal0)[:t + 1]
        r_t = CS.ewma_shift1(resid_trunc, lam)[t]
        ok6 &= np.isclose(r_t, sigs[w]["resid"][lam][t], rtol=0, atol=0,
                          equal_nan=True)
        in_prev = bool(full6[t - 1]) if t > 0 else False
        want = SR.mpc_step(cal0, t, float(r_t), phi, K,
                           consts["enter"], consts["exit"], in_prev)
        ok6 &= want == bool(full6[t])
    check("s6 decisions recomputed from truncated data match", bool(ok6))

if 5 in ONLY:
    print("contract 5: tuning isolation + freeze gate")
    try:
        tune_candidate("s3", sigs[4], sigs[4]["hs"], 92.0, swaps, funding,
                       SR.E008Cache(4))
        check("tune_candidate(full window incl. August) raises", False)
    except AssertionError:
        check("tune_candidate(full window incl. August) raises", True)
    try:
        assert_all_frozen(E008 / "does-not-exist")
        check("final freeze gate raises while tune files missing", False)
    except SystemExit:
        check("final freeze gate raises while tune files missing", True)

if 6 in ONLY:
    print("contract 6: determinism")
    sig_b = SR.build_signals(4)
    same = all(np.array_equal(sigs[4]["cal"][k], sig_b["cal"][k])
               for k in SR.S1_KAPPAS)
    same &= np.array_equal(sigs[4]["score"], sig_b["score"], equal_nan=True)
    same &= sigs[4]["consts"] == sig_b["consts"]
    check("signals rebuild identical", bool(same))
    for cand, cfg in (("s1", {"kappa": 0, "hi_pct": 60, "lo_pct": 20}),
                      ("s5", {"kappa": 8, "c": 2.0}),
                      ("s6", {"lam": 8, "K": 6})):
        m0 = SR.make_mask(cand, cfg, sigs[4])
        m1 = SR.make_mask(cand, cfg, sig_b)
        check(f"{cand} mask rebuild identical", bool(np.array_equal(m0, m1)))
    sizes = {"s1": 75, "s2": 25, "s3": 54, "s4": 27, "s5": 12, "s6": 9}
    ok = all(len(SR.grid_configs(c)) == n for c, n in sizes.items())
    ok &= SR.grid_configs("s1")[0] == {"kappa": 0, "hi_pct": 50, "lo_pct": 10}
    ok &= SR.grid_configs("s6")[-1] == {"lam": 24, "K": 24}
    check("grid enumerations frozen (sizes + order endpoints)", ok)

if 7 in ONLY:
    print("contract 7: accounting identity over all cached streaks")
    for w in (4, 10):
        path = E008 / "out" / f"cache_w{w}.json"
        if not path.exists():
            check(f"w{w} cache exists", False)
            continue
        entries = [e for e in json.loads(path.read_text()).values()
                   if not e.get("empty")]
        worst = max((e["gap"] for e in entries), default=0.0)
        check(f"w{w} max gap <= 1e-6 over {len(entries)} cached streaks",
              worst <= 1e-6, f"{worst:.2e}")

print(f"\n{N_CHECKS} checks, {len(FAILED)} failed"
      + (f": {FAILED}" if FAILED else ""))
sys.exit(1 if FAILED else 0)
