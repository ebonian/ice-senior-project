"""E010 registry: chains, candidates, and the capital parameterization.

E010's one variable vs E005 is the CAPITAL PARAMETERIZATION AND THE VENUE
MENU IT REOPENS (loop/experiments/E010-capital-rescreen.md). Everything
venue-independent stays frozen and is imported from e005/e003/gate1 — this
module adds only what varies: the chain registry (mainnet + Base), the
pre-named candidate set from memo M004 §3, and the $10k reference capital
mapped through E003's C2 split.

Like e005/pools.py, pool ADDRESSES are never written here: `discover10.py`
resolves each candidate via its chain's factory and writes
`out/candidates.json`; downstream stages read that file.

Module naming: e010 module names are unique (registry, fetch10, ...) so that
inserting E005/GATE1/E003 on sys.path FIRST lets `import pools` / `import
race` / `import coverage` always resolve to e005's modules with no shadowing.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

E010 = Path(__file__).resolve().parent
BMS = E010.parent
GATE1 = BMS / "gate1"
E003 = BMS / "e003"
E005 = BMS / "e005"
for p in (str(GATE1), str(E003), str(E005)):
    if p not in sys.path:
        sys.path.insert(0, p)
if str(E010) not in sys.path:
    sys.path.append(str(E010))          # append, never insert-0: e005 wins ties

import pools as P5  # noqa: E402  (e005 registry — frozen constants inherited)
from engine import cost_model as CM  # noqa: E402

# --- frozen, inherited ------------------------------------------------------
ENVELOPE = P5.ENVELOPE
ENVELOPE_BY_NAME = P5.ENVELOPE_BY_NAME
COST_MODEL_VERSION = P5.COST_MODEL_VERSION      # gate1-2026-08-29
ENVELOPE_VERSION = P5.ENVELOPE_VERSION          # e003-2026-08-29
TX_PER_RECENTER = P5.TX_PER_RECENTER            # 4
WINDOW_START = P5.WINDOW_START                  # 2026-05-01
WINDOW_END = P5.WINDOW_END                      # 2026-08-28 (exclusive)
MIN_MEDIAN_SWAPS_PER_DAY = P5.MIN_MEDIAN_SWAPS_PER_DAY  # 48
ARB_GAS_USD_PER_TX = CM.GAS_USD_PER_TX          # 0.0101, frozen for Arbitrum

# --- capital parameterization (the amendment, K1) ---------------------------
# E003's C2 split is preserved: LP notional / hedge equity = 1015 / 405 of
# 1420. The reference moves to $10k; the scaling law is reported at all three.
TOTAL_CAPITAL_E003 = P5.TOTAL_CAPITAL_USD       # 1420.0
LP_FRACTION = P5.LP_CAPITAL_USD / P5.TOTAL_CAPITAL_USD          # 0.714789...
REFERENCE_CAPITAL_USD = 10_000.0
SCALING_CAPITALS = (1_420.0, 10_000.0, 50_000.0)


def lp_notional(capital_usd: float) -> float:
    return capital_usd * LP_FRACTION


def hedge_equity(capital_usd: float) -> float:
    return capital_usd * (1.0 - LP_FRACTION)


LP_NOTIONAL_10K = lp_notional(REFERENCE_CAPITAL_USD)     # 7147.887...
# 10% APR on the reference capital, the rate-form target (pre-registered):
TARGET_USD_PER_DAY_10K = 0.10 * REFERENCE_CAPITAL_USD / 365.0   # 2.7397


def target_usd_per_day(capital_usd: float) -> float:
    return 0.10 * capital_usd / 365.0

# --- chain registry ---------------------------------------------------------
# logs_rpc serves eth_getLogs for the 2026-05..08 range (probed 2026-09-03:
# publicnode gates historical logs behind a token; Tenderly's public gateway
# serves them). state_rpc serves headers / eth_call / latest state and is the
# INDEPENDENT provider for the feeProtocol cross-check (validity gate ii).
CHAINS = {
    "arbitrum": {
        "factory": "0x1F98431c8aD98523631AE4a59f267346ea31F984".lower(),
        "logs_rpc": [P5.RPC_URL],
        "state_rpc": [P5.RPC_URL],
        "anchor_stride": 2000,          # e003's own stride
    },
    "mainnet": {
        "factory": "0x1F98431c8aD98523631AE4a59f267346ea31F984".lower(),
        "logs_rpc": ["https://mainnet.gateway.tenderly.co",
                     "https://eth.llamarpc.com"],
        "state_rpc": ["https://ethereum-rpc.publicnode.com",
                      "https://mainnet.gateway.tenderly.co"],
        "anchor_stride": 1000,          # ~12s blocks -> anchors every ~3.3h
    },
    "base": {
        "factory": "0x33128a8fC17869897dcE68Ed026d694621f6FDfD".lower(),
        "logs_rpc": ["https://base.gateway.tenderly.co",
                     "https://mainnet.base.org"],
        "state_rpc": ["https://base-rpc.publicnode.com",
                      "https://base.gateway.tenderly.co"],
        "anchor_stride": 5000,          # ~2s blocks -> anchors every ~2.8h
    },
}

# Token addresses per chain. discover10.py verifies symbol()/decimals()
# on-chain before anything downstream uses them (a wrong address fails loudly).
TOKENS = {
    "mainnet": {
        "WETH":   ("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", 18),
        "USDC":   ("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", 6),
        "USDT":   ("0xdAC17F958D2ee523a2206206994597C13D831ec7", 6),
        "WBTC":   ("0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599", 8),
        "wstETH": ("0x7f39C581F595B53c5cb19bD0b3f8dA6c935E2Ca0", 18),
        "LINK":   ("0x514910771AF9Ca656af840dff83E8264EcF986CA", 18),
        "UNI":    ("0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984", 18),
    },
    "base": {
        "WETH":   ("0x4200000000000000000000000000000000000006", 18),
        "USDC":   ("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", 6),
    },
}

STABLES = {"USDC", "USDT"}              # unhedged, USD par, mark = 1.0
ETH_BETA_TOKENS = {"wstETH"}            # E005's pre-registered exception
HL_COIN = {"WETH": "ETH", "WBTC": "BTC", "LINK": "LINK", "UNI": "UNI",
           "wstETH": "ETH"}


@dataclass(frozen=True)
class Candidate:
    slug: str
    chain: str
    family: str        # M004 §3 rank / family analogue
    tokenA: str
    tokenB: str
    fee: int
    role: str          # "screen" | "probe"


# M004 §3's pre-named set, in rank order; probes last. Slug prefix m_/b_
# encodes the chain so artifact paths cannot collide with e005's.
CANDIDATES = [
    Candidate("m_wsteth_weth_0p01", "mainnet", "F3-twin",   "wstETH", "WETH", 100,  "screen"),
    Candidate("m_weth_usdc_0p05",   "mainnet", "control-twin", "WETH", "USDC", 500,  "screen"),
    Candidate("m_weth_usdc_0p30",   "mainnet", "F1",        "WETH",  "USDC", 3000, "screen"),
    Candidate("m_weth_usdt_0p05",   "mainnet", "F4-flow",   "WETH",  "USDT", 500,  "screen"),
    Candidate("m_wbtc_weth_0p05",   "mainnet", "F2",        "WBTC",  "WETH", 500,  "screen"),
    Candidate("m_link_weth_0p30",   "mainnet", "F4-signal", "LINK",  "WETH", 3000, "screen"),
    Candidate("m_wbtc_weth_0p30",   "mainnet", "F2b",       "WBTC",  "WETH", 3000, "screen"),
    Candidate("m_uni_weth_0p30",    "mainnet", "F4",        "UNI",   "WETH", 3000, "screen"),
    Candidate("b_weth_usdc_0p05",   "base",    "B3",        "WETH",  "USDC", 500,  "screen"),
    Candidate("m_link_weth_0p05",   "mainnet", "probe",     "LINK",  "WETH", 500,  "probe"),
    Candidate("m_wsteth_weth_0p05", "mainnet", "probe",     "wstETH", "WETH", 500, "probe"),
]

# --- committed chain data (derived by derive_blocks.py) ---------------------
BLOCKS_DIR = E010 / "data" / "blocks"


def month_blocks(chain: str) -> dict[str, tuple[int, int]]:
    if chain == "arbitrum":
        return dict(P5.MONTH_BLOCKS)
    f = BLOCKS_DIR / f"{chain}.month_blocks.json"
    d = json.loads(f.read_text())["month_blocks"]
    return {k: (int(v[0]), int(v[1])) for k, v in d.items()}


def anchors_path(chain: str, label: str) -> Path:
    return BLOCKS_DIR / chain / f"{label}.anchors.json"


def load_anchors(chain: str, label: str) -> dict[int, int]:
    f = anchors_path(chain, label)
    return {int(k): int(v) for k, v in json.loads(f.read_text()).items()}


GAS_ENVELOPE_FILE = E010 / "out" / "gas_envelope.json"


def gas_usd_per_tx(chain: str, point: str) -> float:
    """The chain's $/tx for one coupled envelope point. Arbitrum is frozen at
    the gate1 constant for every point (measured, not enveloped)."""
    if chain == "arbitrum":
        return ARB_GAS_USD_PER_TX
    g = json.loads(GAS_ENVELOPE_FILE.read_text())
    return float(g[chain]["usd_per_tx"][point])


# width arms: e005's mapping, reused verbatim
arms_for_spacing = P5.arms_for_spacing
arm_half_ticks = P5.arm_half_ticks
ARM_PCTS = P5.ARM_PCTS
