#!/usr/bin/env python3
"""Fixture test for the shared cost model.

04-backtest-design.md §2.3 asks for one self-contained `cost_model.py`, kept in
`research/backtest_model_server/` and copied into `bot/analysis/` with a test
that both copies produce identical output on a fixed fixture. This is that test.

Two jobs:
  1. Pin the constants and the arithmetic, so a later edit that silently changes
     a frozen constant fails loudly (§6.3 guard 2: freeze before counterfactuals).
  2. Compare against the bot-side copy when it exists. This session has read-only
     access to the bot repo, so the copy has not been placed; the test reports
     that rather than passing quietly.

Run:  nix develop .#gate1 -c python backtest_model_server/gate1/tests/test_cost_model_fixture.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import cost_model as CM  # noqa: E402

BOT_COPY = Path("/home/poon/developments/llaminet/bot/analysis/cost_model.py")


def fixture(m) -> dict:
    """Deterministic exercise of every public entry point."""
    oc = m.onchain_cost(9062.15, 8, 8, n_tx=43)
    oc_est = m.onchain_cost(9062.15, 8, 8)
    fills = [(500.0, True), (500.0, False), (1234.56, True)]
    return {
        "version": m.COST_MODEL_VERSION,
        "constants": {
            "POOL_FEE_BPS": m.POOL_FEE_BPS,
            "FEE_PROTOCOL_DENOMINATOR": m.FEE_PROTOCOL_DENOMINATOR,
            "LP_FEE_SHARE": m.LP_FEE_SHARE,
            "EFFECTIVE_LP_FEE_BPS": m.EFFECTIVE_LP_FEE_BPS,
            "EXTRA_SWAP_SLIPPAGE_BPS": m.EXTRA_SWAP_SLIPPAGE_BPS,
            "GAS_USD_PER_TX": m.GAS_USD_PER_TX,
            "TX_PER_REBALANCE": m.TX_PER_REBALANCE,
            "TX_PER_EXIT": m.TX_PER_EXIT,
            "FAILED_MINT_RATE": m.FAILED_MINT_RATE,
            "HPL_MAKER_BPS": m.HPL_MAKER_BPS,
            "HPL_TAKER_BPS": m.HPL_TAKER_BPS,
        },
        "onchain_audited_tx": [round(oc.swap_cost_usd, 8), round(oc.gas_usd, 8),
                               round(oc.failed_tx_usd, 8), round(oc.total_usd, 8)],
        "onchain_estimated_tx": [oc_est.n_tx, round(oc_est.total_usd, 8)],
        "hpl_from_fills": round(m.hpl_fees_from_fills(fills), 8),
        "hpl_from_shares": round(m.hpl_fees_from_shares(8825.87, 4830.95), 8),
        "funding": round(
            m.funding_pnl([(0, 1.25e-5), (1, 1.25e-5), (2, 2.0e-5)], lambda h: 560.72), 8
        ),
    }


# Golden values, frozen 2026-08-29 alongside the constants.
GOLDEN = {
    "version": "gate1-2026-08-29",
    "constants": {
        "POOL_FEE_BPS": 5.0,
        "FEE_PROTOCOL_DENOMINATOR": 4, "LP_FEE_SHARE": 0.75,
        "EFFECTIVE_LP_FEE_BPS": 3.75,
        "EXTRA_SWAP_SLIPPAGE_BPS": 0.155,
        "GAS_USD_PER_TX": 0.0101, "TX_PER_REBALANCE": 3, "TX_PER_EXIT": 2,
        "FAILED_MINT_RATE": 0.19, "HPL_MAKER_BPS": 1.44, "HPL_TAKER_BPS": 4.32,
    },
    "onchain_audited_tx": [4.67153833, 0.4343, 0.015352, 5.12119033],
    "onchain_estimated_tx": [40, 5.09089033],
    "hpl_from_fills": 0.46577664,
    "hpl_from_shares": 3.35789568,
    "funding": 0.0252324,
}


def main() -> int:
    got = fixture(CM)
    print("--- research copy fixture ---")
    print(json.dumps(got, indent=2))

    ok = True
    # Constants and version are pinned exactly.
    if got["constants"] != GOLDEN["constants"]:
        print("\nFAIL: frozen constants changed")
        print("  golden:", GOLDEN["constants"])
        print("  got   :", got["constants"])
        ok = False
    if got["version"] != GOLDEN["version"]:
        print(f"\nNOTE: cost model version moved "
              f"{GOLDEN['version']} -> {got['version']}; update GOLDEN deliberately")

    # Derived values to 6 dp, so an arithmetic change is caught.
    for k in ("hpl_from_fills", "hpl_from_shares", "funding"):
        if abs(got[k] - GOLDEN[k]) > 1e-6:
            print(f"\nFAIL: {k} {got[k]} != golden {GOLDEN[k]}")
            ok = False
    for k in ("onchain_audited_tx", "onchain_estimated_tx"):
        if any(abs(a - b) > 1e-6 for a, b in zip(got[k], GOLDEN[k])):
            print(f"\nFAIL: {k} {got[k]} != golden {GOLDEN[k]}")
            ok = False

    # Cross-copy equality, when the bot-side copy exists.
    print("\n--- bot-side copy ---")
    if BOT_COPY.exists():
        spec = importlib.util.spec_from_file_location("_bot_cost_model", BOT_COPY)
        bot_m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bot_m)
        bot_got = fixture(bot_m)
        if bot_got == got:
            print(f"PASS: {BOT_COPY} produces identical output")
        else:
            print(f"FAIL: {BOT_COPY} diverges")
            for k in got:
                if got[k] != bot_got.get(k):
                    print(f"  {k}: research={got[k]}  bot={bot_got.get(k)}")
            ok = False
    else:
        print(f"NOT PRESENT: {BOT_COPY}")
        print("This session has read-only access to the bot repo, so the copy was")
        print("not placed. Copying engine/cost_model.py to that path (header comment")
        print("already names the source of truth) makes this check active.")

    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
