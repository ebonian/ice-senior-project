#!/usr/bin/env python3
"""E008 — the six pre-named streak-aware policies (memo M002 §3, pre-registered).

Selector constructions are reused BY IMPORT from e007's `causal_signals`
(the dow×hod calendar C3 and the payoff EWMA C1, byte-identical code paths);
the exact evaluator and per-streak cache are e007's `evaluate` (E006 stage-2
machinery); the two-state DP is e006's `oracle.dp_select`. Nothing under
`gate1/`, `e003/`, `e005/`, `e006/`, `e007/` is modified.

Policies (grids frozen in M002 §3; enumeration order below IS the tie-break
order; thresholds are tune-window quantiles; NaN signal => out; initial
state: out):

  S1  calendar hysteresis      out->in iff CAL_k(t) >= th_hi;
                               in->out iff CAL_k(t) <  th_lo
  S2  blend hysteresis         score = min(F_pay(PAY_24), F_cal(CAL_0)),
                               F = tune-window ECDFs (E007 C6 score, params
                               inherited); enter >= q_hi, exit < q_lo
  S3  minimum dwell            enter iff CAL_0 >= theta; hold >= D hours;
                               then exit iff CAL_0 < theta
  S4  exit debounce            enter iff CAL_0 >= theta; exit only on the
                               M-th consecutive hour with CAL_0 < theta
                               (bridges gaps < M, holds M-1 trailing hours)
  S5  DP over calendar         e006 two-state DP on y_t = CAL_k(t) with
                               constant switch costs c*(enter_mean, exit_mean)
                               [tune-window stage-1 means, central point]
  S6  receding-horizon DP      at each t: y_{t+j} = CAL_0(t+j) + r_t*phi^j,
                               r_t = EWMA_lam of past residuals
                               (payoff - CAL_0, shifted 1h), phi = 2^(-1/lam);
                               K-hour DP from the policy's current state,
                               exit charged if in at horizon end; execute
                               hour t only

Every decision at hour t is computable from data <= t relative to the
held-out wall (2026-08-01): calendar cells, ECDFs, percentile thresholds and
cost constants derive from tune rows only; EWMAs are shift(1)-causal.
Contract tests in tests/test_e008_contracts.py verify this by truncated
recomputation and scrambled-August invariance.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

E008 = Path(__file__).resolve().parent
BMS = E008.parent
for p in (BMS / "gate1", BMS / "e003", BMS / "e006", BMS / "e007"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
import causal_signals as CS   # noqa: E402  (e007)
import evaluate as EV         # noqa: E402  (e007)
import oracle                 # noqa: E402  (e006)
import envelope as ENV        # noqa: E402  (e003)

AUG1_EPOCH = CS.AUG1_EPOCH
NEG = -1e18

# --- frozen grids (M002 §3) — enumeration order is the tie-break order -----
S1_KAPPAS = (0, 8, 32)
S1_HI_PCTS = (50, 60, 70, 80, 90)
S1_LO_PCTS = (10, 20, 30, 40, 50)
S2_Q_HI = (0.5, 0.6, 0.7, 0.8, 0.9)
S2_Q_LO = (0.1, 0.2, 0.3, 0.4, 0.5)
S3_THETA_PCTS = tuple(range(10, 100, 10))
S3_DWELLS = (2, 3, 4, 6, 8, 12)
S4_THETA_PCTS = tuple(range(10, 100, 10))
S4_DEBOUNCE = (2, 3, 4)
S5_KAPPAS = (0, 8, 32)
S5_COST_MULT = (0.5, 1.0, 2.0, 4.0)
S6_HALFLIVES = (8, 16, 24)
S6_HORIZONS = (6, 12, 24)

PAY_HALFLIFE = 24        # E007 C1 tuned value, inherited (both arms)
CAL_KAPPA_INHERITED = 0  # E007 C3 tuned value, inherited (both arms)

CANDIDATES = ("s1", "s2", "s3", "s4", "s5", "s6")


class E008Cache(EV.StreakCache):
    """e007's per-streak exact-simulation cache, stored under e008/out/."""

    def __init__(self, w: int):
        self.w = w
        self.path = E008 / "out" / f"cache_w{w}.json"
        self.data = {}
        self.dirty = 0
        if self.path.exists():
            self.data = json.loads(self.path.read_text())


# --------------------------------------------------------------------------
def tune_ecdf(values_tune: np.ndarray):
    """ECDF fitted on tune-window values only (NaNs dropped). F(NaN) = NaN."""
    base = np.sort(values_tune[~np.isnan(values_tune)])

    def F(x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=float)
        out = np.full(x.shape, np.nan)
        m = ~np.isnan(x)
        out[m] = np.searchsorted(base, x[m], side="right") / len(base)
        return out

    return F


