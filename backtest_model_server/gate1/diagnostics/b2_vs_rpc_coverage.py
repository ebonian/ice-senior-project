"""Why is the modelled LP fee a uniform +33% over the recorded fee?

A constant multiplicative error across 8 independent cycles is a scale factor,
not noise. Candidates, cheapest first:
  (a) duplicated swaps in the RPC pull
  (b) RPC vs B2 swap counts / volume disagree for the same hour
  (c) the liquidity-share denominator (does the pool's `liquidity` field already
      include our own position?)
  (d) in-range apportionment
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import harness as H, swaps as SW  # noqa: E402

G = Path(__file__).resolve().parents[1]
rpc = pd.read_parquet(G / "data/rpc/T5/swaps.parquet")
rpc["ts"] = pd.to_datetime(rpc["timestamp"], unit="s", utc=True)
rpc["hour"] = rpc["ts"].dt.floor("h")
rpc["vol"] = rpc["amount1"].astype("string").map(int).abs() / 1e6
rpc["poolL"] = rpc["liquidity"].astype("string").map(int).astype(float)

print(f"RPC rows: {len(rpc)}")
dups = rpc.duplicated(subset=["block_number", "log_index"]).sum()
print(f"(a) duplicate (block, log_index) pairs: {dups}")
dup_tx = rpc.duplicated(subset=["tx_hash", "log_index"]).sum()
print(f"    duplicate (tx_hash, log_index): {dup_tx}")

b2 = SW.load_swaps(
    pd.Timestamp("2026-05-14 00:00", tz="UTC"),
    pd.Timestamp("2026-05-16 00:00", tz="UTC"),
    swap_dir=G / "data/b2/swaps",
)
b2["hour"] = b2["ts"].dt.floor("h")
print(f"\nB2 rows in 05-14..05-15: {len(b2)}")

print("\n(b) per-hour comparison, hours present in BOTH sources")
print(f"{'hour':>16s} {'B2 n':>7s} {'RPC n':>7s} {'ratio':>6s} "
      f"{'B2 vol$':>12s} {'RPC vol$':>12s} {'ratio':>6s}")
b2h = b2.groupby("hour").agg(n=("price", "size"), vol=("volume_usd", "sum"))
rph = rpc.groupby("hour").agg(n=("vol", "size"), vol=("vol", "sum"))
common = sorted(set(b2h.index) & set(rph.index))
for h in common:
    a, b = b2h.loc[h], rph.loc[h]
    print(f"{str(h)[:16]:>16s} {int(a.n):>7d} {int(b.n):>7d} {b.n/a.n:>6.3f} "
          f"{a.vol:>12,.0f} {b.vol:>12,.0f} {b.vol/a.vol:>6.3f}")

# Block-level check on one hour: are the RPC extras real swaps B2 dropped?
if common:
    h = common[len(common) // 2]
    ab = set(zip(b2[b2["hour"] == h].get("block_number", pd.Series(dtype=int)),
                 [0] * len(b2[b2["hour"] == h])))
    print(f"\n  spot-check hour {h}: B2 has no log_index column? "
          f"{'block_number' in b2.columns}")

print("\n(c) liquidity-share denominator")
med_pool = float(np.median(rpc["poolL"]))
print(f"    median pool liquidity (raw): {med_pool:.4e}")
# Our own L, cycle 6 (a fully in-range cycle).
L_raw = 4142918273791842.0  # T5 cycle 2 mint, from the receipt
print(f"    our L_raw (T5 c2 mint):      {L_raw:.4e}")
print(f"    L/(pool+L) = {L_raw/(med_pool+L_raw):.6e}")
print(f"    L/pool     = {L_raw/med_pool:.6e}")
print(f"    ratio      = {(L_raw/med_pool)/(L_raw/(med_pool+L_raw)):.6f}  "
      "(so this cannot explain +33%)")

print("\n(d) does the recorded fee imply a different effective share?")
# cycle 6: 20:02->22:02, recorded 0.9147, ticks -198970..-198870
lo, hi = -198970, -198870
sl = rpc[(rpc["block_number"] > 462848362) & (rpc["block_number"] <= 462877155)]
inr = sl[(sl["tick"] >= lo) & (sl["tick"] <= hi)]
print(f"    cycle 6 swaps {len(sl)}, in-range-tick swaps {len(inr)}, "
      f"in-range volume ${inr['vol'].sum():,.0f}")
Lc6 = 3.9e15  # approx
print(f"    implied share from recorded fee: "
      f"{0.9147 / (inr['vol'].sum() * 0.0005):.6e}")
print(f"    modelled mean share was 6.478e-4")
