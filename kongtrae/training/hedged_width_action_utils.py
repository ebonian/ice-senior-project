from __future__ import annotations

from typing import Sequence

import numpy as np

from kongtrae.training.uniswap_v3_hedged_fee_env import ENTRY_WIDTHS, optimal_width_for_vol


WIDTH_ACTION_MODE_ABSOLUTE = "absolute"
WIDTH_ACTION_MODE_HEURISTIC_DELTA = "heuristic_delta"
WIDTH_ACTION_MODES = (
    WIDTH_ACTION_MODE_ABSOLUTE,
    WIDTH_ACTION_MODE_HEURISTIC_DELTA,
)

HEURISTIC_WIDTH_OFFSETS = (-2, -1, 0, 1, 2)
OBS_NATR_14_INDEX = 1


def width_action_values(action_mode: str) -> list[int]:
    if action_mode == WIDTH_ACTION_MODE_ABSOLUTE:
        return list(ENTRY_WIDTHS)
    if action_mode == WIDTH_ACTION_MODE_HEURISTIC_DELTA:
        return list(HEURISTIC_WIDTH_OFFSETS)
    raise ValueError(f"Unsupported width action mode: {action_mode}")


def width_action_labels(action_mode: str) -> list[str]:
    if action_mode == WIDTH_ACTION_MODE_ABSOLUTE:
        return [f"width_{width}" for width in ENTRY_WIDTHS]
    if action_mode == WIDTH_ACTION_MODE_HEURISTIC_DELTA:
        labels = []
        for offset in HEURISTIC_WIDTH_OFFSETS:
            sign = "p" if offset > 0 else "m" if offset < 0 else ""
            suffix = str(abs(offset)) if offset != 0 else "0"
            labels.append(f"heuristic_{sign}{suffix}")
        return labels
    raise ValueError(f"Unsupported width action mode: {action_mode}")


def width_action_index_to_value(action_idx: int, action_mode: str) -> int:
    values = width_action_values(action_mode)
    action_idx_int = int(action_idx)
    if action_idx_int < 0 or action_idx_int >= len(values):
        raise ValueError(f"Width action index out of range: {action_idx_int}")
    return int(values[action_idx_int])


def heuristic_width_from_obs(obs: Sequence[float] | np.ndarray) -> int:
    return int(optimal_width_for_vol(float(obs[OBS_NATR_14_INDEX])))


def _shift_width(base_width: int, offset: int) -> int:
    if base_width not in ENTRY_WIDTHS:
        raise ValueError(f"Unsupported base width: {base_width}")
    base_idx = ENTRY_WIDTHS.index(int(base_width))
    target_idx = max(0, min(len(ENTRY_WIDTHS) - 1, base_idx + int(offset)))
    return int(ENTRY_WIDTHS[target_idx])


def width_decision_to_width(
    decision_value: int,
    obs: Sequence[float] | np.ndarray,
    action_mode: str,
) -> int:
    if action_mode == WIDTH_ACTION_MODE_ABSOLUTE:
        width = int(decision_value)
        if width not in ENTRY_WIDTHS:
            raise ValueError(f"Unsupported absolute width decision: {width}")
        return width
    if action_mode == WIDTH_ACTION_MODE_HEURISTIC_DELTA:
        return _shift_width(heuristic_width_from_obs(obs), int(decision_value))
    raise ValueError(f"Unsupported width action mode: {action_mode}")
