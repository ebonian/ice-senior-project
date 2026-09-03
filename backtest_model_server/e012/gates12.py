"""E012 candidate registry — M006 §4's six pre-named rules, grids verbatim.

Nothing outside CANDIDATES may be evaluated (multiple-comparisons guard).
Each config resolves to (signal series, thresholds-from-tune-quantiles,
mask generator). Thresholds are frozen to ABSOLUTE values by tune12.py;
final12.py re-builds masks from the frozen absolutes only.
"""

from __future__ import annotations

import numpy as np

import common12 as C12

# grid order is the pre-registered tie-break (first best wins)
CANDIDATES: dict[str, dict] = {
    "V1": {"desc": "trailing-RV hysteresis", "grain_h": 4, "kind": "hyst",
           "signal": "rv",
           "grid": [{"n": n, "q_in": qi, "q_out": qo}
                    for n in (12, 24, 48)
                    for qi in (0.30, 0.50)
                    for qo in (0.80, 0.95)]},
    "V2": {"desc": "RV threshold + min-dwell", "grain_h": 4, "kind": "dwell",
           "signal": "rv",
           "grid": [{"n": n, "q": q, "D": D}
                    for n in (12, 24)
                    for q in (0.70, 0.90)
                    for D in (24, 48, 96)]},
    "V3": {"desc": "HAR z-blend hysteresis", "grain_h": 24, "kind": "hyst",
           "signal": "har",
           "grid": [{"q_in": qi, "q_out": qo}
                    for qi in (0.30, 0.50)
                    for qo in (0.80, 0.95)]},
    "V4": {"desc": "prev-hour swap-RV hysteresis", "grain_h": 4,
           "kind": "hyst", "signal": "swapmed",
           "grid": [{"m": m, "q_in": qi, "q_out": qo}
                    for m in (1, 4)
                    for qi in (0.30, 0.50)
                    for qo in (0.80, 0.95)]},
    "V5": {"desc": "EWMA-RV hysteresis", "grain_h": 4, "kind": "hyst",
           "signal": "ewma",
           "grid": [{"lam": lam, "q_in": qi, "q_out": qo}
                    for lam in (0.97, 0.99, 0.995)
                    for qi in (0.30, 0.50)
                    for qo in (0.80, 0.95)]},
    "V6": {"desc": "trailing-RV hysteresis, daily", "grain_h": 24,
           "kind": "hyst", "signal": "rv",
           "grid": [{"n": n, "q_in": qi, "q_out": qo}
                    for n in (24, 48, 72)
                    for qi in (0.30, 0.50)
                    for qo in (0.80, 0.95)]},
}


def signal_for(cand: dict, cfg: dict, zstats: dict | None = None):
    """(series, zstats_or_None). zstats only meaningful for V3: pass the
    frozen stats in the final phase; None computes them from tune."""
    kind = cand["signal"]
    if kind == "rv":
        return C12.trailing_rv(cfg["n"]), None
    if kind == "swapmed":
        return C12.swap_rv_median(cfg["m"]), None
    if kind == "ewma":
        return C12.ewma_rv(cfg["lam"]), None
    if kind == "har":
        sig, zs = C12.har_blend(zstats)
        return sig, zs
    raise ValueError(kind)


def thresholds_from_tune(cand: dict, cfg: dict, sig: np.ndarray) -> dict:
    """Quantiles over tune-window valid hours → absolute values (frozen)."""
    if cand["kind"] == "hyst":
        return {"thr_in": C12.tune_quantile(sig, cfg["q_in"]),
                "thr_out": C12.tune_quantile(sig, cfg["q_out"])}
    return {"thr": C12.tune_quantile(sig, cfg["q"])}


def build_mask(cand: dict, cfg: dict, sig: np.ndarray, thr: dict,
               hs: np.ndarray) -> np.ndarray:
    if cand["kind"] == "hyst":
        return C12.gate_mask_hysteresis(sig, hs, cand["grain_h"],
                                        thr["thr_in"], thr["thr_out"])
    return C12.gate_mask_dwell(sig, hs, cand["grain_h"], thr["thr"],
                               cfg["D"])


def cfg_label(cfg: dict) -> str:
    return "_".join(f"{k}{v}" for k, v in cfg.items())
