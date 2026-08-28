"""
The trivial baseline the walk-forward gate never ran: always be in the pool at one
fixed width, and recenter when price leaves the range.

simulation_14's gate scored the DQN against two references -- always-cash and the
paper's bb-gated W4 threshold rule (`walk_forward_three_head_v2_dqn.py:243-262`).
Both of those spend time in cash, so neither answers "does the learned policy beat
just staying in the pool?". This policy answers exactly that, and nothing else.

It is a drop-in for the `three_head_policy` argument of
`run_three_head_policy_episode`: same `.predict(obs, return_q=...) ->
PolicyPrediction` contract as `NormalizedDQNPolicy`, so it runs inside
`UniswapV3HedgedThreeHeadEnv` with the DQN's action semantics, accounting, and
env kwargs unchanged.

Action contract under `_v2_env_kwargs` (`train_hedged_three_head_v2_dqn.py`),
with `action_widths = (4, 6, 10, 20)`:

    state         0            1          2                       3..
    cash          stay_cash    enter_w4   enter_w6                enter_w10, enter_w20
    lp_in_range   hold         go_cash    (masked)
    lp_oor        hold_oor     go_cash    recenter_same_width     (masked)

so the rule is: cash -> `1 + widths.index(width)`, in-range -> 0 (hold),
out-of-range -> 2 (recenter at the same width). Action 1 is never emitted from an
LP state, which is what "never EXIT to cash" means here.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

from kongtrae.training.hedged_hierarchical_policy import (
    PolicyPrediction,
    _three_head_state_from_obs,
)
from kongtrae.training.uniswap_v3_hedged_hierarchical_env import (
    THREE_HEAD_CASH,
    THREE_HEAD_GO_CASH,
    THREE_HEAD_HOLD,
    THREE_HEAD_IN_RANGE,
    THREE_HEAD_OOR,
)

OOR_RECENTER_SAME_ACTION = 2


class AlwaysInFixedWidthPolicy:
    """Hold a position at `width` forever; recenter on exit; never go to cash."""

    def __init__(self, width: int, action_widths: Sequence[int]):
        widths = tuple(int(w) for w in action_widths)
        if int(width) not in widths:
            raise ValueError(
                f"width {width} is not in the model's action catalog {widths}"
            )
        self.width = int(width)
        self.action_widths = widths
        self.enter_action = 1 + widths.index(self.width)

    @property
    def name(self) -> str:
        return f"always_in_w{self.width}"

    def predict(self, obs: np.ndarray, return_q: bool = False) -> PolicyPrediction:
        state = _three_head_state_from_obs(obs)
        if state == THREE_HEAD_CASH:
            action = self.enter_action
        elif state == THREE_HEAD_IN_RANGE:
            action = THREE_HEAD_HOLD
        elif state == THREE_HEAD_OOR:
            action = OOR_RECENTER_SAME_ACTION
        else:
            raise ValueError(f"Unsupported three-head state: {state}")
        return PolicyPrediction(value=int(action), q_values=None, raw_value=int(action))


class AlwaysInHoldOnlyPolicy(AlwaysInFixedWidthPolicy):
    """Same, but sit out-of-range instead of recentering.

    Separates the two things the W-rule does -- being in the pool at all, and
    paying to recenter -- so a win can be attributed to one of them.
    """

    @property
    def name(self) -> str:
        return f"always_in_w{self.width}_no_recenter"

    def predict(self, obs: np.ndarray, return_q: bool = False) -> PolicyPrediction:
        state = _three_head_state_from_obs(obs)
        if state == THREE_HEAD_CASH:
            action = self.enter_action
        else:
            action = THREE_HEAD_HOLD  # 0 is `hold` in-range and `hold_oor` when out
        return PolicyPrediction(value=int(action), q_values=None, raw_value=int(action))


def build_rule_policies(action_widths: Sequence[int], widths: Sequence[int]):
    """Return `{name: policy}` for each requested fixed width, plus the W10 variant."""
    policies = {}
    for width in widths:
        policy = AlwaysInFixedWidthPolicy(width, action_widths)
        policies[policy.name] = policy
    if 10 in tuple(int(w) for w in widths):
        variant = AlwaysInHoldOnlyPolicy(10, action_widths)
        policies[variant.name] = variant
    return policies


__all__ = [
    "AlwaysInFixedWidthPolicy",
    "AlwaysInHoldOnlyPolicy",
    "build_rule_policies",
    "THREE_HEAD_GO_CASH",
]
