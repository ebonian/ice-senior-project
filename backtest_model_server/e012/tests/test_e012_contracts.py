#!/usr/bin/env python3
"""E012 blocking contracts. Run before trusting any number in REPORT.md.

    nix develop .#gate1 -c python backtest_model_server/e012/tests/test_e012_contracts.py [pre|repro|oracle|post|all]

What can silently invalidate this experiment, and the check that catches it:

  pre    1. PARQUET DRIFT — sha256 of E010's committed month parquets vs
            committed meta (4/4) before anything loads.
         2. CLOSE-SERIES IDENTITY — p0·u0 identical across the two arms'
            committed stage-1 CSVs (signals are arm-invariant by contract).
         3. SIGNAL DEFINITION — trailing_rv reproduces e006
            trailing_signals exactly for n in {12,24,48}.
         4. CAUSALITY BY TRUNCATION — every signal series recomputed from
            data truncated at boundary t equals the full-series value at t
            (sampled boundaries, exact equality); every mask generator's
            prefix is invariant to future signal values.
         5. GRAIN/DWELL PROPERTY — masks change state only at allowed UTC
            boundaries; dwell masks never violate D.
         6. always_cash == $0.00 exactly at every point.
         7. TUNING ISOLATION — eval_mask raises AugustIsolationError on a
            mask crossing 2026-08-01 without the unlock token; final12
            refuses to run without a complete params_frozen.json.
  repro  8. ENGINE-PATH DRIFT — the all-ones mask per arm through THIS
            evaluator must reproduce E010's committed race rows
            float-consistently (Bucket fields + per-day + August month
            central) at all three coupled gas points; identity gap <= 1e-6.
  oracle 9. E011's committed held_central mask per arm through this
            evaluator returns E011's committed stage2 numbers at all three
            points (the evaluator judging the gate is the one that priced
            the ceiling).
  post  10. Freeze-file completeness (12 cells); every checkpointed cell's
            accounting gap <= 1e-6; DETERMINISM — a sampled tuned cell and
            a sampled frozen final re-evaluated cache-free reproduce the
            checkpointed numbers exactly.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

E012 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(E012))

import common12 as C12  # noqa: E402
import gates12 as G12   # noqa: E402

C11 = C12.C11
REL, ABS = 1e-9, 1e-6
FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          f"{('  — ' + detail) if detail else ''}", flush=True)
    if not ok:
        FAILS.append(name)


def close(a: float, b: float) -> bool:
    return abs(a - b) <= max(ABS, REL * max(abs(a), abs(b)))


def part_pre() -> None:
    print("[pre-1] parquet sha256 vs committed meta")
    months = C12.verify_parquets()
    check("parquet-sha256", len(months) == 4, f"{len(months)}/4 verified")

    print("[pre-2] close-series identity across arms")
    dfs = {lab: pd.read_csv(C11.OUT / f"stage1_hours_{lab}.csv")
           for lab in C12.ARM_LABELS}
    a, b = dfs[C12.ARM_LABELS[0]], dfs[C12.ARM_LABELS[1]]
    ok = (np.array_equal(a["hour_epoch"], b["hour_epoch"])
          and np.array_equal((a["p0"] * a["u0"]).to_numpy(),
                             (b["p0"] * b["u0"]).to_numpy())
          and close(float(a["p1"].iloc[-1] * a["u1"].iloc[-1]),
                    float(b["p1"].iloc[-1] * b["u1"].iloc[-1])))
    check("closes-arm-invariant", ok)

    print("[pre-3] trailing_rv == e006 trailing_signals (n in 12/24/48)")
    _, closes = C12.hours_and_closes()
    ref = C11.E6S.trailing_signals(closes)
    hs, _ = C12.hours_and_closes()
    nb = len(hs)
    for n in (12, 24, 48):
        mine = C12.trailing_rv(n)
        r = ref[f"rv_{n}h"][:nb]
        same = np.allclose(mine, r, rtol=0, atol=0, equal_nan=True)
        check(f"signal-def/rv_{n}", bool(same))

    print("[pre-4] causality by truncation (signals + mask prefixes)")
    rng = np.random.RandomState(0)   # sampling only; values are exact
    r_full = C12.hourly_returns()
    sample_ts = sorted(rng.choice(np.arange(200, nb - 1), 40, replace=False))
    for n in (12, 24, 48, 72, 168):
        sig = C12.trailing_rv(n)
        bad = []
        for t in sample_ts:
            trunc = np.std(r_full[t - n: t], ddof=1) if t >= n else np.nan
            if not (np.isnan(sig[t]) and np.isnan(trunc)
                    or sig[t] == trunc):
                bad.append(t)
        check(f"causal/rv_{n}", not bad, f"{len(bad)} mismatches")
    rvs = C12.swap_rv()
    for m in (1, 4):
        sig = C12.swap_rv_median(m)
        bad = [t for t in sample_ts
               if not (sig[t] == np.median(rvs[t - m: t]))]
        check(f"causal/swapmed_{m}", not bad, f"{len(bad)} mismatches")
    for lam in (0.97, 0.99, 0.995):
        sig = C12.ewma_rv(lam)
        s2 = float(np.mean(r_full[:C12.EWMA_SEED_H] ** 2))
        series = {C12.EWMA_SEED_H: np.sqrt(s2)}
        for t in range(C12.EWMA_SEED_H + 1, nb):
            s2 = lam * s2 + (1 - lam) * float(r_full[t - 1] ** 2)
            series[t] = np.sqrt(s2)
        bad = [t for t in sample_ts if sig[t] != series[t]]
        check(f"causal/ewma_{lam}", not bad, f"{len(bad)} mismatches")
    har, zs = C12.har_blend(None)
    har2, _ = C12.har_blend(zs)
    check("causal/har-frozen-zstats", bool(
        np.allclose(har, har2, rtol=0, atol=0, equal_nan=True)))

    # mask-prefix invariance: future signal values cannot change the past
    probe = [("V1", {"n": 12, "q_in": 0.30, "q_out": 0.95}),
             ("V2", {"n": 24, "q": 0.90, "D": 48}),
             ("V4", {"m": 1, "q_in": 0.50, "q_out": 0.80}),
             ("V6", {"n": 48, "q_in": 0.30, "q_out": 0.80})]
    for cid, cfg in probe:
        cand = G12.CANDIDATES[cid]
        sig, _ = G12.signal_for(cand, cfg)
        thr = G12.thresholds_from_tune(cand, cfg, sig)
        full = G12.build_mask(cand, cfg, sig, thr, hs)
        bad = []
        for t in sample_ts[:12]:
            sig2 = sig.copy()
            sig2[t + 1:] = np.nan
            m2 = G12.build_mask(cand, cfg, sig2, thr, hs)
            if not np.array_equal(m2[:t + 1], full[:t + 1]):
                bad.append(t)
        check(f"causal/mask-prefix/{cid}", not bad, f"{len(bad)} mismatches")

    print("[pre-5] grain/dwell property")
    for cid, cfg in probe:
        cand = G12.CANDIDATES[cid]
        sig, _ = G12.signal_for(cand, cfg)
        thr = G12.thresholds_from_tune(cand, cfg, sig)
        mask = G12.build_mask(cand, cfg, sig, thr, hs)
        chg = np.nonzero(mask[1:] != mask[:-1])[0] + 1
        period = cand["grain_h"] * 3600
        ok = all(hs[t] % period == 0 for t in chg)
        detail = f"{len(chg)} changes"
        if cand["kind"] == "dwell" and len(chg) > 1:
            gaps_h = np.diff(hs[chg]) / 3600.0
            ok = ok and bool((gaps_h >= cfg["D"]).all())
            detail += f", min gap {gaps_h.min():.0f}h vs D={cfg['D']}"
        check(f"grain-dwell/{cid}", ok, detail)

    print("[pre-6] always_cash == $0.00")
    cash = C11.R5.always_cash(100.0, {"2026-05": 100.0})
    ok = all(cash.total.net_usd(C11.ENVELOPE_BY_NAME[pn]) == 0.0
             for pn in C12.POINTS)
    ok = ok and all(getattr(cash.total, f) == 0.0
                    for f in C11.BUCKET_FIELDS if f != "hours")
    check("always-cash-zero", ok)

    print("[pre-7] tuning isolation raises; final refuses without freeze")
    arm = C12.arms12()[0]
    mask = np.ones(nb, dtype=bool)
    try:
        C12.eval_mask(arm, mask, hs, points=("central",))
        check("isolation-raises", False, "no exception")
    except C12.AugustIsolationError:
        check("isolation-raises", True)
    import final12
    try:
        final12.load_frozen(C12.OUT / "nonexistent_params.json")
        check("final-refuses-unfrozen", False, "no exception")
    except FileNotFoundError:
        check("final-refuses-unfrozen", True)


def part_repro() -> None:
    """E011's own baseline contract: always-in IS one unbroken streak from
    the first swap. The MASK path is hour-anchored (exact11's convention —
    identical to how the ceiling was priced), so it drops the pre-hs[0]
    sliver; the committed E010 rows are swap-anchored. Both cannot be
    reproduced float-exactly by one anchoring (deviation recorded in the
    experiment file): the E010 contract runs swap-anchored here, and the
    mask path is bound-checked against it (sliver <= $5, hours <= 1.01h)."""
    print("[repro] spanning streak == E010 committed race rows "
          "(2 arms x 3 pts) + mask-path sliver bound")
    hs, _ = C12.hours_and_closes()
    spec, swaps, funding, marks = C11.load_all()
    ts = swaps["timestamp"].to_numpy(np.int64)
    t_from, t_to = int(ts[0]), int(ts[-1]) + 1
    days = C11.window_days(swaps)
    mask = np.ones(len(hs), dtype=bool)
    for arm in C12.arms12():
        res = C12.eval_mask(arm, mask, hs, points=C12.POINTS,
                            unlock_heldout=True)
        for pn in C12.POINTS:
            with C11.chain_gas(pn):
                r = C11.simulate_streak(arm, t_from, t_to)
            committed = C11.read_json(C11.E010_RESULTS[pn])
            want = {a["arm"]: a for a in committed["arms"]}[arm["label"]]
            bad = []
            for f in C11.BUCKET_FIELDS:
                if not close(getattr(r.total, f), want["total"][f]):
                    bad.append(f)
            for q in C12.POINTS:
                per_day = r.total.per_day(C11.ENVELOPE_BY_NAME[q])
                if not close(per_day, want["total"][f"per_day_{q}"]):
                    bad.append(f"per_day_{q}")
            aug = {}
            C11.add_bucket(aug, r.months["2026-08"])
            aug_mine = C11.net_usd(aug, C11.ENVELOPE_BY_NAME[pn])
            aug_want = want["months"]["2026-08"][f"net_usd_{pn}"]
            if not close(aug_mine, aug_want):
                bad.append(f"aug {aug_mine} vs {aug_want}")
            check(f"repro/{pn}/{arm['label']}", not bad, "; ".join(bad[:3]))
            check(f"repro-identity-gap/{pn}/{arm['label']}",
                  r.checks["lp_value_abs_gap_usd"] <= 1e-6)
            got = res["points"][pn]
            d_net = abs(got["net_usd"]
                        - r.total.net_usd(C11.ENVELOPE_BY_NAME[pn]))
            d_hours = abs(got["total"]["hours"] - r.total.hours)
            check(f"repro-maskpath-sliver/{pn}/{arm['label']}",
                  d_net <= 5.0 and d_hours <= 1.01,
                  f"dnet ${d_net:.3f}, dhours {d_hours:.3f}")
            check(f"repro-gap/{pn}/{arm['label']}",
                  got["max_lp_value_abs_gap_usd"] <= 1e-6)


def part_oracle() -> None:
    print("[oracle] E011 held_central mask == E011 committed stage-2 rows")
    s2 = C11.read_json(C11.OUT / "stage2_results.json")
    hs, _ = C12.hours_and_closes()
    for arm in C12.arms12():
        lab = arm["label"]
        hrs = pd.read_csv(C11.OUT / f"stage1_hours_{lab}.csv")
        mask = hrs["held_central"].to_numpy(bool)
        res = C12.eval_mask(arm, mask, hs, points=C12.POINTS,
                            unlock_heldout=True)
        want = s2["arms"][lab]
        for pn in C12.POINTS:
            got = res["points"][pn]["net_usd"]
            exp = want["points"][pn]["net_usd"]
            check(f"oracle/{pn}/{lab}", close(got, exp),
                  f"{got:.6f} vs {exp:.6f}")
        check(f"oracle-nstreaks/{lab}",
              res["points"]["central"]["n_streaks_simulated"]
              == want["n_streaks_simulated"])
        check(f"oracle-gap/{lab}",
              max(res["points"][pn]["max_lp_value_abs_gap_usd"]
                  for pn in C12.POINTS) <= 1e-6)


def part_post() -> None:
    print("[post] freeze completeness, checkpoint gaps, determinism")
    fp = C12.OUT / "params_frozen.json"
    if not fp.exists():
        check("freeze-exists", False, "params_frozen.json missing")
        return
    frozen = C12.read_json(fp)
    cells = [(cid, arm) for cid in G12.CANDIDATES for arm in C12.ARM_LABELS]
    have = {(c["candidate"], c["arm"]) for c in frozen["cells"]}
    check("freeze-complete", have == set(cells),
          f"{len(have)}/{len(cells)} cells")

    tr = C12.read_json(C12.OUT / "tune_results.json")
    worst = max((cell["central"]["max_lp_value_abs_gap_usd"]
                 for cell in tr["cells"].values()), default=0.0)
    check("tune-gaps", worst <= 1e-6, f"worst {worst:.2e}")
    fr = C12.OUT / "final_results.json"
    if fr.exists():
        fin = C12.read_json(fr)
        worst = max(max(c["points"][pn]["max_lp_value_abs_gap_usd"]
                        for pn in C12.POINTS)
                    for c in fin["cells"].values())
        check("final-gaps", worst <= 1e-6, f"worst {worst:.2e}")

    # determinism: re-evaluate one tuned cell and one frozen final cell
    import tune12
    key0 = sorted(tr["cells"])[0]
    fresh = tune12.eval_cell_by_key(key0)
    old = tr["cells"][key0]["central"]
    same = (fresh["central"]["net_usd"] == old["net_usd"]
            and fresh["central"]["n_streaks_simulated"]
            == old["n_streaks_simulated"])
    check("determinism-tune-cell", same, key0)
    if fr.exists():
        import final12
        cid, arm_lab = frozen["cells"][0]["candidate"], \
            frozen["cells"][0]["arm"]
        fresh = final12.eval_frozen_cell(frozen["cells"][0])
        old = fin["cells"][f"{cid}|{arm_lab}"]
        same = all(fresh["points"][pn]["net_usd"]
                   == old["points"][pn]["net_usd"] for pn in C12.POINTS)
        check("determinism-final-cell", same, f"{cid}|{arm_lab}")


PARTS = {"pre": part_pre, "repro": part_repro, "oracle": part_oracle,
         "post": part_post}

if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    for name, fn in PARTS.items():
        if which in (name, "all"):
            fn()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURES:")
        for f in FAILS:
            print(f"  {f}")
        sys.exit(1)
    print(f"contracts PASS ({which})")
