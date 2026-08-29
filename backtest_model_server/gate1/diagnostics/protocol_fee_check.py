"""Does the pool take a Uniswap V3 protocol fee, and did it during the trials?

`UniswapV3Pool.slot0()` returns `feeProtocol`, packed as two 4-bit denominators
(token0 low nibble, token1 high nibble). A value of n means 1/n of the swap fee
is skimmed for the protocol and only the remainder accrues to LPs. n = 4 leaves
LPs 75% of the 5 bps — the shape of a uniform 0.75x factor on every modelled
cycle fee.

The public RPC serves log archive but not state archive at May depth, so the
current value comes from `slot0()` at head and the history comes from the
`SetFeeProtocol` event, which needs only logs.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.b2 import read_env  # noqa: E402
from engine.rpc import ArbRPC, POOL  # noqa: E402

SLOT0 = "0x3850c7bd"
FEE = "0xddca3f43"
# keccak256("SetFeeProtocol(uint8,uint8,uint8,uint8)")
TOPIC_SET_FEE_PROTOCOL = (
    "0x973d8d92bb299f4af6ce49b52a8adb85ae46b9f214c4c4fc06ac77401237b133"
)

pub = ArbRPC("https://arb1.arbitrum.io/rpc")


def show_slot0(rpc, tag, label):
    res = rpc.call("eth_call", [{"to": POOL, "data": SLOT0}, tag])
    d = res[2:]
    w = [d[i : i + 64] for i in range(0, len(d), 64)]
    sqrtp = int(w[0], 16)
    fp = int(w[5], 16)
    lo, hi = fp % 16, fp >> 4
    price = (sqrtp / 2**96) ** 2 * 1e12
    print(f"{label:26s} price={price:10.2f} feeProtocol=0x{fp:02x} "
          f"(token0 denom={lo}, token1 denom={hi})")
    if lo or hi:
        print(f"    -> LPs receive {(1-1/lo)*100 if lo else 100:.1f}% of token0 fees, "
              f"{(1-1/hi)*100 if hi else 100:.1f}% of token1 fees")
    return fp


print("--- current state (public RPC, head) ---")
show_slot0(pub, "latest", "pool @ latest")
fee = pub.call("eth_call", [{"to": POOL, "data": FEE}, "latest"])
print(f"pool fee tier: {int(fee, 16)} (hundredths of a bip; 500 == 5 bps)\n")

print("--- SetFeeProtocol history (logs only, trial-era window) ---")
# A full-chain scan is ~10k getLogs calls. The question is only what the value
# was during the trials, so scan the blocks around them.
logs = pub.get_logs(460_000_000, 465_000_000, TOPIC_SET_FEE_PROTOCOL)
if not logs:
    print("no SetFeeProtocol events found on this pool over the scanned range")
else:
    for lg in logs:
        d = lg["data"][2:]
        w = [d[i : i + 64] for i in range(0, len(d), 64)]
        old0, old1, new0, new1 = (int(x, 16) for x in w[:4])
        print(f"  block {int(lg['blockNumber'],16):,}: "
              f"feeProtocol0 {old0}->{new0}, feeProtocol1 {old1}->{new1}")

print("\n--- archive state via the configured RPC, if it will serve May ---")
try:
    env = read_env()
    alch = ArbRPC(env["ARBITRUM_RPC_URL"])
    for label, blk in [("T5 cycle 6 mint", 462848362), ("T5 window end", 462963448)]:
        show_slot0(alch, hex(blk), label)
except Exception as e:
    print(f"unavailable: {type(e).__name__}: {str(e)[:160]}")
