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
    REPRODUCTION_TOLERANCE,
    SUBSTANTIAL_THRESHOLD,
    Impact,
    Reproduction,
    Severity,
    analyse,
    check_reproduction,
    fragility,
    leave_one_out,
    reproduces_reported,
)
from .model import (
    DIFFERENCE_MEASURES,
    MEASURES,
    RATIO_MEASURES,
    TABLE_MEASURES,
    DataError,
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
    "check_reproduction",
    "fragility",
    "leave_one_out",
    "reproduces_reported",
    "Impact",
    "Reproduction",
    "Severity",
    "SUBSTANTIAL_THRESHOLD",
    "REPRODUCTION_TOLERANCE",
    # data model
    "DataError",
    "MetaAnalysis",
    "Study",
    "from_dict",
    "load",
    "MEASURES",
    "RATIO_MEASURES",
    "DIFFERENCE_MEASURES",
    "TABLE_MEASURES",
    # statistics
    "PooledResult",
    "effect_size",
    "pool",
    "pool_meta",
]
