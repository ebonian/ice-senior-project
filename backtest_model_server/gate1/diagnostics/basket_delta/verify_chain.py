#!/usr/bin/env python3
"""E004 step 3 - is the Mint event's amount0 corroborated by independent
chain evidence, or is the engine's chain read wrong?

    nix develop .#gate1 -c python \
        backtest_model_server/gate1/diagnostics/basket_delta/verify_chain.py

The engine takes the LP position's ETH leg straight off the pool's Mint event.
Report 01's derivation implies a different number for T5's breakout cycle. The
pre-registered REFUTED branch is "the Mint event is inconsistent with the
transaction's actual token flows", so this checks the Mint event against a
source that does not share its decoder: the ERC-20 Transfer logs in the same
receipt, which are emitted by the token contracts rather than by the pool.

For a Uniswap V3 mint the pool pulls both tokens from the position manager in
uniswapV3MintCallback, so the receipt must contain a WETH Transfer and a USDC
Transfer into the pool whose values equal the Mint event's amount0/amount1
exactly. Any mismatch is a decoder bug; an exact match means the Mint amounts
are corroborated by two independent contracts in the same atomic transaction.

Read-only JSON-RPC. Writes chain_verification.json next to this file.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
GATE1 = HERE.parent.parent
sys.path.insert(0, str(GATE1))

POOL = "0xc6962004f452be9203591991d15f6b388e09e8d0"
WETH = "0x82af49447d8a07e3bd95bd0d56f35241523fbab1"
USDC = "0xaf88d065e77c8cc2239327c5edb3a432268e5831"
NFPM = "0xc36442b4a4522e871399cd717abdd847ab11fe88"  # NonfungiblePositionManager

TOPIC_TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
TOPIC_MINT = "0x7a53080ba414158be7ec69b987b5fb7d07dee101fe85488f0853ae16239d0bde"
TOPIC_BURN = "0x0c396cd989a39f4459b5fa1aed6a9a8dcdbc45908acfd67e028cd568da98982c"
TOPIC_COLLECT = "0x70935338e69775456a85ddef226c395fb668b63fa0115f5f20610b388e6ca9c0"

DEFAULT_RPC = "https://arb1.arbitrum.io/rpc"

# The cycles under test. T5 cycle 4 is the breakout the gate1 report flags as
# carrying the whole T5 gap; the others are controls.
TARGETS = {
    "5": [
        ("T5 c1 mint", "2026-05-14T05:02:06.849Z"),
        ("T5 c4 mint  <-- BREAKOUT, the flagged cycle", "2026-05-14T14:02:07.282Z"),
        ("T5 c4 burn  <-- BREAKOUT exit", "2026-05-14T16:02:07.031Z"),
    ],
    "4": [
        ("T4 c5 exit  <-- F4 reverted", "2026-05-13T05:02:06"),
        ("T4 c7 exit  <-- F4 reverted", "2026-05-13T10:02:05"),
    ],
}


def rpc_urls() -> list[str]:
    """Every endpoint worth trying, in order. The keyed Alchemy endpoint is
    rate-limited at the moment, so the public node is a real fallback rather
    than a formality; receipts are plain indexed data and any full node serves
    them identically."""
    urls = []
    env_path = Path("/home/poon/developments/llaminet/model/.env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.strip().startswith("ARBITRUM_RPC_URL"):
                urls.append(line.split("=", 1)[1].strip().strip('"').strip("'"))
    if os.environ.get("RPC_URL"):
        urls.append(os.environ["RPC_URL"])
    urls.append(DEFAULT_RPC)
    seen, out = set(), []
    for u in urls:
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def call(urls, method, params, attempts=4):
    """Try each endpoint with backoff. Raises only if all of them fail."""
    last = None
    for attempt in range(attempts):
        for url in urls:
            try:
                r = requests.post(
                    url,
                    json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                    timeout=60,
                )
                if r.status_code == 429:
                    last = f"429 from {url.split('/')[2]}"
                    continue
                r.raise_for_status()
                j = r.json()
                if "error" in j:
                    last = f"{method}: {j['error']}"
                    continue
                return j["result"]
            except Exception as e:  # network flake, try the next endpoint
                last = str(e)
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"all RPC endpoints failed: {last}")


def u256(hexstr: str) -> int:
    return int(hexstr, 16)


def words(data: str) -> list[str]:
    d = data[2:]
    return ["0x" + d[i : i + 64] for i in range(0, len(d), 64)]


def addr(topic: str) -> str:
    return "0x" + topic[-40:].lower()


def decode_receipt(rcpt: dict) -> dict:
    """Pull the pool's Mint/Burn/Collect and every ERC-20 Transfer."""
    out = {"mint": [], "burn": [], "collect": [], "transfers": [], "n_logs": 0}
    if not rcpt:
        return out
    out["n_logs"] = len(rcpt.get("logs", []))
    out["status"] = rcpt.get("status")
    out["block"] = int(rcpt["blockNumber"], 16)
    out["gas_used"] = int(rcpt["gasUsed"], 16)
    for lg in rcpt.get("logs", []):
        a = lg["address"].lower()
        t0 = lg["topics"][0].lower()
        w = words(lg["data"])
        if a == POOL and t0 == TOPIC_MINT:
            out["mint"].append(
                {"liquidity": u256(w[1]), "amount0": u256(w[2]), "amount1": u256(w[3])}
            )
        elif a == POOL and t0 == TOPIC_BURN:
            out["burn"].append(
                {"liquidity": u256(w[0]), "amount0": u256(w[1]), "amount1": u256(w[2])}
            )
        elif a == POOL and t0 == TOPIC_COLLECT:
            out["collect"].append({"amount0": u256(w[1]), "amount1": u256(w[2])})
        elif t0 == TOPIC_TRANSFER and len(lg["topics"]) >= 3:
            out["transfers"].append(
                {
                    "token": a,
                    "token_name": {WETH: "WETH", USDC: "USDC"}.get(a, a[:10]),
                    "from": addr(lg["topics"][1]),
                    "to": addr(lg["topics"][2]),
                    "value": u256(lg["data"]) if lg["data"] not in ("0x", "") else 0,
                    "log_index": int(lg["logIndex"], 16),
                }
            )
    return out