def build_signals(w: int, payoff_override: np.ndarray | None = None) -> dict:
    """Everything a candidate needs for width w. Tune-window-derived pieces
    (calendar cells, percentiles, ECDFs, switch-cost means) use only rows
    with hour_epoch < AUG1_EPOCH. `payoff_override` exists for the causality
    contract (scrambled-August invariance) only."""
    hours = CS.load_hours(w)
    hs = hours["hour_epoch"].to_numpy(np.int64)
    payoff = hours["payoff_usd"].to_numpy(np.float64)
    if payoff_override is not None:
        payoff = np.asarray(payoff_override, dtype=np.float64)
    tune = hs < AUG1_EPOCH

    cal = {k: CS.seasonal_signal(hs, payoff, kappa=k) for k in S1_KAPPAS}
    pay = CS.ewma_shift1(payoff, PAY_HALFLIFE)
    cal_pcts = {k: {p: float(np.percentile(cal[k][tune], p))
                    for p in range(10, 100, 10)} for k in S1_KAPPAS}
    F_pay = tune_ecdf(pay[tune])
    F_cal = tune_ecdf(cal[CAL_KAPPA_INHERITED][tune])
    score = np.minimum(F_pay(pay), F_cal(cal[CAL_KAPPA_INHERITED]))

    point = ENV.ENVELOPE_BY_NAME["central"]
    ht = hours[tune].reset_index(drop=True)
    enter_arr, exit_arr = oracle.switch_costs(ht, point)
    consts = {"enter": float(enter_arr.mean()), "exit": float(exit_arr[1:].mean())}

    resid = {lam: CS.ewma_shift1(payoff - cal[CAL_KAPPA_INHERITED], lam)
             for lam in S6_HALFLIVES}

    return {"w": w, "hours": hours, "hs": hs, "payoff": payoff, "tune": tune,
            "cal": cal, "pay": pay, "cal_pcts": cal_pcts, "score": score,
            "consts": consts, "resid": resid}


# --- the mechanisms --------------------------------------------------------
def hysteresis_mask(sig: np.ndarray, th_hi: float, th_lo: float) -> np.ndarray:
    n = len(sig)
    mask = np.zeros(n, dtype=bool)
    in_pos = False
    for t in range(n):
        v = sig[t]
        if np.isnan(v):
            in_pos = False
        elif in_pos:
            in_pos = v >= th_lo
        else:
            in_pos = v >= th_hi
        mask[t] = in_pos
    return mask


def dwell_mask(sig: np.ndarray, theta: float, D: int) -> np.ndarray:
    n = len(sig)
    mask = np.zeros(n, dtype=bool)
    in_pos, age = False, 0
    for t in range(n):
        v = sig[t]
        if np.isnan(v):
            in_pos, age = False, 0
        elif not in_pos:
            if v >= theta:
                in_pos, age = True, 0
        else:
            if age >= D and v < theta:
                in_pos, age = False, 0
        if in_pos:
            mask[t] = True
            age += 1
    return mask


def debounce_mask(sig: np.ndarray, theta: float, M: int) -> np.ndarray:
    n = len(sig)
    mask = np.zeros(n, dtype=bool)
    in_pos, below = False, 0
    for t in range(n):
        v = sig[t]
        if np.isnan(v):
            in_pos, below = False, 0
        elif not in_pos:
            if v >= theta:
                in_pos, below = True, 0
        else:
            if v >= theta:
                below = 0
            else:
                below += 1
                if below >= M:
                    in_pos, below = False, 0
        mask[t] = in_pos
    return mask


def dp_calendar_mask(cal_series: np.ndarray, enter_cost: float,
                     exit_cost: float) -> np.ndarray:
    """S5: e006's exact two-state DP on the forecast series with constant
    switch costs. Consumes ONLY the forecast series — realized payoffs never
    enter this function."""
    n = len(cal_series)
    enter = np.full(n, enter_cost)
    exit_ = np.concatenate([[np.inf], np.full(n, exit_cost)])
    _, held = oracle.dp_select(np.asarray(cal_series, dtype=float), enter, exit_)
    return held


def mpc_step(cal_series: np.ndarray, t: int, r_t: float, phi: float, K: int,
             enter_cost: float, exit_cost: float, in_prev: bool) -> bool:
    """S6's one decision: K-hour backward induction over the forecast
    y_{t+j} = cal[t+j] + r_t*phi^j, from the policy's current state; exit
    charged if in at horizon end; ties keep the current state. Consumes ONLY
    forecast values."""
    n = len(cal_series)
    kk = min(K, n - t)
    y = cal_series[t:t + kk] + r_t * phi ** np.arange(kk)
    v_in, v_out = -exit_cost, 0.0
    a_in = a_out = False
    for k in range(kk - 1, -1, -1):
        in_if_in = y[k] + v_in
        out_if_in = -exit_cost + v_out
        in_if_out = -enter_cost + y[k] + v_in
        out_if_out = v_out
        a_in = bool(in_if_in >= out_if_in)      # from in: stay in on ties
        a_out = bool(in_if_out > out_if_out)    # from out: stay out on ties
        v_in = in_if_in if a_in else out_if_in
        v_out = in_if_out if a_out else out_if_out
    return a_in if in_prev else a_out


