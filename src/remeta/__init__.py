"""ReMeta — reassess meta-analysis results after study retractions.

ReMeta reproduces a published pooled estimate from study-level data, removes
the studies marked as retracted, recalculates, and reports whether the
review's conclusion actually changed. Every number is a deterministic
recalculation, not a judgement about the papers.

Typical use::

    from remeta import analyse, load

    for ma in load("review.json"):
        impact = analyse(ma)
        print(ma.id, impact.severity.value, impact.summary())
"""

from .impact import (
    GATE_ABSOLUTE_COMBINED,
    GATE_ABSOLUTE_PER_VALUE,
    GATE_RULES,
    SUBSTANTIAL_THRESHOLD,
    Gate,
    GateComparison,
    GateState,
    Impact,
    Severity,
    analyse,
    check_gate,
    fragility,
    leave_one_out,
    precision_tolerance,
)
from .model import (
    COUNT_MEASURES,
    DIFFERENCE_MEASURES,
    MEASURES,
    RATE_MEASURES,
    RATIO_MEASURES,
    TABLE_MEASURES,
    DataError,
    DoubleZeroError,
    MetaAnalysis,
    Study,
    from_dict,
    load,
)
from .stats import PooledResult, effect_size, pool, pool_meta

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # analysis
    "analyse",
    "check_gate",
    "fragility",
    "leave_one_out",
    "precision_tolerance",
    "Impact",
    "Gate",
    "GateComparison",
    "GateState",
    "Severity",
    "SUBSTANTIAL_THRESHOLD",
    "GATE_ABSOLUTE_PER_VALUE",
    "GATE_ABSOLUTE_COMBINED",
    "GATE_RULES",
    # data model
    "DataError",
    "DoubleZeroError",
    "MetaAnalysis",
    "Study",
    "from_dict",
    "load",
    "MEASURES",
    "RATIO_MEASURES",
    "DIFFERENCE_MEASURES",
    "TABLE_MEASURES",
    "RATE_MEASURES",
    "COUNT_MEASURES",
    # statistics
    "PooledResult",
    "effect_size",
    "pool",
    "pool_meta",
]
