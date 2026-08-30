#!/usr/bin/env python3
"""E005 candidate discovery and eligibility metadata.

    nix develop .#gate1 -c python backtest_model_server/e005/discover.py

Resolves every pre-registered candidate through the Uniswap V3 factory,
verifies token contracts, reads each pool's protocol-fee state (slot0 +
SetFeeProtocol events over the window — issue W is why), checks Hyperliquid
perp existence, and runs the F4 discovery sampling. Writes
`out/candidates.json` with one row per candidate INCLUDING screened-out ones
(NO-POOL / NO-PERP rows are recorded here; INELIGIBLE-thin and DATA-FAIL are
decided later, after full fetches, by coverage + tables).

Nothing here judges the hypothesis; it is validity metadata.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

E005 = Path(__file__).resolve().parent
sys.path.insert(0, str(E005))
import pools as P  # noqa: E402
import keccak as K  # noqa: E402

GATE1 = E005.parent / "gate1"
sys.path.insert(0, str(GATE1))
from engine.rpc import ArbRPC, TOPIC_SWAP  # noqa: E402

SEL_GETPOOL = K.selector("getPool(address,address,uint24)")
SEL_SLOT0 = K.selector("slot0()")
SEL_DECIMALS = K.selector("decimals()")
SEL_SYMBOL = K.selector("symbol()")
SEL_TICKSPACING = K.selector("tickSpacing()")
SEL_FEE = K.selector("fee()")
SEL_TOKEN0 = K.selector("token0()")
SEL_TOKEN1 = K.selector("token1()")
SEL_LIQUIDITY = K.selector("liquidity()")
TOPIC_SET_FEE_PROTOCOL = K.event_topic("SetFeeProtocol(uint8,uint8,uint8,uint8)")

WINDOW_B0 = P.MONTH_BLOCKS["2026-05"][0]
WINDOW_B1 = P.MONTH_BLOCKS["2026-08"][1]


def eth_call(rpc: ArbRPC, to: str, data: str) -> str:
    return rpc.call("eth_call", [{"to": to, "data": data}, "latest"])


def enc_addr(a: str) -> str:
    return a.lower().replace("0x", "").rjust(64, "0")


def enc_u(v: int) -> str:
    return hex(v)[2:].rjust(64, "0")


def dec_string(ret: str) -> str:
    """ABI string OR bytes32 symbol (MKR-style)."""
    raw = bytes.fromhex(ret[2:])
    if len(raw) == 32:
        return raw.rstrip(b"\x00").decode("ascii", "replace")
    ln = int.from_bytes(raw[32:64], "big")
    return raw[64:64 + ln].decode("utf-8", "replace")


def token_info(rpc: ArbRPC, addr: str) -> dict:
    sym = dec_string(eth_call(rpc, addr, SEL_SYMBOL))
    dec = int(eth_call(rpc, addr, SEL_DECIMALS), 16)
    return {"address": addr.lower(), "symbol_onchain": sym, "decimals_onchain": dec}


def get_pool(rpc: ArbRPC, a: str, b: str, fee: int) -> str | None:
    ret = eth_call(rpc, P.FACTORY, SEL_GETPOOL + enc_addr(a) + enc_addr(b) + enc_u(fee))
    addr = "0x" + ret[-40:]
    return None if int(addr, 16) == 0 else addr.lower()


def pool_state(rpc: ArbRPC, pool: str) -> dict:
    s0 = eth_call(rpc, pool, SEL_SLOT0)
    words = [s0[2 + i * 64: 2 + (i + 1) * 64] for i in range(7)]
    tick = int(words[1], 16)
    if tick >= 1 << 255:
        tick -= 1 << 256
    fee_protocol = int(words[5], 16)
    return {
        "token0": ("0x" + eth_call(rpc, pool, SEL_TOKEN0)[-40:]).lower(),
        "token1": ("0x" + eth_call(rpc, pool, SEL_TOKEN1)[-40:]).lower(),
        "fee": int(eth_call(rpc, pool, SEL_FEE), 16),
        "tick_spacing": int(eth_call(rpc, pool, SEL_TICKSPACING), 16),
        "liquidity_now": int(eth_call(rpc, pool, SEL_LIQUIDITY), 16),
        "slot0_tick_now": tick,
        "fee_protocol_now": fee_protocol,
        "fee_protocol0_now": fee_protocol % 16,
        "fee_protocol1_now": fee_protocol >> 4,
    }


def set_fee_protocol_events(rpc: ArbRPC, pool: str) -> list[dict]:
    """Every SetFeeProtocol on this pool in [window_start, head]. Rare event,
    so large spans; halve on rejection."""
    head = rpc.block_number()
    out = []
    stack = [(WINDOW_B0, head)]
    span = 5_000_000
    while stack:
        lo, hi = stack.pop(0)
        if hi - lo + 1 > span:
            mid = lo + span - 1
            stack.insert(0, (mid + 1, hi))
            hi = mid
        try:
            logs = rpc.call("eth_getLogs", [{
                "address": pool, "fromBlock": hex(lo), "toBlock": hex(hi),
                "topics": [TOPIC_SET_FEE_PROTOCOL]}])
        except Exception:
            if hi - lo < 100_000:
                raise
            mid = (lo + hi) // 2
            stack.insert(0, (mid + 1, hi))
            stack.insert(0, (lo, mid))
            time.sleep(1.0)
            continue
        for lg in logs:
            d = lg["data"][2:]
            w = [int(d[i * 64:(i + 1) * 64], 16) for i in range(4)]
            out.append({"block": int(lg["blockNumber"], 16),
                        "feeProtocol0Old": w[0], "feeProtocol1Old": w[1],
                        "feeProtocol0New": w[2], "feeProtocol1New": w[3]})
    return sorted(out, key=lambda e: e["block"])


def lp_fee_share_of(fp0: int, fp1: int) -> float:
    s0 = 1.0 - (1.0 / fp0 if fp0 else 0.0)
    s1 = 1.0 - (1.0 / fp1 if fp1 else 0.0)
    return (s0 + s1) / 2.0


def fee_share_schedule(state: dict, events: list[dict]) -> list[dict]:
    """Piecewise lp_fee_share over the window. With no in-window events the
    current slot0 value extends back across the whole window (any change since
    window start would have logged an event in [window_b0, head])."""
    segs = []
    if not [e for e in events if e["block"] <= WINDOW_B1]:
        share = lp_fee_share_of(state["fee_protocol0_now"], state["fee_protocol1_now"])
        return [{"from_block": WINDOW_B0, "to_block": WINDOW_B1,
                 "fp0": state["fee_protocol0_now"], "fp1": state["fee_protocol1_now"],
                 "lp_fee_share": share}]
    inw = [e for e in events if e["block"] <= WINDOW_B1]
    cur_b = WINDOW_B0
    fp0, fp1 = inw[0]["feeProtocol0Old"], inw[0]["feeProtocol1Old"]
    for e in inw:
        if e["block"] > cur_b:
            segs.append({"from_block": cur_b, "to_block": e["block"] - 1,
                         "fp0": fp0, "fp1": fp1,
                         "lp_fee_share": lp_fee_share_of(fp0, fp1)})
        cur_b, fp0, fp1 = e["block"], e["feeProtocol0New"], e["feeProtocol1New"]
    segs.append({"from_block": cur_b, "to_block": WINDOW_B1, "fp0": fp0, "fp1": fp1,
                 "lp_fee_share": lp_fee_share_of(fp0, fp1)})
    return segs


def hl_universe() -> dict:
    r = requests.post("https://api.hyperliquid.xyz/info", json={"type": "meta"},
                      timeout=30)
    r.raise_for_status()
    u = r.json()["universe"]
    return {a["name"]: {"delisted": bool(a.get("isDelisted", False))} for a in u}


# --- F4 discovery sampling --------------------------------------------------
def block_at_day(day_frac: float) -> tuple[int, int]:
    """Approximate block range of one sample day, `day_frac` through the
    window, by linear interpolation inside the containing month."""
    import pandas as pd
    t0 = pd.Timestamp(P.WINDOW_START, tz="UTC")
    t1 = pd.Timestamp(P.WINDOW_END, tz="UTC")
    day = t0 + (t1 - t0) * day_frac
    day = day.normalize()
    lab = day.strftime("%Y-%m")
    b0, b1 = P.MONTH_BLOCKS[lab]
    m0 = day.replace(day=1)
    m1 = min(m0 + pd.offsets.MonthBegin(1), t1)
    frac0 = (day - m0) / (m1 - m0)
    frac1 = (day + pd.Timedelta(days=1) - m0) / (m1 - m0)
    blk0 = b0 + int((b1 - b0 + 1) * frac0)
    blk1 = min(b0 + int((b1 - b0 + 1) * frac1) - 1, b1)
    return blk0, blk1


def count_swaps(rpc: ArbRPC, pool: str, b0: int, b1: int) -> int:
    n = 0
    stack = [(b0, b1)]
    span = 120_000
    while stack:
        lo, hi = stack.pop(0)
        if hi - lo + 1 > span:
            mid = lo + span - 1
            stack.insert(0, (mid + 1, hi))
            hi = mid
        try:
            logs = rpc.call("eth_getLogs", [{
                "address": pool, "fromBlock": hex(lo), "toBlock": hex(hi),
                "topics": [TOPIC_SWAP]}])
        except Exception:
            if hi - lo < 10_000:
                raise
            mid = (lo + hi) // 2
            stack.insert(0, (mid + 1, hi))
            stack.insert(0, (lo, mid))
            time.sleep(1.0)
            continue
        n += len(logs)
    return n


def main() -> int:
    rpc = ArbRPC(P.RPC_URL)
    out = {"generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "factory": P.FACTORY, "window_blocks": [WINDOW_B0, WINDOW_B1],
           "rpc": P.RPC_URL}

    print("== token verification ==")
    tokens = {}
    for sym, (addr, dec) in {**P.TOKENS, **P.DISCOVERY_TOKENS}.items():
        try:
            info = token_info(rpc, addr)
        except Exception as e:
            info = {"address": addr.lower(), "error": str(e)[:120]}
        info["expected_symbol"] = sym
        info["expected_decimals"] = dec
        info["ok"] = (info.get("decimals_onchain") == dec)
        tokens[sym] = info
        print(f"  {sym:>7s} {info.get('symbol_onchain','?'):>8s} "
              f"dec {info.get('decimals_onchain','?')} ok={info['ok']}")
    out["tokens"] = tokens

    print("== hyperliquid universe ==")
    uni = hl_universe()
    need = sorted({P.HL_COIN.get(s, s) for s in
                   list(P.TOKENS) + list(P.DISCOVERY_TOKENS) if s not in P.STABLES})
    perps = {c: uni.get(c) for c in need}
    for c in need:
        print(f"  {c:>7s} {'LIVE' if perps[c] and not perps[c]['delisted'] else 'MISSING/DELISTED'}")
    out["hl_perps"] = perps

    print("== pre-registered candidates ==")
    rows = []
    for c in P.CANDIDATES:
        row = {"slug": c.slug, "family": c.family, "pair": f"{c.tokenA}/{c.tokenB}",
               "fee": c.fee, "tick_spacing_expected": c.tick_spacing}
        ta, tb = P.TOKENS[c.tokenA][0], P.TOKENS[c.tokenB][0]
        addr = get_pool(rpc, ta, tb, c.fee)
        if addr is None:
            row["status"] = "NO-POOL"
            rows.append(row)
            print(f"  {c.slug:>18s}  NO-POOL")
            continue
        st = pool_state(rpc, addr)
        ev = set_fee_protocol_events(rpc, addr)
        sched = fee_share_schedule(st, ev)
        t0sym = c.tokenA if st["token0"] == ta.lower() else c.tokenB
        t1sym = c.tokenB if t0sym == c.tokenA else c.tokenA
        legs = {}
        for pos, sym in (("token0", t0sym), ("token1", t1sym)):
            if sym in P.STABLES:
                legs[pos] = {"symbol": sym, "hedge": "stable-unhedged"}
            elif sym in P.ETH_BETA_TOKENS:
                legs[pos] = {"symbol": sym, "hedge": "eth-beta", "hl_coin": "ETH"}
            else:
                coin = P.HL_COIN[sym]
                live = perps.get(coin) and not perps[coin]["delisted"]
                legs[pos] = {"symbol": sym, "hedge": "perp" if live else "NO-PERP",
                             "hl_coin": coin}
        no_perp = any(v.get("hedge") == "NO-PERP" for v in legs.values())
        row.update({
            "status": "NO-PERP" if no_perp else "RESOLVED",
            "address": addr, "token0_symbol": t0sym, "token1_symbol": t1sym,
            "decimals0": P.TOKENS[t0sym][1], "decimals1": P.TOKENS[t1sym][1],
            "pool_state": st, "set_fee_protocol_events": ev,
            "lp_fee_share_schedule": sched, "legs": legs,
        })
        rows.append(row)
        print(f"  {c.slug:>18s}  {addr}  t0={t0sym} t1={t1sym} "
              f"spacing={st['tick_spacing']} feeProt=0x{st['fee_protocol_now']:02x} "
              f"share={sched[0]['lp_fee_share']:.4f} ev={len(ev)} "
              f"{'NO-PERP' if no_perp else ''}")
    out["candidates"] = rows

    print("== F4 discovery sampling ==")
    n_days = 10
    fracs = [(i + 0.5) / n_days for i in range(n_days)]
    cache = {}
    prev_f = E005 / "out" / "candidates.json"
    if prev_f.exists():
        for d in json.loads(prev_f.read_text()).get("discovery", []):
            if "sampled_day_counts" in d:
                cache[(d["token"], d["quote"], d["fee"])] = d["sampled_day_counts"]
    listed = {r.get("address") for r in rows if r.get("address")}
    disc = []
    for sym, (addr, dec) in P.DISCOVERY_TOKENS.items():
        coin = P.HL_COIN.get(sym, sym)
        live = perps.get(coin) and not perps[coin]["delisted"]
        for quote in ("WETH", "USDC"):
            for fee in (500, 3000):
                d = {"token": sym, "quote": quote, "fee": fee, "hl_coin": coin,
                     "hl_perp_live": bool(live)}
                if not live:
                    d["status"] = "NO-PERP"
                    disc.append(d)
                    continue
                paddr = get_pool(rpc, addr, P.TOKENS[quote][0], fee)
                if paddr is None:
                    d["status"] = "NO-POOL"
                    disc.append(d)
                    continue
                if paddr in listed:
                    d["status"] = "ALREADY-LISTED"
                    d["address"] = paddr
                    disc.append(d)
                    continue
                counts = cache.get((sym, quote, fee))
                if counts is None:
                    counts = []
                    for fr in fracs:
                        b0, b1 = block_at_day(fr)
                        counts.append(count_swaps(rpc, paddr, b0, b1))
                counts_sorted = sorted(counts)
                med = counts_sorted[len(counts) // 2]
                d.update({"status": "SAMPLED", "address": paddr,
                          "sampled_day_counts": counts, "sampled_median_per_day": med})
                disc.append(d)
                print(f"  {sym}/{quote} {fee}  {paddr}  median/day~{med}  {counts}")
    out["discovery"] = disc

    sampled = [d for d in disc if d.get("status") == "SAMPLED"]
    sampled.sort(key=lambda d: -d["sampled_median_per_day"])
    chosen = [d for d in sampled if d["sampled_median_per_day"] >= P.MIN_MEDIAN_SWAPS_PER_DAY][:2]
    out["discovered_pools"] = chosen
    for i, d in enumerate(chosen):
        addr = d["address"]
        st = pool_state(rpc, addr)
        ev = set_fee_protocol_events(rpc, addr)
        sched = fee_share_schedule(st, ev)
        tsym, qsym = d["token"], d["quote"]
        taddr = P.DISCOVERY_TOKENS[tsym][0].lower()
        t0sym = tsym if st["token0"] == taddr else qsym
        t1sym = qsym if t0sym == tsym else tsym
        dec = {**{k: v[1] for k, v in P.TOKENS.items()},
               **{k: v[1] for k, v in P.DISCOVERY_TOKENS.items()}}
        legs = {}
        for pos, sym2 in (("token0", t0sym), ("token1", t1sym)):
            if sym2 in P.STABLES:
                legs[pos] = {"symbol": sym2, "hedge": "stable-unhedged"}
            else:
                legs[pos] = {"symbol": sym2, "hedge": "perp",
                             "hl_coin": P.HL_COIN.get(sym2, sym2)}
        slug = f"{tsym.lower()}_{qsym.lower()}_0p{'05' if d['fee'] == 500 else '30'}"
        row = {"slug": slug, "family": "F4-discovered",
               "pair": f"{tsym}/{qsym}", "fee": d["fee"],
               "status": "RESOLVED", "address": addr,
               "token0_symbol": t0sym, "token1_symbol": t1sym,
               "decimals0": dec[t0sym], "decimals1": dec[t1sym],
               "pool_state": st, "set_fee_protocol_events": ev,
               "lp_fee_share_schedule": sched, "legs": legs,
               "sampled_median_per_day": d["sampled_median_per_day"]}
        rows.append(row)
        chosen[i] = {**d, "slug": slug}
        print(f"  DISCOVERED: {slug} -> {addr} share={sched[0]['lp_fee_share']:.4f} ev={len(ev)}")
    for d in sampled:
        if d not in chosen:
            d["status"] = "SAMPLED-NOT-CHOSEN"

    (E005 / "out").mkdir(exist_ok=True)
    (E005 / "out" / "candidates.json").write_text(json.dumps(out, indent=2))
    print(f"wrote out/candidates.json  ({rpc.calls} rpc calls)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
