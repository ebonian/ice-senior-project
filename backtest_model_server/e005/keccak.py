"""Pure-python keccak256 — the gate1 shell has no keccak library, and E005
needs function selectors and event topics that must be derived, not guessed
(a wrong SetFeeProtocol topic would silently report "no fee change").

Trustworthiness is established by `self_test()`, which requires this
implementation to reproduce (a) the canonical empty-input digest and (b) the
Swap event topic frozen in `gate1/engine/rpc.py`. Every selector used by E005
comes through here after that test has passed.
"""

from __future__ import annotations

_RC = [
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A,
    0x8000000080008000, 0x000000000000808B, 0x0000000080000001,
    0x8000000080008081, 0x8000000000008009, 0x000000000000008A,
    0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089,
    0x8000000000008003, 0x8000000000008002, 0x8000000000000080,
    0x000000000000800A, 0x800000008000000A, 0x8000000080008081,
    0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
]
# rotation offsets, indexed [x + 5y]
_R = [0, 1, 62, 28, 27,
      36, 44, 6, 55, 20,
      3, 10, 43, 25, 39,
      41, 45, 15, 21, 8,
      18, 2, 61, 56, 14]
_MASK = (1 << 64) - 1


def _rol(v: int, n: int) -> int:
    n %= 64
    return ((v << n) | (v >> (64 - n))) & _MASK if n else v


def _f(a: list[int]) -> list[int]:
    for rc in _RC:
        c = [a[x] ^ a[x + 5] ^ a[x + 10] ^ a[x + 15] ^ a[x + 20] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rol(c[(x + 1) % 5], 1) for x in range(5)]
        a = [a[i] ^ d[i % 5] for i in range(25)]
        b = [0] * 25
        for x in range(5):
            for y in range(5):
                b[y + 5 * ((2 * x + 3 * y) % 5)] = _rol(a[x + 5 * y], _R[x + 5 * y])
        a = [b[i] ^ ((~b[(i % 5 + 1) % 5 + 5 * (i // 5)]) & b[(i % 5 + 2) % 5 + 5 * (i // 5)])
             for i in range(25)]
        a[0] ^= rc
    return a


def keccak256(data: bytes) -> bytes:
    rate = 136
    p = bytearray(data)
    p.append(0x01)
    while len(p) % rate:
        p.append(0x00)
    p[-1] |= 0x80
    s = [0] * 25
    for off in range(0, len(p), rate):
        for i in range(rate // 8):
            s[i] ^= int.from_bytes(p[off + 8 * i: off + 8 * i + 8], "little")
        s = _f(s)
    return b"".join(s[i].to_bytes(8, "little") for i in range(4))


def selector(signature: str) -> str:
    """0x-prefixed 4-byte function selector."""
    return "0x" + keccak256(signature.encode()).hex()[:8]


def event_topic(signature: str) -> str:
    """0x-prefixed 32-byte event topic0."""
    return "0x" + keccak256(signature.encode()).hex()


def self_test() -> None:
    empty = keccak256(b"").hex()
    want_empty = "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    if empty != want_empty:
        raise AssertionError(f"keccak256(b'') = {empty}, want {want_empty}")
    swap = event_topic("Swap(address,address,int256,int256,uint160,uint128,int24)")
    want_swap = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
    if swap != want_swap:
        raise AssertionError(f"Swap topic {swap} != gate1 TOPIC_SWAP {want_swap}")


self_test()
