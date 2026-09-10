"""Meta-analysis statistics.

Implements the standard Cochrane/RevMan estimators:

  - effect sizes from 2x2 tables (log RR, log OR, RD)
  - inverse-variance fixed-effect pooling
  - DerSimonian-Laird random-effects pooling
  - Cochran's Q, I-squared, tau-squared

These are deliberately the *conventional* estimators rather than better modern
ones (REML, Hartung-Knapp). ReMeta's question is "what would this published
review have concluded without the retracted study", so it must reproduce the
method the review actually used. Using a better estimator would change the
answer for reasons unrelated to the retraction, which is the one thing this
tool must never do.

References:
  DerSimonian R, Laird N. Meta-analysis in clinical trials. Control Clin
  Trials. 1986;7(3):177-188.
  Higgins JPT, Thompson SG. Quantifying heterogeneity in a meta-analysis.
  Stat Med. 2002;21(11):1539-1558.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .model import (
    COUNT_MEASURES,
    RATE_MEASURES,
    RATIO_MEASURES,
    TABLE_MEASURES,
    DataError,
    DoubleZeroError,
    MetaAnalysis,
    Study,
)

# Standard normal quantile for a 95% interval. RevMan uses the normal
# approximation for pooled estimates, so we do too.
Z_95 = 1.959963984540054


def _norm_sf(x: float) -> float:
    """Upper tail of the standard normal distribution."""
    return 0.5 * math.erfc(x / math.sqrt(2.0))


def z_quantile(confidence: float) -> float:
    """Two-sided critical value, via bisection on the error function."""
    if not 0 < confidence < 1:
        raise ValueError("confidence must be in (0, 1)")
    target = (1 + confidence) / 2
    low, high = 0.0, 40.0
    for _ in range(200):
        mid = (low + high) / 2
        if 1 - _norm_sf(mid) < target:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def effect_size(
    study: Study,
    measure: str,
    correction: float = 0.5,
    include_double_zero: bool = False,
) -> tuple[float, float]:
    """Return (yi, vi) for a study on the analysis scale.

    Ratio measures are returned in log space, which is where pooling happens.
    A continuity correction is applied only when a cell is zero, matching
    RevMan's default behaviour.

    A study with no events in either arm raises DoubleZeroError unless
    `include_double_zero` is set: it carries no information about the
    contrast, and correcting it would hand it a weight it has not earned.
    """
    if study.has_effect:
        assert study.yi is not None and study.vi is not None
        return study.yi, study.vi

    if measure not in COUNT_MEASURES:
        raise DataError(
            f"study {study.id!r}: {measure} cannot be derived from counts "
            f"(only {', '.join(sorted(COUNT_MEASURES))} can). Supply a "
            f"precomputed effect as 'yi' (on the log scale for ratio measures) "
            f"with its variance 'vi'."
        )

    if measure in RATE_MEASURES:
        return _rate_effect(study, measure, correction, include_double_zero)

    if not study.has_table:
        raise DataError(
            f"study {study.id!r}: {measure} needs a 2x2 table "
            f"(events and totals for both arms); none was supplied"
        )

    a = float(study.events_treat)  # type: ignore[arg-type]
    n1 = float(study.total_treat)  # type: ignore[arg-type]
    c = float(study.events_control)  # type: ignore[arg-type]
    n2 = float(study.total_control)  # type: ignore[arg-type]
    b = n1 - a
    d = n2 - c

    double_zero = a == 0 and c == 0

    if measure == "RD":
        if double_zero:
            # The point estimate is defined and equal to zero, but its
            # variance is exactly zero, so no inverse-variance weight exists.
            # There is nothing to include, which is why include_double_zero
            # does not rescue this case.
            raise DoubleZeroError(
                f"study {study.id!r}: no events in either arm, so its risk "
                f"difference has zero variance and cannot be given an "
                f"inverse-variance weight"
            )
        p1, p2 = a / n1, c / n2
        yi = p1 - p2
        vi = p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2
        if vi <= 0:
            raise DataError(
                f"study {study.id!r}: risk difference has zero variance because "
                f"both arms are all-events or no-events; it cannot be pooled"
            )
        return yi, vi

    if double_zero and not include_double_zero:
        raise DoubleZeroError(
            f"study {study.id!r}: no events in either arm, so it carries no "
            f"information about a {measure}"
        )

    if min(a, b, c, d) == 0:
        a, b, c, d = a + correction, b + correction, c + correction, d + correction
        n1, n2 = a + b, c + d

    if measure == "RR":
        if a <= 0 or c <= 0:
            raise DataError(f"study {study.id!r}: cannot compute a risk ratio from these counts")
        yi = math.log((a / n1) / (c / n2))
        vi = 1 / a - 1 / n1 + 1 / c - 1 / n2
    else:  # OR
        if min(a, b, c, d) <= 0:
            raise DataError(f"study {study.id!r}: cannot compute an odds ratio from these counts")
        yi = math.log((a * d) / (b * c))
        vi = 1 / a + 1 / b + 1 / c + 1 / d

    if vi <= 0:
        raise DataError(f"study {study.id!r}: non-positive variance ({vi})")
    return yi, vi


def _rate_effect(
    study: Study,
    measure: str,
    correction: float,
    include_double_zero: bool,
) -> tuple[float, float]:
    """Log incidence rate ratio from event counts and person-time at risk.

    log IRR = log((a / PT1) / (c / PT2)),  var = 1/a + 1/c

    The variance depends only on the event counts, which is why person-time
    appears in the estimate but not in its variance.
    """
    if not study.has_person_time:
        raise DataError(
            f"study {study.id!r}: an incidence rate ratio is a ratio of rates, "
            f"so it needs person-time at risk in each arm "
            f"('person_time_treat' and 'person_time_control'), not participant "
            f"totals. Supply person-time, or give the published log rate ratio "
            f"as 'yi' with its variance 'vi'."
        )

    a = float(study.events_treat)  # type: ignore[arg-type]
    c = float(study.events_control)  # type: ignore[arg-type]
    pt1 = float(study.person_time_treat)  # type: ignore[arg-type]
    pt2 = float(study.person_time_control)  # type: ignore[arg-type]

    if a == 0 and c == 0 and not include_double_zero:
        raise DoubleZeroError(
            f"study {study.id!r}: no events in either arm, so it carries no "
            f"information about a {measure}"
        )

    if a == 0 or c == 0:
        a, c = a + correction, c + correction

    yi = math.log((a / pt1) / (c / pt2))
    vi = 1 / a + 1 / c
    if vi <= 0:
        raise DataError(f"study {study.id!r}: non-positive variance ({vi})")
    return yi, vi


@dataclass
class PooledResult:
    """The result of pooling a set of studies."""

    estimate: float          # on the reporting scale (exponentiated for ratios)
    ci_low: float
    ci_high: float
    estimate_log: float      # on the analysis scale
    se: float
    p_value: float
    k: int                   # number of studies pooled
    tau_squared: float
    q: float
    q_df: int
    q_p_value: float
    i_squared: float
    model: str
    weights: dict[str, float]  # percentage weight per study id
    confidence: float = 0.95
    # Study id -> why it was left out of this pooled estimate. A silently
    # dropped row would be as misleading as a silently wrong one.
    excluded: dict[str, str] = field(default_factory=dict)

    @property
    def significant(self) -> bool:
        """Whether the pooled estimate is significant at the 0.05 level."""
        return self.p_value < 0.05

    def favours(self, null: float) -> str:
        """Which side of the null the point estimate falls on."""
        if self.estimate < null:
            return "below-null"
        if self.estimate > null:
            return "above-null"
        return "null"


def _q_p_value(q: float, df: int) -> float:
    """Upper tail of chi-square with df degrees of freedom.

    Uses a regularised incomplete gamma via a series/continued-fraction split,
    so we stay dependency-free.
    """
    if df <= 0:
        return 1.0
    x, a = q / 2.0, df / 2.0
    if x <= 0:
        return 1.0
    if x < a + 1:
        # Series expansion for the lower incomplete gamma.
        total, term, n = 1.0 / a, 1.0 / a, 0
        while n < 1000:
            n += 1
            term *= x / (a + n)
            total += term
            if abs(term) < abs(total) * 1e-15:
                break
        return max(0.0, min(1.0, 1.0 - total * math.exp(-x + a * math.log(x) - math.lgamma(a))))
    # Continued fraction for the upper incomplete gamma (Lentz's method).
    tiny = 1e-300
    b, c, d = x + 1 - a, 1 / tiny, 1 / (x + 1 - a)
    h = d
    for i in range(1, 1000):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1 / d
        delta = d * c
        h *= delta
        if abs(delta - 1) < 1e-15:
            break
    return max(0.0, min(1.0, h * math.exp(-x + a * math.log(x) - math.lgamma(a))))


def pool(
    studies: list[Study],
    measure: str,
    model: str = "random",
    confidence: float = 0.95,
    include_double_zero: bool = False,
) -> PooledResult:
    """Pool studies into a single estimate.

    `model` is "random" (DerSimonian-Laird) or "fixed" (inverse variance).
    tau-squared, Q and I-squared are reported for both models; under the fixed
    model they describe the heterogeneity without being used for weighting.

    Studies with no events in either arm are dropped by default and listed in
    `PooledResult.excluded`. Set `include_double_zero` to pool them under a
    continuity correction instead, which is what some meta-analysis software
    does and what reproducing such software requires.
    """
    if len(studies) < 1:
        raise DataError("cannot pool an empty set of studies")
    if model not in ("random", "fixed"):
        raise DataError(f"unknown model {model!r}; use 'random' or 'fixed'")

    pairs: list[tuple[str, float, float]] = []
    excluded: dict[str, str] = {}
    for study in studies:
        try:
            pairs.append((study.id, *effect_size(
                study, measure, include_double_zero=include_double_zero
            )))
        except DoubleZeroError as exc:
            if include_double_zero:
                # The caller asked for these studies and this one still
                # cannot be pooled, so the problem is real, not a policy.
                raise
            excluded[study.id] = str(exc).split(": ", 1)[-1]

    if not pairs:
        reasons = "; ".join(f"{sid} ({why})" for sid, why in excluded.items())
        raise DataError(
            f"no studies left to pool after excluding {len(excluded)} with "
            f"no events in either arm: {reasons}"
        )

    ids = [p[0] for p in pairs]
    y = [p[1] for p in pairs]
    v = [p[2] for p in pairs]
    k = len(y)

    # --- Fixed-effect pass. Needed regardless: Q is defined against it. ---
    w = [1.0 / vi for vi in v]
    sum_w = sum(w)
    theta_fe = sum(wi * yi for wi, yi in zip(w, y)) / sum_w

    q = sum(wi * (yi - theta_fe) ** 2 for wi, yi in zip(w, y))
    df = k - 1
    if df > 0:
        c_term = sum_w - sum(wi**2 for wi in w) / sum_w
        tau2 = max(0.0, (q - df) / c_term) if c_term > 0 else 0.0
        i2 = max(0.0, (q - df) / q) * 100 if q > 0 else 0.0
        q_p = _q_p_value(q, df)
    else:
        tau2, i2, q_p = 0.0, 0.0, 1.0

    # Random effects add tau-squared to every study's variance; fixed effects
    # weight by within-study variance alone.
    w_star = [1.0 / (vi + tau2) for vi in v] if model == "random" else w

    sum_w_star = sum(w_star)
    theta = sum(wi * yi for wi, yi in zip(w_star, y)) / sum_w_star
    se = math.sqrt(1.0 / sum_w_star)

    z_crit = Z_95 if abs(confidence - 0.95) < 1e-12 else z_quantile(confidence)
    lo_log, hi_log = theta - z_crit * se, theta + z_crit * se
    p = 2 * _norm_sf(abs(theta / se)) if se > 0 else 1.0

    is_ratio = measure in RATIO_MEASURES
    transform = math.exp if is_ratio else (lambda x: x)

    return PooledResult(
        estimate=transform(theta),
        ci_low=transform(lo_log),
        ci_high=transform(hi_log),
        estimate_log=theta,
        se=se,
        p_value=p,
        k=k,
        tau_squared=tau2,
        q=q,
        q_df=df,
        q_p_value=q_p,
        i_squared=i2,
        model=model,
        weights={sid: 100.0 * wi / sum_w_star for sid, wi in zip(ids, w_star)},
        confidence=confidence,
        excluded=excluded,
    )


def pool_meta(
    ma: MetaAnalysis,
    studies: list[Study] | None = None,
    include_double_zero: bool = False,
) -> PooledResult:
    """Pool a MetaAnalysis using its own declared measure and model."""
    return pool(
        ma.studies if studies is None else studies,
        measure=ma.measure,
        model=ma.model,
        include_double_zero=include_double_zero,
    )
