"""Loaders for the recorded trial data that mode-A replay consumes.

Mode A replays the trials' RECORDED positions and actions. Nothing here is
counterfactual: cycles come from `rebalance-history`, the perp notional path
from `aum-history`, fills from `trade_history`, funding from the saved
Hyperliquid rate series.

Two data traps are handled here rather than at the call sites:

  * `trade_history.csv` is UTC+7 (bot issue T). Every other export is UTC.
    `load_fills` converts. Getting this wrong shifts the trade window 7 hours
    and was what produced the phantom "$7.22/day funding swing".
  * An `executed_exit` row does not always mean liquidity was burned. T4 has
    two exit rows whose remove tx emitted no Burn (see `Cycle.orphan_exits`),
    and whose `accumulated_fees_usd` is a running total that was never reset —
    so summing all exit rows double-counts those cycles' fees.
"""

from __future__ import annotations

import csv
import glob
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

TRIALS_DIR = Path("/home/poon/developments/llaminet/bot/analysis/trials")
REVIEW_DATA = Path("/home/poon/developments/llaminet/bot/analysis/strategy-review/data")
GATE1 = Path(__file__).resolve().parents[1]

WINDOWS = {
    4: ("2026-05-12T16:00:00+00:00", "2026-05-13T16:00:00+00:00"),
    5: ("2026-05-14T05:00:00+00:00", "2026-05-15T05:00:00+00:00"),
}
TRADE_TZ_OFFSET_HOURS = 7  # issue T


def _trial_file(trial: int, pattern: str) -> Path:
    hits = glob.glob(str(TRIALS_DIR / str(trial) / pattern))
    if not hits:
        raise FileNotFoundError(f"T{trial}: no file matching {pattern}")
    return Path(sorted(hits)[0])