def check(name, ts, action, urls) -> dict:
    rc = call(urls, "eth_getTransactionReceipt", [action["tx"]])
    dec = decode_receipt(rc)

    # Token flows into and out of the pool, by token.
    def net_to_pool(token):
        v = 0
        for t in dec["transfers"]:
            if t["token"] != token:
                continue
            if t["to"] == POOL:
                v += t["value"]
            if t["from"] == POOL:
                v -= t["value"]
        return v

    res = {
        "name": name,
        "ts": ts,
        "tx": action["tx"],
        "status": dec.get("status"),
        "block": dec.get("block"),
        "n_logs": dec["n_logs"],
        "pool_mint": dec["mint"],
        "pool_burn": dec["burn"],
        "pool_collect": dec["collect"],
        "weth_net_into_pool_wei": net_to_pool(WETH),
        "usdc_net_into_pool_units": net_to_pool(USDC),
        "transfers": dec["transfers"],
    }

    checks = []
    if dec["mint"]:
        m = dec["mint"][0]
        d0 = res["weth_net_into_pool_wei"] - m["amount0"]
        d1 = res["usdc_net_into_pool_units"] - m["amount1"]
        checks.append(
            {
                "check": "Mint.amount0 == net WETH Transfer into pool",
                "mint_amount0_wei": m["amount0"],
                "transfer_wei": res["weth_net_into_pool_wei"],
                "diff_wei": d0,
                "match": d0 == 0,
            }
        )
        checks.append(
            {
                "check": "Mint.amount1 == net USDC Transfer into pool",
                "mint_amount1_units": m["amount1"],
                "transfer_units": res["usdc_net_into_pool_units"],
                "diff_units": d1,
                "match": d1 == 0,
            }
        )
    if dec["burn"] and dec["collect"]:
        b, c = dec["burn"][0], dec["collect"][0]
        # On a burn the pool pays out at Collect, not at Burn.
        d0 = -res["weth_net_into_pool_wei"] - c["amount0"]
        d1 = -res["usdc_net_into_pool_units"] - c["amount1"]
        checks.append(
            {
                "check": "Collect.amount0 == net WETH Transfer out of pool",
                "collect_amount0_wei": c["amount0"],
                "transfer_out_wei": -res["weth_net_into_pool_wei"],
                "diff_wei": d0,
                "match": d0 == 0,
            }
        )
        checks.append(
            {
                "check": "Collect.amount1 == net USDC Transfer out of pool",
                "collect_amount1_units": c["amount1"],
                "transfer_out_units": -res["usdc_net_into_pool_units"],
                "diff_units": d1,
                "match": d1 == 0,
            }
        )
        checks.append(
            {
                "check": "Collect >= Burn (fees are the difference)",
                "fee0_wei": c["amount0"] - b["amount0"],
                "fee1_units": c["amount1"] - b["amount1"],
                "match": c["amount0"] >= b["amount0"] and c["amount1"] >= b["amount1"],
            }
        )
    res["checks"] = checks
    return res


