#!/usr/bin/env python3
"""E010 candidate discovery: resolve the M004 §3 set on mainnet and Base.

    nix develop .#gate1 -c python backtest_model_server/e010/discover10.py

e005/discover.py's process, chain-parameterized. Per candidate: factory
`getPool` resolution, token verification, slot0 protocol-fee read PLUS a
cross-check of the same read against a second independent RPC provider
(E010 validity gate ii), a SetFeeProtocol event scan over
[window_start_block, head] with piecewise fee-share schedule, HL perp
existence, and — for probe-role candidates — the 10-spread-day swap-count
sample that decides raced-or-INELIGIBLE-thin (e005's F4 sampling rule).

Writes out/candidates.json in the e005 row schema (+ "chain" and
"fee_protocol_crosscheck" fields) so the race's spec loader ports unchanged.
Nothing here judges the hypothesis; it is validity metadata.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

E010 = Path(__file__).resolve().parent
BMS = E010.parent
for p in (str(BMS / "gate1"), str(BMS / "e005"), str(E010)):
    if p not in sys.path:
        sys.path.insert(0, p) if "e010" not in p else sys.path.append(p)

import registry as R  # noqa: E402
import keccak as K  # noqa: E402  (e005's self-tested keccak)
import discover as D5  # noqa: E402  (e005 helpers: token_info, pool_state, ...)
from engine.rpc import ArbRPC, TOPIC_SWAP  # noqa: E402

TOPIC_SET_FEE_PROTOCOL = K.event_topic("SetFeeProtocol(uint8,uint8,uint8,uint8)")
SEL_GETPOOL = K.selector("getPool(address,address,uint24)")


def get_pool(rpc: ArbRPC, factory: str, a: str, b: str, fee: int) -> str | None:
    ret = D5.eth_call(rpc, factory,
                      SEL_GETPOOL + D5.enc_addr(a) + D5.enc_addr(b) + D5.enc_u(fee))
    addr = "0x" + ret[-40:]
    return None if int(addr, 16) == 0 else addr.lower()


def set_fee_protocol_events(rpc: ArbRPC, pool: str, b0: int, head: int) -> list[dict]:
    """Every SetFeeProtocol on `pool` in [b0, head]; large spans, halve on
    rejection (e005's scan with the window passed in)."""
    out = []
    stack = [(b0, head)]
    span = 2_000_000
    while stack:
        lo, hi = stack.pop(0)
        if hi - lo + 1 > span:
            mid = lo + span - 1
            stack.insert(0, (mid + 1, hi))
            hi = mid
        try:
            logs = rpc.call("eth_getLogs", [{
                "address": pool, "fromBlock": hex(lo), "toBlock": hex(hi),
                "topics": [TOPIC_SET_FEE_PROTOCOL]}], tries=3)
        except Exception:
            if hi - lo < 50_000:
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


def fee_share_schedule(state: dict, events: list[dict],
                       b0: int, b1: int) -> list[dict]:
    """Piecewise lp_fee_share over [b0, b1] (e005's logic, window passed in)."""
    inw = [e for e in events if e["block"] <= b1]
    if not inw:
        share = D5.lp_fee_share_of(state["fee_protocol0_now"],
                                   state["fee_protocol1_now"])
        return [{"from_block": b0, "to_block": b1,
                 "fp0": state["fee_protocol0_now"],
                 "fp1": state["fee_protocol1_now"], "lp_fee_share": share}]
    segs = []
    cur_b = b0
    fp0, fp1 = inw[0]["feeProtocol0Old"], inw[0]["feeProtocol1Old"]
    for e in inw:
        if e["block"] > cur_b:
            segs.append({"from_block": cur_b, "to_block": e["block"] - 1,
                         "fp0": fp0, "fp1": fp1,
                         "lp_fee_share": D5.lp_fee_share_of(fp0, fp1)})
        cur_b, fp0, fp1 = e["block"], e["feeProtocol0New"], e["feeProtocol1New"]
    segs.append({"from_block": cur_b, "to_block": b1, "fp0": fp0, "fp1": fp1,
                 "lp_fee_share": D5.lp_fee_share_of(fp0, fp1)})
    return segs


def sample_days(rpc: ArbRPC, pool: str, mb: dict, n_days: int = 10) -> list[int]:
    """Swap counts on n spread days (e005's F4 sampling, chain month blocks)."""
    import pandas as pd
    t0 = pd.Timestamp(R.WINDOW_START, tz="UTC")
    t1 = pd.Timestamp(R.WINDOW_END, tz="UTC")
    counts = []
    for k in range(n_days):
        day = (t0 + (t1 - t0) * ((k + 0.5) / n_days)).normalize()
        lab = day.strftime("%Y-%m")
        b0, b1 = mb[lab]
        m0 = day.replace(day=1)
        m1 = min(m0 + pd.offsets.MonthBegin(1), t1)
        f0 = (day - m0) / (m1 - m0)
        f1 = (day + pd.Timedelta(days=1) - m0) / (m1 - m0)
        blk0 = b0 + int((b1 - b0 + 1) * f0)
        blk1 = min(b0 + int((b1 - b0 + 1) * f1) - 1, b1)
        n = 0
        stack = [(blk0, blk1)]
        span = 10_000
        while stack:
            lo, hi = stack.pop(0)
            if hi - lo + 1 > span:
                mid = lo + span - 1
                stack.insert(0, (mid + 1, hi))
                hi = mid
            try:
                logs = rpc.call("eth_getLogs", [{
                    "address": pool, "fromBlock": hex(lo), "toBlock": hex(hi),
                    "topics": [TOPIC_SWAP]}], tries=3)
            except Exception:
                if hi - lo < 1_000:
                    raise
                mid = (lo + hi) // 2
                stack.insert(0, (mid + 1, hi))
                stack.insert(0, (lo, mid))
                time.sleep(1.0)
                continue
            n += len(logs)
        counts.append(n)
        time.sleep(0.2)
    return counts


def main() -> int:
    out = {"generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "experiment": "E010",
           "window": [R.WINDOW_START, R.WINDOW_END],
           "chains": {}, "candidates": []}

    print("== hyperliquid universe ==")
    uni = D5.hl_universe()
    need = sorted({R.HL_COIN[s] for ch in R.TOKENS.values() for s in ch
                   if s not in R.STABLES})
    perps = {c: uni.get(c) for c in need}
    for c in need:
        ok = perps[c] and not perps[c]["delisted"]
        print(f"  {c:>5s} {'LIVE' if ok else 'MISSING/DELISTED'}")
    out["hl_perps"] = perps

    clients: dict[str, tuple[ArbRPC, ArbRPC, ArbRPC]] = {}
    for chain in ("mainnet", "base"):
        ch = R.CHAINS[chain]
        state = ArbRPC(ch["state_rpc"][0])
        state2 = ArbRPC(ch["state_rpc"][1])   # independent provider, gate (ii)
        logs = ArbRPC(ch["logs_rpc"][0])
        mb = R.month_blocks(chain)
        head = state.block_number()
        out["chains"][chain] = {
            "factory": ch["factory"], "month_blocks": {k: list(v) for k, v in mb.items()},
            "window_blocks": [mb["2026-05"][0], mb["2026-08"][1]],
            "state_rpc": ch["state_rpc"], "logs_rpc": ch["logs_rpc"][0],
            "head_at_discovery": head}
        clients[chain] = (state, state2, logs)

    print("== token verification ==")
    tokens_ok = {}
    for chain, toks in R.TOKENS.items():
        state = clients[chain][0]
        for sym, (addr, dec) in toks.items():
            info = D5.token_info(state, addr)
            info.update({"chain": chain, "expected_symbol": sym,
                         "expected_decimals": dec,
                         "ok": info.get("decimals_onchain") == dec})
            tokens_ok[f"{chain}:{sym}"] = info
            print(f"  {chain:>7s} {sym:>7s} {info.get('symbol_onchain','?'):>8s} "
                  f"dec {info.get('decimals_onchain','?')} ok={info['ok']}")
            if not info["ok"]:
                raise SystemExit(f"token verification failed: {chain}:{sym}")
    out["tokens"] = tokens_ok

    print("== candidates ==")
    for c in R.CANDIDATES:
        state, state2, logs = clients[c.chain]
        ch = R.CHAINS[c.chain]
        mb = R.month_blocks(c.chain)
        wb0, wb1 = mb["2026-05"][0], mb["2026-08"][1]
        row = {"slug": c.slug, "chain": c.chain, "family": c.family,
               "role": c.role, "pair": f"{c.tokenA}/{c.tokenB}", "fee": c.fee}
        ta = R.TOKENS[c.chain][c.tokenA][0]
        tb = R.TOKENS[c.chain][c.tokenB][0]
        addr = get_pool(state, ch["factory"], ta, tb, c.fee)
        if addr is None:
            row["status"] = "NO-POOL"
            out["candidates"].append(row)
            print(f"  {c.slug:>20s}  NO-POOL")
            continue
        st = D5.pool_state(state, addr)
        st2 = D5.pool_state(state2, addr)
        xcheck = {"provider_a": state.url, "provider_b": state2.url,
                  "fee_protocol_a": st["fee_protocol_now"],
                  "fee_protocol_b": st2["fee_protocol_now"],
                  "match": st["fee_protocol_now"] == st2["fee_protocol_now"]}
        if not xcheck["match"]:
            raise SystemExit(f"{c.slug}: feeProtocol cross-check FAILED {xcheck}")
        logs.pool = addr
        ev = set_fee_protocol_events(logs, addr, wb0, state.block_number())
        sched = fee_share_schedule(st, ev, wb0, wb1)
        t0sym = c.tokenA if st["token0"] == ta.lower() else c.tokenB
        t1sym = c.tokenB if t0sym == c.tokenA else c.tokenA
        legs = {}
        for pos, sym in (("token0", t0sym), ("token1", t1sym)):
            if sym in R.STABLES:
                legs[pos] = {"symbol": sym, "hedge": "stable-unhedged"}
            elif sym in R.ETH_BETA_TOKENS:
                legs[pos] = {"symbol": sym, "hedge": "eth-beta", "hl_coin": "ETH"}
            else:
                coin = R.HL_COIN[sym]
                live = perps.get(coin) and not perps[coin]["delisted"]
                legs[pos] = {"symbol": sym, "hedge": "perp" if live else "NO-PERP",
                             "hl_coin": coin}
        no_perp = any(v.get("hedge") == "NO-PERP" for v in legs.values())
        row.update({
            "status": "NO-PERP" if no_perp else "RESOLVED",
            "address": addr, "token0_symbol": t0sym, "token1_symbol": t1sym,
            "decimals0": R.TOKENS[c.chain][t0sym][1],
            "decimals1": R.TOKENS[c.chain][t1sym][1],
            "pool_state": st, "fee_protocol_crosscheck": xcheck,
            "set_fee_protocol_events": ev,
            "lp_fee_share_schedule": sched, "legs": legs,
        })
        if c.role == "probe" and not no_perp:
            counts = sample_days(logs, addr, mb)
            med = sorted(counts)[len(counts) // 2]
            row["sampled_day_counts"] = counts
            row["sampled_median_per_day"] = med
            if med < R.MIN_MEDIAN_SWAPS_PER_DAY:
                row["status"] = "INELIGIBLE-thin"
        out["candidates"].append(row)
        shares = sorted({s["lp_fee_share"] for s in sched})
        print(f"  {c.slug:>20s}  {addr}  t0={t0sym} t1={t1sym} "
              f"spacing={st['tick_spacing']} feeProt=0x{st['fee_protocol_now']:02x} "
              f"share={shares} ev_inwin="
              f"{len([e for e in ev if e['block'] <= wb1])} "
              f"status={row['status']}"
              + (f" med/day~{row.get('sampled_median_per_day')}"
                 if "sampled_median_per_day" in row else ""), flush=True)

    (E010 / "out").mkdir(exist_ok=True)
    (E010 / "out" / "candidates.json").write_text(json.dumps(out, indent=2))
    calls = sum(cl.calls for trio in clients.values() for cl in trio)
    print(f"wrote out/candidates.json  ({calls} rpc calls)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