def window(trial: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    a, b = WINDOWS[trial]
    return pd.Timestamp(a), pd.Timestamp(b)


# --------------------------------------------------------------------------
# LP cycles
# --------------------------------------------------------------------------
@dataclass
class Cycle:
    idx: int
    mint_ts: pd.Timestamp
    burn_ts: pd.Timestamp
    mint_tx: str
    burn_tx: str
    lower_v3_tick: int
    upper_v3_tick: int
    recorded_fees_usd: float          # accumulated_fees_usd on the burn row
    mint_row_wallet_usd: float        # capital sitting in the wallet just before the mint
    burn_row_position_usd: float      # position value just before the burn
    mint_block: int | None = None
    burn_block: int | None = None
    # Exact on-chain quantities, filled from RPC receipts when available.
    onchain: dict = field(default_factory=dict)
    orphan_exits: list = field(default_factory=list)   # exit rows whose tx reverted
    intra_rows: list = field(default_factory=list)     # non-exit rows inside the cycle
    # False when the position was never actually burned — either the exit tx
    # reverted with no later retry, or the window ended with it open. Fees still
    # accrued (they are in `accumulated_fees_usd`), but IL was NOT crystallized.
    crystallized: bool = True


def load_rebalance_rows(trial: int) -> list[dict]:
    f = _trial_file(trial, "rebalance-history-*.csv")
    rows = list(csv.DictReader(open(f, encoding="utf-8-sig")))
    for r in rows:
        r["_ts"] = pd.Timestamp(r["timestamp"])
    rows.sort(key=lambda r: r["_ts"])
    return rows


def load_cycles(
    trial: int,
    actions_json: Path | None = None,
    assume_all_exits_burned: bool = False,
) -> list[Cycle]:
    """Pair executed_rebalance (mint) with the exit that actually burned.

    When `actions_json` (written by fetch_rpc_window.py) is present, an exit is
    treated as a real burn only if its tx emitted a pool Burn event with
    non-zero liquidity. Without it, every executed_exit is assumed real — which
    is the assumption that double-counts T4.
    """
    rows = load_rebalance_rows(trial)

    burned: dict[str, dict] = {}
    if actions_json and Path(actions_json).exists():
        for a in json.loads(Path(actions_json).read_text()):
            ev = a.get("events") or {}
            burns = [b for b in ev.get("burn", []) if b["liquidity"] > 0]
            mints = [m for m in ev.get("mint", []) if m["liquidity"] > 0]
            # status 0x0 means the tx reverted. The bot logs `executed_exit`
            # without checking the receipt, so three rows across T4/T5 record an
            # exit that never happened.
            reverted = str(a.get("status")) in ("0x0", "0")
            burned[a["tx"].lower()] = {
                "block": a.get("block"),
                "status": a.get("status"),
                "reverted": reverted,
                "burns": burns,
                "mints": mints,
                "collects": ev.get("collect", []),
                "real": bool(burns) if a["kind"] == "burn" else bool(mints),
            }

    def exit_really_burned(r: dict) -> bool:
        # `assume_all_exits_burned` keeps the block numbers (they are needed to
        # slice swaps) but ignores whether the tx actually emitted a Burn. That
        # is report 01's pairing, kept switchable so the two can be compared.
        if assume_all_exits_burned or not burned:
            return True
        txs = [t.strip().lower() for t in r["remove_tx_hashes"].split(";") if t.strip()]
        return any(burned.get(t, {}).get("real") for t in txs)

    cycles: list[Cycle] = []
    open_mint: dict | None = None
    pending_orphans: list[dict] = []
    pending_intra: list[dict] = []
    idx = 0

    for r in rows:
        st = r["status"]
        if st == "executed_rebalance":
            open_mint = r
            pending_orphans, pending_intra = [], []
        elif st == "executed_exit" and open_mint is not None:
            if not exit_really_burned(r):
                pending_orphans.append(r)
                continue
            idx += 1
            tx_m = open_mint["create_tx_hash"].strip()
            tx_b = [t.strip() for t in r["remove_tx_hashes"].split(";") if t.strip()]
            c = Cycle(
                idx=idx,
                mint_ts=open_mint["_ts"],
                burn_ts=r["_ts"],
                mint_tx=tx_m,
                burn_tx=tx_b[0] if tx_b else "",
                lower_v3_tick=int(open_mint["applied_tick_lower"]),
                upper_v3_tick=int(open_mint["applied_tick_upper"]),
                recorded_fees_usd=float(r["accumulated_fees_usd"] or 0.0),
                mint_row_wallet_usd=float(open_mint["wallet_usd"] or 0.0),
                burn_row_position_usd=float(r["position_usd"] or 0.0),
                mint_block=burned.get(tx_m.lower(), {}).get("block"),
                burn_block=burned.get(tx_b[0].lower(), {}).get("block") if tx_b else None,
                onchain={
                    "mint": burned.get(tx_m.lower(), {}).get("mints", []),
                    "burn": burned.get(tx_b[0].lower(), {}).get("burns", []) if tx_b else [],
                    "collect": burned.get(tx_b[0].lower(), {}).get("collects", []) if tx_b else [],
                },
                orphan_exits=[
                    {"ts": str(o["_ts"]), "accumulated_fees_usd": float(o["accumulated_fees_usd"] or 0),
                     "tx": o["remove_tx_hashes"]}
                    for o in pending_orphans
                ],
                intra_rows=[
                    {"ts": str(o["_ts"]), "status": o["status"],
                     "accumulated_fees_usd": float(o["accumulated_fees_usd"] or 0),
                     "position_usd": float(o["position_usd"] or 0)}
                    for o in pending_intra
                ],
            )
            cycles.append(c)
            open_mint = None
            pending_orphans, pending_intra = [], []
        elif open_mint is not None and st in ("skipped_dwell_guard", "skipped_hold"):
            pending_intra.append(r)

    # A position still open when the record ends. T5 ends this way: its final
    # exit tx reverted and was never retried inside the window, so the position
    # minted at 02:02 was still live at 05:00. Its fees accrued and are inside
    # `lp_fees_collected_usd`; its IL was never crystallized.
    if open_mint is not None and pending_orphans:
        last = pending_orphans[-1]
        idx += 1
        tx_m = open_mint["create_tx_hash"].strip()
        cycles.append(
            Cycle(
                idx=idx,
                mint_ts=open_mint["_ts"],
                burn_ts=last["_ts"],
                mint_tx=tx_m,
                burn_tx="",
                lower_v3_tick=int(open_mint["applied_tick_lower"]),
                upper_v3_tick=int(open_mint["applied_tick_upper"]),
                recorded_fees_usd=float(last["accumulated_fees_usd"] or 0.0),
                mint_row_wallet_usd=float(open_mint["wallet_usd"] or 0.0),
                burn_row_position_usd=float(last["position_usd"] or 0.0),
                mint_block=burned.get(tx_m.lower(), {}).get("block"),
                burn_block=burned.get(
                    [t.strip().lower() for t in last["remove_tx_hashes"].split(";") if t.strip()][0],
                    {},
                ).get("block"),
                onchain={"mint": burned.get(tx_m.lower(), {}).get("mints", []),
                         "burn": [], "collect": []},
                orphan_exits=[
                    {"ts": str(o["_ts"]),
                     "accumulated_fees_usd": float(o["accumulated_fees_usd"] or 0),
                     "tx": o["remove_tx_hashes"], "reverted": True}
                    for o in pending_orphans
                ],
                intra_rows=[
                    {"ts": str(o["_ts"]), "status": o["status"],
                     "accumulated_fees_usd": float(o["accumulated_fees_usd"] or 0),
                     "position_usd": float(o["position_usd"] or 0)}
                    for o in pending_intra
                ],
                crystallized=False,
            )
        )

    return cycles


# --------------------------------------------------------------------------
# AUM path
# --------------------------------------------------------------------------
def load_aum(trial: int) -> pd.DataFrame:
    f = _trial_file(trial, "aum-history-*.csv")
    df = pd.read_csv(f, encoding="utf-8-sig")
    df["ts"] = pd.to_datetime(df["timestamp"], utc=True, format="ISO8601")
    num = [
        "total_usd", "lp_side_total_usd", "hedge_side_total_usd", "position_usd",
        "wallet_usd", "native_eth_usd", "exchange_equity_usd",
        "perp_position_qty", "perp_position_notional", "perp_unrealized_pnl_usd",
    ]
    for c in num:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values("ts").reset_index(drop=True)


def aum_at(aum: pd.DataFrame, ts, how: str = "after") -> pd.Series | None:
    """AUM snapshot after / before / nearest to `ts`.

    `nearest` matters for funding: report 01 reconstructs it from "the AUM
    snapshot nearest each hour top". Exits fire at :02, so always taking the
    snapshot *after* the hour top systematically catches a just-flattened perp
    and biases the notional path low.
    """
    t = pd.Timestamp(ts)
    if how == "nearest":
        i = (aum["ts"] - t).abs().idxmin()
        return aum.loc[i]
    sel = aum[aum["ts"] >= t] if how == "after" else aum[aum["ts"] <= t]
    if len(sel) == 0:
        return None
    return sel.iloc[0] if how == "after" else sel.iloc[-1]


# --------------------------------------------------------------------------
# Hyperliquid fills
# --------------------------------------------------------------------------
def load_fills(trial: int, tz_correct: bool = True) -> pd.DataFrame:
    """Fills from trade_history.csv, converted UTC+7 -> UTC (issue T)."""
    f = TRIALS_DIR / str(trial) / "trade_history.csv"
    df = pd.read_csv(f)
    naive = pd.to_datetime(df["time"], format="%m/%d/%Y - %H:%M:%S")
    if tz_correct:
        df["ts"] = (
            naive.dt.tz_localize(timezone(timedelta(hours=TRADE_TZ_OFFSET_HOURS)))
            .dt.tz_convert("UTC")
        )
    else:
        df["ts"] = naive.dt.tz_localize("UTC")
    for c in ("px", "sz", "ntl", "fee", "closedPnl"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    # The recorded fee rate is the order-type outcome: the schedule is exactly
    # 1.44 bps maker / 4.32 bps taker and the histogram has no other modes.
    df["fee_bps"] = (df["fee"] / df["ntl"] * 1e4).where(df["ntl"] > 0, 0.0)
    df["is_maker"] = df["fee_bps"] < 3.0
    return df.sort_values("ts").reset_index(drop=True)


def fills_in_window(trial: int, **kw) -> pd.DataFrame:
    w0, w1 = window(trial)
    df = load_fills(trial, **kw)
    return df[(df["ts"] >= w0) & (df["ts"] < w1)].reset_index(drop=True)


# --------------------------------------------------------------------------
# Funding
# --------------------------------------------------------------------------
def load_funding(path: Path | None = None) -> pd.DataFrame:
    p = path or (REVIEW_DATA / "hl_funding_eth_hourly_2026-05-12_to_05-16.csv")
    df = pd.read_csv(p)
    df["ts"] = pd.to_datetime(df["iso_utc"], utc=True, format="ISO8601").dt.floor("h")
    df["funding_rate_hourly"] = pd.to_numeric(df["funding_rate_hourly"])
    return df.sort_values("ts").reset_index(drop=True)


# --------------------------------------------------------------------------
# Binance 1m reference (the price series report 01 used for IL)
# --------------------------------------------------------------------------
def load_binance_1m(trial: int) -> pd.DataFrame:
    f = TRIALS_DIR / str(trial) / "binance_ethusdt_1m.csv"
    df = pd.read_csv(f)
    df["ts"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for c in ("open", "high", "low", "close"):
        df[c] = pd.to_numeric(df[c])
    return df.sort_values("ts").reset_index(drop=True)


def binance_price_at(bn: pd.DataFrame, ts) -> float:
    t = pd.Timestamp(ts)
    prior = bn[bn["ts"] <= t]
    if len(prior) == 0:
        return float(bn["close"].iloc[0])
    return float(prior["close"].iloc[-1])


# --------------------------------------------------------------------------
# On-chain audit (T5 only)
# --------------------------------------------------------------------------
def load_onchain_audit(trial: int) -> dict | None:
    p = TRIALS_DIR / str(trial) / "output" / "data" / "onchain_audit.json"
    return json.loads(p.read_text()) if p.exists() else None


def load_summary(trial: int) -> dict:
    p = TRIALS_DIR / str(trial) / "output" / "data" / "summary.json"
    return json.loads(p.read_text())
