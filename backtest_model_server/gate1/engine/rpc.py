"""Arbitrum RPC client: Swap/Mint/Burn/Collect logs and tx receipts.

Exists because the B2 daily archive is not complete over the trial windows —
only 11 of 24 hours are present in each (see gate1/REPORT.md, finding D1).
Replaying fees against B2 alone would silently undercount by roughly half,
which is exactly the failure mode 04-backtest-design.md §9 warns about
("refuse to replay a window with gaps rather than silently under-counting").

Everything here is read-only JSON-RPC against the URL in model/.env.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

import requests

POOL = "0xC6962004f452bE9203591991D15f6b388e09E8D0".lower()

# keccak256 of the event signatures, as emitted by UniswapV3Pool.
TOPIC_SWAP = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
TOPIC_MINT = "0x7a53080ba414158be7ec69b987b5fb7d07dee101fe85488f0853ae16239d0bde"
TOPIC_BURN = "0x0c396cd989a39f4459b5fa1aed6a9a8dcdbc45908acfd67e028cd568da98982c"
TOPIC_COLLECT = "0x70935338e69775456a85ddef226c395fb668b63fa0115f5f20610b388e6ca9c0"

MAX_BLOCK_SPAN = 50_000


def _u256(word: str) -> int:
    return int(word, 16)


def _i256(word: str) -> int:
    v = int(word, 16)
    return v - (1 << 256) if v >= (1 << 255) else v


def _i24(word: str) -> int:
    v = int(word, 16) & ((1 << 24) - 1)
    return v - (1 << 24) if v >= (1 << 23) else v


def _words(data: str) -> list[str]:
    d = data[2:] if data.startswith("0x") else data
    return [d[i : i + 64] for i in range(0, len(d), 64)]


@dataclass
class Swap:
    block_number: int
    log_index: int
    tx_hash: str
    amount0: int
    amount1: int
    sqrt_price_x96: int
    liquidity: int
    tick: int
    # Indexed topics. `recipient` is who received the output, which is how our
    # own swap legs are identified for the on-chain cost line.
    sender: str = ""
    recipient: str = ""


class ArbRPC:
    def __init__(self, url: str, pool: str = POOL):
        self.url = url
        self.pool = pool.lower()
        self._id = 0
        self.session = requests.Session()
        self.calls = 0

    def call(self, method: str, params: list, tries: int = 5):
        self._id += 1
        payload = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
        last = None
        for attempt in range(tries):
            try:
                r = self.session.post(self.url, json=payload, timeout=120)
                r.raise_for_status()
                j = r.json()
                if "error" in j:
                    raise RuntimeError(f"{method}: {j['error']}")
                self.calls += 1
                return j["result"]
            except Exception as e:  # transient RPC failures are routine
                last = e
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"{method} failed after {tries} tries: {last}")

    def batch(self, requests_: list[tuple[str, list]], tries: int = 5) -> list:
        """One HTTP round trip for many calls. Order is preserved."""
        payload = []
        for method, params in requests_:
            self._id += 1
            payload.append(
                {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
            )
        last = None
        for attempt in range(tries):
            try:
                r = self.session.post(self.url, json=payload, timeout=180)
                r.raise_for_status()
                out = r.json()
                by_id = {o["id"]: o for o in out}
                res = []
                for p in payload:
                    o = by_id[p["id"]]
                    if "error" in o:
                        raise RuntimeError(f"{p['method']}: {o['error']}")
                    res.append(o["result"])
                self.calls += len(payload)
                return res
            except Exception as e:
                last = e
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"batch failed after {tries} tries: {last}")

    # --- blocks ------------------------------------------------------------
    def block_number(self) -> int:
        return int(self.call("eth_blockNumber", []), 16)

    def block_timestamp(self, block: int) -> int:
        b = self.call("eth_getBlockByNumber", [hex(block), False])
        return int(b["timestamp"], 16)

    def block_timestamps(self, blocks: list[int]) -> dict[int, int]:
        """Batched timestamps for many blocks."""
        out: dict[int, int] = {}
        uniq = sorted(set(blocks))
        CHUNK = 200
        for i in range(0, len(uniq), CHUNK):
            part = uniq[i : i + CHUNK]
            res = self.batch([("eth_getBlockByNumber", [hex(b), False]) for b in part])
            for b, r in zip(part, res):
                out[b] = int(r["timestamp"], 16)
        return out

    def block_at_time(self, target_ts: int, lo: int, hi: int) -> int:
        """First block with timestamp >= target_ts, by binary search."""
        while lo < hi:
            mid = (lo + hi) // 2
            if self.block_timestamp(mid) < target_ts:
                lo = mid + 1
            else:
                hi = mid
        return lo

    # --- logs --------------------------------------------------------------
    def get_logs(self, from_block: int, to_block: int, topic0: str) -> list[dict]:
        out: list[dict] = []
        b = from_block
        while b <= to_block:
            end = min(b + MAX_BLOCK_SPAN - 1, to_block)
            res = self.call(
                "eth_getLogs",
                [
                    {
                        "address": self.pool,
                        "fromBlock": hex(b),
                        "toBlock": hex(end),
                        "topics": [topic0],
                    }
                ],
            )
            out.extend(res)
            b = end + 1
        return out

    def get_swaps(self, from_block: int, to_block: int) -> list[Swap]:
        logs = self.get_logs(from_block, to_block, TOPIC_SWAP)
        swaps = []
        for lg in logs:
            w = _words(lg["data"])
            swaps.append(
                Swap(
                    block_number=int(lg["blockNumber"], 16),
                    log_index=int(lg["logIndex"], 16),
                    tx_hash=lg["transactionHash"],
                    amount0=_i256(w[0]),
                    amount1=_i256(w[1]),
                    sqrt_price_x96=_u256(w[2]),
                    liquidity=_u256(w[3]),
                    tick=_i24(w[4]),
                    sender="0x" + lg["topics"][1][-40:],
                    recipient="0x" + lg["topics"][2][-40:],
                )
            )
        swaps.sort(key=lambda s: (s.block_number, s.log_index))
        return swaps

    # --- receipts ----------------------------------------------------------
    def receipt(self, tx_hash: str) -> dict:
        return self.call("eth_getTransactionReceipt", [tx_hash])

    def receipts(self, tx_hashes: list[str]) -> dict[str, dict]:
        res = self.batch([("eth_getTransactionReceipt", [h]) for h in tx_hashes])
        return {h.lower(): r for h, r in zip(tx_hashes, res)}

    def pool_events_in_receipt(self, rcpt: dict) -> dict:
        """Decode this pool's Mint / Burn / Collect logs out of a tx receipt."""
        out = {"mint": [], "burn": [], "collect": []}
        if not rcpt:
            return out
        for lg in rcpt.get("logs", []):
            if lg["address"].lower() != self.pool:
                continue
            t0 = lg["topics"][0].lower()
            tick_lower = _i24(lg["topics"][2][-6:]) if len(lg["topics"]) > 2 else None
            tick_upper = _i24(lg["topics"][3][-6:]) if len(lg["topics"]) > 3 else None
            w = _words(lg["data"])
            if t0 == TOPIC_MINT:
                # Mint(sender, owner, tickLower, tickUpper, amount, amount0, amount1)
                out["mint"].append(
                    {
                        "tick_lower": tick_lower,
                        "tick_upper": tick_upper,
                        "liquidity": _u256(w[1]),
                        "amount0": _u256(w[2]),
                        "amount1": _u256(w[3]),
                        "block": int(lg["blockNumber"], 16),
                    }
                )
            elif t0 == TOPIC_BURN:
                # Burn(owner, tickLower, tickUpper, amount, amount0, amount1)
                out["burn"].append(
                    {
                        "tick_lower": tick_lower,
                        "tick_upper": tick_upper,
                        "liquidity": _u256(w[0]),
                        "amount0": _u256(w[1]),
                        "amount1": _u256(w[2]),
                        "block": int(lg["blockNumber"], 16),
                    }
                )
            elif t0 == TOPIC_COLLECT:
                # Collect(owner, recipient, tickLower, tickUpper, amount0, amount1)
                out["collect"].append(
                    {
                        "tick_lower": tick_lower,
                        "tick_upper": tick_upper,
                        "amount0": _u256(w[1]),
                        "amount1": _u256(w[2]),
                        "block": int(lg["blockNumber"], 16),
                    }
                )
        return out
