from __future__ import annotations

import math
from .contracts import FundamentalAnchor, ModelForecast


def anchor_ratio_guard(f: ModelForecast, anchor: FundamentalAnchor | None, max_log_deviation: float = math.log(3.0)) -> tuple[bool, str | None]:
    """Reject grossly implausible model outputs before blending.

    This is not a valuation cap. It is a bootstrap safety rule until walk-forward evidence
    supports widening the accepted region.
    """
    if f.point is None or f.point <= 0:
        return False, "missing/non-positive point forecast"
    if anchor is None or anchor.base is None or anchor.base <= 0:
        return True, None
    dev = abs(math.log(float(f.point) / float(anchor.base)))
    if dev > max_log_deviation:
        return False, "model point is >3x away from fundamental anchor in price ratio"
    return True, None