def main() -> int:
    urls = rpc_urls()
    print("rpc endpoints: " + ", ".join(u.split("/")[2] for u in urls) + "\n")

    out = {}
    for trial, targets in TARGETS.items():
        actions = json.loads(
            (GATE1 / "data" / "rpc" / f"T{trial}" / "actions.json").read_text()
        )
        by_ts = {a["ts"]: a for a in actions}
        rows = []
        for name, ts in targets:
            act = by_ts.get(ts)
            if act is None:
                # recorder timestamps in actions.json carry ms; match on prefix
                cand = [a for a in actions if a["ts"].startswith(ts[:19])]
                act = cand[0] if cand else None
            if act is None:
                print(f"!! {name}: no action at {ts}")
                continue
            r = check(name, ts, act, urls)
            rows.append(r)

            print("=" * 92)
            print(f"{name}   {ts}")
            print(f"  tx     {r['tx']}")
            print(f"  block  {r['block']}   status {r['status']}   logs {r['n_logs']}")
            if r["pool_mint"]:
                m = r["pool_mint"][0]
                print(f"  pool Mint  amount0 = {m['amount0']} wei = {m['amount0']/1e18:.18f} ETH")
                print(f"             amount1 = {m['amount1']} = {m['amount1']/1e6:.6f} USDC")
                print(f"             liquidity = {m['liquidity']}")
            if r["pool_burn"]:
                b = r["pool_burn"][0]
                print(f"  pool Burn  amount0 = {b['amount0']} wei = {b['amount0']/1e18:.18f} ETH")
                print(f"             amount1 = {b['amount1']} = {b['amount1']/1e6:.6f} USDC")
            if r["pool_collect"]:
                c = r["pool_collect"][0]
                print(f"  pool Collect amount0 = {c['amount0']} wei   amount1 = {c['amount1']}")
            print(f"  ERC-20 Transfers in receipt: {len(r['transfers'])}")
            for t in r["transfers"]:
                tag = ""
                if t["to"] == POOL:
                    tag = "  --> INTO POOL"
                elif t["from"] == POOL:
                    tag = "  <-- OUT OF POOL"
                print(
                    f"    {t['token_name']:<6} {t['from'][:10]}..-> {t['to'][:10]}.. "
                    f"{t['value']}{tag}"
                )
            print("  checks:")
            for c in r["checks"]:
                mark = "PASS" if c["match"] else "FAIL"
                extra = {k: v for k, v in c.items() if k not in ("check", "match")}
                print(f"    [{mark}] {c['check']}")
                print(f"           {extra}")
            print()
        out[trial] = rows

    (HERE / "chain_verification.json").write_text(json.dumps(out, indent=2))
    allc = [c for rows in out.values() for r in rows for c in r["checks"]]
    n_fail = sum(1 for c in allc if not c["match"])
    print("=" * 92)
    print(f"{len(allc) - n_fail}/{len(allc)} independent-evidence checks passed")
    print(f"wrote {HERE / 'chain_verification.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
