"""What did the final T5 'executed_exit' tx actually do?

The rebalance-history row at 2026-05-15T04:02:04 is logged `executed_exit` with a
remove tx hash, but its receipt emits no pool Mint/Burn/Collect, and the AUM path
still shows ~$904 of position value 54 minutes later. Same shape as T4's two
unpaired exits.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.rpc import ArbRPC, POOL

RPC = "https://arb1.arbitrum.io/rpc"
r = ArbRPC(RPC)

CASES = [
    ("T5 final exit 05-15T04:02:04", "0xb23a2565e6bc"),
]

import csv, glob, json

TRIALS = Path("/home/poon/developments/llaminet/bot/analysis/trials")


def full_hashes(trial, prefixes):
    f = glob.glob(str(TRIALS / str(trial) / "rebalance-history-*.csv"))[0]
    out = {}
    for row in csv.DictReader(open(f, encoding="utf-8-sig")):
        for h in [row["create_tx_hash"]] + row["remove_tx_hashes"].split(";"):
            h = h.strip()
            if h and any(h.lower().startswith(p) for p in prefixes):
                out[h] = row["timestamp"]
    return out


targets = {}
targets.update(full_hashes(5, ["0xb23a2565e6bc"]))
targets.update(full_hashes(4, ["0x4c731432aaf1", "0x8eb3f2c68107",
                               "0x88dd8ddfc607", "0x57863d0b4330",
                               "0x8f821807dcbb", "0x13621f392513"]))

for tx, ts in sorted(targets.items(), key=lambda kv: kv[1]):
    rc = r.receipt(tx)
    if rc is None:
        print(f"{ts[:19]} {tx[:14]} -> RECEIPT NOT FOUND")
        continue
    status = int(rc["status"], 16)
    logs = rc.get("logs", [])
    pool_logs = [lg for lg in logs if lg["address"].lower() == POOL]
    ev = r.pool_events_in_receipt(rc)
    print(
        f"{ts[:19]} {tx[:14]} status={status} gasUsed={int(rc['gasUsed'],16)} "
        f"logs={len(logs)} pool_logs={len(pool_logs)} "
        f"mint={len(ev['mint'])} burn={len(ev['burn'])} collect={len(ev['collect'])}"
    )
    for lg in pool_logs:
        print(f"    pool topic0={lg['topics'][0][:12]}...")
    if ev["burn"]:
        b = ev["burn"][0]
        print(f"    BURN tl={b['tick_lower']} tu={b['tick_upper']} L={b['liquidity']} "
              f"a0={b['amount0']/1e18:.6f} a1={b['amount1']/1e6:.2f}")
    if ev["collect"]:
        c = ev["collect"][0]
        print(f"    COLLECT a0={c['amount0']/1e18:.6f} a1={c['amount1']/1e6:.2f}")
    # what contract did it hit?
    print(f"    to={rc.get('to')} from={rc.get('from')}")
