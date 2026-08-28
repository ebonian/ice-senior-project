"""
Import shim so this analysis runs against simulation_14's OWN training code.

Every module under `research/simulation_14/training/` imports its siblings as
`kongtrae.training.*`, but `research/simulation_14/` is not named `kongtrae` and
its parent is not on the path as one. Running those scripts from the repo root
therefore silently resolves `kongtrae.training.*` to the top-level `kongtrae/`
package -- which is the *pre-mask-fix* copy. The two differ:

    kongtrae/training/hedged_hierarchical_policy.py    (older)
    research/simulation_14/training/hedged_hierarchical_policy.py (mask-fixed)

Concretely the snapshot adds `masked_invalid_action` to the trace, counts
`recenter_same_width` in `trace_metrics`, and threads `fee_haircut` /
`active_liquidity_multiplier` into the paper baseline. The shipped 1h checkpoint
comes from run `walk_forward_three_head_v2_1h_maskfix_100k`
(`models/three_head_v3_1h/manifest.json`), i.e. the mask-fixed code -- so the
snapshot, not the top-level package, is the environment it was trained in.

`bind()` registers `research/simulation_14` under the name `kongtrae` before any
of its modules load, so the existing `from kongtrae.training.X import Y` lines
resolve to the snapshot. Import everything through the `kongtrae.` namespace
afterwards; importing the same file under both names would create two distinct
module objects and break identity checks.
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))  # .../simulation_14/analysis/baseline_race
SIM14_DIR = os.path.dirname(os.path.dirname(_HERE))  # .../simulation_14
SIM_PARENT = os.path.dirname(SIM14_DIR)  # .../research
RESEARCH_ROOT = os.path.dirname(SIM_PARENT)

MODELS_DIR = os.path.join(SIM14_DIR, "models")
SHIPPED_1H_MODEL = os.path.join(MODELS_DIR, "dqn_three_head_v3_1h.zip")
SHIPPED_1H_VECNORM = os.path.join(MODELS_DIR, "dqn_three_head_v3_1h_vecnormalize.pkl")


def bind() -> None:
    """Alias `kongtrae` -> `research/simulation_14` in sys.modules."""
    if "kongtrae" in sys.modules:
        return
    if SIM_PARENT not in sys.path:
        sys.path.insert(0, SIM_PARENT)

    import simulation_14
    import simulation_14.training

    expected = os.path.join(SIM14_DIR, "__init__.py")
    actual = getattr(simulation_14, "__file__", None)
    if actual is None or os.path.abspath(actual) != expected:
        raise RuntimeError(
            f"simulation_14 resolved to {actual}, expected {expected}; "
            "refusing to run against the wrong training package"
        )

    sys.modules["kongtrae"] = simulation_14
    sys.modules["kongtrae.training"] = simulation_14.training
