"""Retraction impact analysis.

The core operation: recompute a published pooled estimate with the retracted
studies removed, and classify what changed.

The severity ladder is ordered by what a reader of the review would have to
do about it:

  REVERSED      the pooled effect crossed the null; the review's direction
                was wrong
  SIGNIFICANCE  the effect kept its direction but crossed the 0.05 boundary
                in one direction or the other
  SUBSTANTIAL   the estimate moved by >=10% without changing the verdict
  MINIMAL       the estimate moved by <10%
  UNPOOLABLE    too few studies survive to pool at all

The 10 / 30 / 50% thresholds are not ours. They come from Graña Possamai et
al., "Inclusion of Retracted Studies in Systematic Reviews and Meta-Analyses
of Interventions" (JAMA Intern Med. 2025;185(6):702-709), which recalculated
166 meta-analyses after removing the retracted study and reported effect
estimate evolution at those marks. Using their thresholds is what makes our
output comparable to their published recalculation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .model import MetaAnalysis
from .stats import PooledResult, pool

#: Default percentage change in the point estimate counted as substantial.
SUBSTANTIAL_THRESHOLD = 10.0

#: Default tolerance, in percent, for accepting a reproduction of a published
#: estimate. Published forest plots are usually rounded to two or three
#: significant figures, so an exact match is not expected.
REPRODUCTION_TOLERANCE = 5.0


class Severity(str, Enum):
    """How much a retraction changed a pooled result."""

    REVERSED = "reversed"
    SIGNIFICANCE = "significance_change"
    SUBSTANTIAL = "substantial_change"
    MINIMAL = "minimal_change"
    UNPOOLABLE = "unpoolable"
    NO_RETRACTIONS = "no_retractions"

    @property
    def rank(self) -> int:
        """Sort order: higher means more urgent."""
        return {
            Severity.UNPOOLABLE: 5,
            Severity.REVERSED: 4,
            Severity.SIGNIFICANCE: 3,
            Severity.SUBSTANTIAL: 2,
            Severity.MINIMAL: 1,
            Severity.NO_RETRACTIONS: 0,
        }[self]

    @property
    def actionable(self) -> bool:
        """Whether a human needs to look at this review."""
        return self.rank >= 3


@dataclass
class Reproduction:
    """Whether ReMeta could reproduce the estimate the review printed.

    `status` is one of:
      "match"      recomputed estimate agrees with the published one
      "mismatch"   it does not; the comparison below is unverified
      "unchecked"  the input declared no published estimate to check against
    """

    status: str
    computed: float | None = None
    reported: float | None = None
    difference_pct: float | None = None
    tolerance_pct: float = REPRODUCTION_TOLERANCE

    @property
    def ok(self) -> bool:
        return self.status == "match"

    @property
    def checked(self) -> bool:
        return self.status != "unchecked"


@dataclass
class Impact:
    """What removing the retracted studies did to a pooled result."""

    meta_analysis_id: str
    severity: Severity
    original: PooledResult | None
    recalculated: PooledResult | None
    removed: list[str] = field(default_factory=list)
    # Percentage change in the point estimate, on the reporting scale.
    evolution_pct: float | None = None
    lost_significance: bool = False
    gained_significance: bool = False
    direction_reversed: bool = False
    within_original_ci: bool | None = None
    retracted_weight_pct: float = 0.0
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """One-line description of the change, for logs and commit messages."""
        if self.severity is Severity.NO_RETRACTIONS:
            return "no retracted studies in this analysis"
        if self.severity is Severity.UNPOOLABLE:
            return f"removing {len(self.removed)} study(ies) leaves too few to pool"
        assert self.original and self.recalculated
        change = (
            f" ({self.evolution_pct:+.1f}%)" if self.evolution_pct is not None else ""
        )
        return (
            f"{self.original.estimate:.3f} -> {self.recalculated.estimate:.3f}{change}, "
            f"p {self.original.p_value:.3g} -> {self.recalculated.p_value:.3g}"
        )


def _exclusion_notes(*results: PooledResult | None) -> list[str]:
    """Report every study a pooled estimate left out, and why."""
    seen: dict[str, str] = {}
    for result in results:
        if result is not None:
            seen.update(result.excluded)
    return [
        f"study {sid!r} was excluded from pooling: {why}"
        for sid, why in seen.items()
    ]


def _percent_change(new: float, old: float) -> float | None:
    if old == 0:
        return None
    return 100.0 * (new - old) / abs(old)


def analyse(
    ma: MetaAnalysis,
    substantial_threshold: float = SUBSTANTIAL_THRESHOLD,
) -> Impact:
    """Recompute `ma` without its retracted studies and classify the change."""
    removed = [s.id for s in ma.retracted_studies]
    survivors = ma.surviving_studies

    original = pool(ma.studies, ma.measure, ma.model)

    if not removed:
        # Still report the reproduced pooled estimate: it is the answer to
        # "what does this analysis say", which is worth printing even when
        # there is nothing to remove.
        return Impact(
            meta_analysis_id=ma.id,
            severity=Severity.NO_RETRACTIONS,
            original=original,
            recalculated=None,
            notes=_exclusion_notes(original),
        )

    retracted_weight = sum(original.weights.get(sid, 0.0) for sid in removed)

    if len(survivors) < 2:
        return Impact(
            meta_analysis_id=ma.id,
            severity=Severity.UNPOOLABLE,
            original=original,
            recalculated=None,
            removed=removed,
            retracted_weight_pct=retracted_weight,
            notes=_exclusion_notes(original) + [
                f"only {len(survivors)} study(ies) remain; the pooled result "
                "cannot be reproduced without the retracted work"
            ],
        )

    recalculated = pool(survivors, ma.measure, ma.model)

    null = ma.null_value
    evolution = _percent_change(recalculated.estimate, original.estimate)

    was_sig = original.significant
    now_sig = recalculated.significant
    lost = was_sig and not now_sig
    gained = not was_sig and now_sig

    # Direction reversal: the point estimate moved to the other side of the
    # null. Only meaningful if the original was significant, otherwise the
    # review was not claiming a direction to begin with.
    reversed_dir = (
        was_sig
        and (original.estimate - null) * (recalculated.estimate - null) < 0
    )

    within_ci = original.ci_low <= recalculated.estimate <= original.ci_high

    if reversed_dir:
        severity = Severity.REVERSED
    elif lost or gained:
        severity = Severity.SIGNIFICANCE
    elif evolution is not None and abs(evolution) >= substantial_threshold:
        severity = Severity.SUBSTANTIAL
    else:
        severity = Severity.MINIMAL

    notes: list[str] = _exclusion_notes(original, recalculated)
    if retracted_weight >= 50:
        notes.append(
            f"retracted studies carried {retracted_weight:.1f}% of the pooled weight"
        )
    if recalculated.i_squared > 75 and original.i_squared <= 75:
        notes.append("heterogeneity became substantial after removal")
    if not within_ci:
        notes.append("recalculated estimate falls outside the original confidence interval")

    return Impact(
        meta_analysis_id=ma.id,
        severity=severity,
        original=original,
        recalculated=recalculated,
        removed=removed,
        evolution_pct=evolution,
        lost_significance=lost,
        gained_significance=gained,
        direction_reversed=reversed_dir,
        within_original_ci=within_ci,
        retracted_weight_pct=retracted_weight,
        notes=notes,
    )


def leave_one_out(ma: MetaAnalysis) -> dict[str, PooledResult]:
    """Pool the analysis once per study, each time omitting that study.

    Used to answer a question the retraction feed cannot: which single study
    is this conclusion most dependent on? A review whose result hinges on one
    trial is fragile whether or not that trial has been retracted yet.

    Studies whose omission would leave fewer than two studies are skipped, so
    an analysis of two studies yields an empty result.
    """
    results: dict[str, PooledResult] = {}
    for study in ma.studies:
        rest = [s for s in ma.studies if s.id != study.id]
        if len(rest) < 2:
            continue
        results[study.id] = pool(rest, ma.measure, ma.model)
    return results


def fragility(ma: MetaAnalysis) -> tuple[str | None, float]:
    """Return the study whose removal moves the estimate most, and by how much.

    This is a dependency measure that needs no retraction to have happened.
    It is how ReMeta answers "which results are one bad study away from
    changing" before the bad study is found. Returns (None, 0.0) when the
    analysis is too small for a leave-one-out pass.
    """
    baseline = pool(ma.studies, ma.measure, ma.model)
    worst_id, worst_shift = None, 0.0
    for sid, result in leave_one_out(ma).items():
        shift = _percent_change(result.estimate, baseline.estimate)
        if shift is None:
            continue
        if abs(shift) > abs(worst_shift):
            worst_id, worst_shift = sid, shift
    return worst_id, worst_shift


def check_reproduction(
    ma: MetaAnalysis, tolerance_pct: float = REPRODUCTION_TOLERANCE
) -> Reproduction:
    """Compare our pooling against the estimate the review actually printed.

    This gates everything else. If we cannot reproduce the published number
    from the published forest plot, our recalculation of it means nothing,
    and the analysis must be reported as unverified rather than as a finding.
    """
    if ma.reported_estimate is None:
        return Reproduction(status="unchecked", tolerance_pct=tolerance_pct)
    computed = pool(ma.studies, ma.measure, ma.model).estimate
    diff = _percent_change(computed, ma.reported_estimate)
    status = "match" if diff is not None and abs(diff) <= tolerance_pct else "mismatch"
    return Reproduction(
        status=status,
        computed=computed,
        reported=ma.reported_estimate,
        difference_pct=diff,
        tolerance_pct=tolerance_pct,
    )


def reproduces_reported(
    ma: MetaAnalysis, tolerance_pct: float = REPRODUCTION_TOLERANCE
) -> tuple[bool, float | None]:
    """Boolean form of :func:`check_reproduction`.

    Returns (reproduced, percent difference). A missing published estimate is
    not a pass: it returns (False, None). Use :func:`check_reproduction` when
    you need to tell "could not reproduce" apart from "nothing to check".
    """
    result = check_reproduction(ma, tolerance_pct)
    return result.ok, result.difference_pct
