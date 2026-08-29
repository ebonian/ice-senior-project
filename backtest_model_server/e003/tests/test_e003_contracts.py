#!/usr/bin/env python3
"""Contract tests for E003. Run before trusting any number in REPORT.md.

    nix develop .#gate1 -c python backtest_model_server/e003/tests/test_e003_contracts.py

Three things can silently invalidate this experiment, and each gets a test:

  1. The width->tick mapping. If W10 does not mean what the live bot minted,
     every arm is mislabelled and the frontier is about nothing.
  2. The frozen cost model. E003 must be using gate1's constants unchanged; a
     local copy that drifted would be the exact failure §6.3 guard 2 forbids.
  3. The envelope arithmetic. The central point exists to reproduce a measured
     hedge fee line, so it is checked against T5's recorded fills.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

E003 = Path(__file__).resolve().parents[1]
GATE1 = E003.parent / "gate1"
sys.path.insert(0, str(GATE1))
sys.path.insert(0, str(E003))

from engine import cost_model as CM  # noqa: E402
from engine import harness as H  # noqa: E402
import envelope as ENV  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{('  — ' + detail) if detail else ''}")
    if not ok:
        FAILS.append(name)


# --- 1. width -> ticks ------------------------------------------------------
print("1. width -> tick mapping")

# The harness's own contract, in human-tick space.
for w in ENV.WIDTH_ARMS:
    r = H.bt.compute_lp_range_from_width(3800.0, w, 10)
    span = r["upper_tick"] - r["lower_tick"]
    check(f"W{w} spans {w} tick-spacings in the harness",
          span == w * 10, f"got {span}, want {w * 10}")

check("half_width_ticks matches 03_run_infer_backtest.py:234 for every arm",
      all(ENV.half_width_ticks(w) == w * 10 // 2 for w in ENV.WIDTH_ARMS))

# T5 cycle 6 minted v3 ticks -198970..-198870: a 100-tick interval, i.e. W10.
LIVE_LOWER, LIVE_UPPER = -198970, -198870
live_span = LIVE_UPPER - LIVE_LOWER
check("T5's recorded mint is exactly W10 under this mapping",
      live_span == 2 * ENV.half_width_ticks(10),
      f"recorded span {live_span} ticks, W10 span {2 * ENV.half_width_ticks(10)}")
check("live ticks are aligned to tickSpacing 10 (so the mapping is v3-tick space)",
      LIVE_LOWER % 10 == 0 and LIVE_UPPER % 10 == 0)

for w, want_pct in ((4, 0.2002), (10, 0.5013), (20, 1.0050), (160, 8.3287)):
    got = ENV.width_pct(w) * 100
    check(f"W{w} = ±{want_pct}%", abs(got - want_pct) < 5e-4, f"got ±{got:.4f}%")


# --- 2. frozen cost model ---------------------------------------------------
print("\n2. frozen cost model (gate1-2026-08-29), imported not copied")

check("E003 reads the version straight off gate1",
      CM.COST_MODEL_VERSION == "gate1-2026-08-29", CM.COST_MODEL_VERSION)
check("cost_model module resolves inside gate1/engine",
      "gate1/engine/cost_model.py" in str(Path(CM.__file__).as_posix()),
      str(CM.__file__))
for name, want in (("POOL_FEE_BPS", 5.0), ("LP_FEE_SHARE", 0.75),
                   ("EFFECTIVE_LP_FEE_BPS", 3.75), ("EXTRA_SWAP_SLIPPAGE_BPS", 0.155),
                   ("GAS_USD_PER_TX", 0.0101), ("FAILED_MINT_RATE", 0.19),
                   ("HPL_MAKER_BPS", 1.44), ("HPL_TAKER_BPS", 4.32)):
    check(f"{name} == {want}", abs(getattr(CM, name) - want) < 1e-12,
          str(getattr(CM, name)))

# The measured T5 anchor: $9,062.15 swapped, 43 txs -> $5.10 total on-chain.
oc = CM.onchain_cost(9062.15, 8, 8, n_tx=43)
check("onchain_cost reproduces T5's audited $5.1049 total",
      abs(oc.total_usd - 5.1049) < 0.02, f"${oc.total_usd:.4f}")


# --- 3. envelope ------------------------------------------------------------
print("\n3. hedge execution envelope")

opt, cen, pes = ENV.ENVELOPE
check("central maker share is E002 F5's notional-weighted 64.63%",
      abs(cen.maker_share_notional - 0.6463) < 1e-9)
check("central maker share is NOT the count-weighted 86.06% (the F5 trap)",
      abs(cen.maker_share_notional - 0.8606) > 0.1)
check("pessimistic is all-taker", pes.maker_share_notional == 0.0)
check("envelope is monotone in cost",
      opt.total_bps < cen.total_bps < pes.total_bps,
      f"{opt.total_bps:.3f} < {cen.total_bps:.3f} < {pes.total_bps:.3f}")
check("pessimistic fee leg equals the taker rate exactly",
      abs(pes.fee_bps - CM.HPL_TAKER_BPS) < 1e-12)

# T5's recorded fills: $3.3577 of HPL fees on maker/taker notionals whose
# notional-weighted maker share is 64.63%. The central point's FEE leg (which
# excludes slippage, because the recorded figure is fees only) must reproduce it.
t5_fee_bps_from_shares = (
    CM.hpl_fees_from_shares(0.6463, 1 - 0.6463) / 1.0 * 1e4)
check("central fee leg == cost_model.hpl_fees_from_shares at the same share",
      abs(cen.fee_bps - t5_fee_bps_from_shares) < 1e-9,
      f"{cen.fee_bps:.6f} vs {t5_fee_bps_from_shares:.6f}")
t5_notional = 3.3577 / (cen.fee_bps / 1e4)
check("implied T5 hedge notional is plausible for a 24h $1k-LP hedge",
      5_000 < t5_notional < 40_000, f"${t5_notional:,.0f}")


# --- 4. capital and target --------------------------------------------------
print("\n4. capital and the pre-registered target")

check("LP + hedge equity == $1,420 total",
      abs(ENV.TOTAL_CAPITAL_USD - 1420.0) < 1e-9, f"${ENV.TOTAL_CAPITAL_USD}")
check("target is 10% APR on total capital and equals the pre-registered $0.39",
      abs(ENV.TARGET_USD_PER_DAY - 0.389) < 0.001,
      f"${ENV.TARGET_USD_PER_DAY:.4f}/day")


print()
if FAILS:
    print(f"{len(FAILS)} FAILED: " + ", ".join(FAILS))
    raise SystemExit(1)
print("all contract tests pass")