def mpc_mask(cal_series: np.ndarray, resid_ewma: np.ndarray, lam: int, K: int,
             enter_cost: float, exit_cost: float) -> np.ndarray:
    phi = 2.0 ** (-1.0 / lam)
    n = len(cal_series)
    mask = np.zeros(n, dtype=bool)
    in_prev = False
    for t in range(n):
        r = resid_ewma[t]
        if np.isnan(r):
            in_prev = False
        else:
            in_prev = mpc_step(cal_series, t, float(r), phi, K,
                               enter_cost, exit_cost, in_prev)
        mask[t] = in_prev
    return mask


# --- config enumeration + dispatch ----------------------------------------
def grid_configs(cand: str) -> list[dict]:
    """Ordered configs; list order is the pre-registered tie-break order."""
    if cand == "s1":
        return [{"kappa": k, "hi_pct": h, "lo_pct": lo}
                for k in S1_KAPPAS for h in S1_HI_PCTS for lo in S1_LO_PCTS]
    if cand == "s2":
        return [{"q_hi": qh, "q_lo": ql} for qh in S2_Q_HI for ql in S2_Q_LO]
    if cand == "s3":
        return [{"theta_pct": p, "D": d} for p in S3_THETA_PCTS for d in S3_DWELLS]
    if cand == "s4":
        return [{"theta_pct": p, "M": m} for p in S4_THETA_PCTS for m in S4_DEBOUNCE]
    if cand == "s5":
        return [{"kappa": k, "c": c} for k in S5_KAPPAS for c in S5_COST_MULT]
    if cand == "s6":
        return [{"lam": lam, "K": K} for lam in S6_HALFLIVES for K in S6_HORIZONS]
    raise ValueError(cand)


def cfg_key(cfg: dict) -> str:
    return "_".join(f"{k}{v}" for k, v in sorted(cfg.items()))


def make_mask(cand: str, cfg: dict, sigs: dict, n: int | None = None) -> np.ndarray:
    """Policy mask over the first n hours (None = full grid). State machines
    start from `out` at index 0 in both cases; truncating the input series
    is identical to truncating the run (all signals are causal)."""
    if n is None:
        n = len(sigs["hs"])
    consts = sigs["consts"]
    if cand == "s1":
        sig = sigs["cal"][cfg["kappa"]][:n]
        pct = sigs["cal_pcts"][cfg["kappa"]]
        return hysteresis_mask(sig, pct[cfg["hi_pct"]], pct[cfg["lo_pct"]])
    if cand == "s2":
        return hysteresis_mask(sigs["score"][:n], cfg["q_hi"], cfg["q_lo"])
    if cand == "s3":
        pct = sigs["cal_pcts"][CAL_KAPPA_INHERITED]
        return dwell_mask(sigs["cal"][CAL_KAPPA_INHERITED][:n],
                          pct[cfg["theta_pct"]], cfg["D"])
    if cand == "s4":
        pct = sigs["cal_pcts"][CAL_KAPPA_INHERITED]
        return debounce_mask(sigs["cal"][CAL_KAPPA_INHERITED][:n],
                             pct[cfg["theta_pct"]], cfg["M"])
    if cand == "s5":
        return dp_calendar_mask(sigs["cal"][cfg["kappa"]][:n],
                                cfg["c"] * consts["enter"],
                                cfg["c"] * consts["exit"])
    if cand == "s6":
        return mpc_mask(sigs["cal"][CAL_KAPPA_INHERITED][:n],
                        sigs["resid"][cfg["lam"]][:n], cfg["lam"], cfg["K"],
                        consts["enter"], consts["exit"])
    raise ValueError(cand)


def auc_score(cand: str, cfg: dict, sigs: dict) -> np.ndarray:
    """Descriptive AUC score series (oriented: higher = points toward held)."""
    if cand in ("s1", "s5"):
        return sigs["cal"][cfg["kappa"]]
    if cand == "s2":
        return sigs["score"]
    if cand in ("s3", "s4"):
        return sigs["cal"][CAL_KAPPA_INHERITED]
    if cand == "s6":
        return sigs["cal"][CAL_KAPPA_INHERITED] + np.nan_to_num(
            sigs["resid"][cfg["lam"]], nan=0.0)
    raise ValueError(cand)
