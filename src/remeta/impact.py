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

import math
from dataclasses import dataclass, field
from enum import Enum

from .model import MetaAnalysis
from .stats import PooledResult, pool

#: Default percentage change in the point estimate counted as substantial.
SUBSTANTIAL_THRESHOLD = 10.0

#: Absolute tolerance, on the reporting scale, allowed on any single compared
#: value under the "absolute" gate rule.
GATE_ABSOLUTE_PER_VALUE = 0.01

#: Absolute tolerance allowed across the estimate and both interval bounds
#: taken together, as an alternative to the per-value limit.
GATE_ABSOLUTE_COMBINED = 0.03

#: Floating-point slack so a difference of exactly one tolerance counts as
#: inside it. 0.345 - 0.34 is 0.0050000000000000044 in binary, so a bare <=
#: would reject a value sitting exactly on the limit.
GATE_EPSILON = 1e-9

#: Names of the tolerance rules, in the order they are tried.
GATE_RULES = ("absolute", "precision")


class Severity(str, Enum):
    """How much a retraction changed a pooled result."""

    REVERSED = "reversed"
    SIGNIFICANCE = "significance_change"
    UNVERIFIED = "unverified"
    SUBSTANTIAL = "substantial_change"
    MINIMAL = "minimal_change"
    UNPOOLABLE = "unpoolable"
    NO_RETRACTIONS = "no_retractions"

    @property
    def rank(self) -> int:
        """Sort order: higher means more urgent."""
        return {
            Severity.UNPOOLABLE: 6,
            Severity.REVERSED: 5,
            Severity.SIGNIFICANCE: 4,
            Severity.UNVERIFIED: 3,
            Severity.SUBSTANTIAL: 2,
            Severity.MINIMAL: 1,
            Severity.NO_RETRACTIONS: 0,
        }[self]

    @property
    def actionable(self) -> bool:
        """Whether this is a finding a human should act on.

        Deliberately a membership test rather than a rank threshold, because
        UNVERIFIED ranks high and is NOT actionable: ReMeta has no finding to
        act on there, only an input it could not verify. Putting it in the
        same queue as a gated verdict is exactly what the gate exists to
        prevent, so do not "fix" this into `rank >= n`.
        """
        return self in _ACTIONABLE


#: The severity classes that represent a finding a human should act on.
#: UNVERIFIED is deliberately absent: see Severity.actionable.
_ACTIONABLE = frozenset({
    Severity.REVERSED,
    Severity.SIGNIFICANCE,
    Severity.UNPOOLABLE,
})


class GateState(str, Enum):
    """Whether ReMeta could reproduce the result the review printed.

    REPRODUCED  the estimate and both interval bounds are within tolerance
    PARTIAL     everything reported is within tolerance, but the interval
                was not fully reported, so the check is weaker
    FAILED      something reported falls outside tolerance
    UNANCHORED  the input declared nothing to compare against
    """

    REPRODUCED = "reproduced"
    PARTIAL = "partial"
    FAILED = "failed"
    UNANCHORED = "unanchored"


@dataclass(frozen=True)
class GateComparison:
    """One published number against the one ReMeta computed."""

    name: str            # "estimate", "ci_low" or "ci_high"
    reported: float
    computed: float
    difference: float    # computed - reported, on the reporting scale
    tolerance: float     # the limit that was applied to this value
    within: bool


@dataclass(frozen=True)
class Gate:
    """The result of the reproduction gate for one meta-analysis."""

    state: GateState
    rule: str | None = None                     # the rule that granted a pass
    rules_passed: tuple[str, ...] = ()
    comparisons: tuple[GateComparison, ...] = ()

    @property
    def ok(self) -> bool:
        """Whether a recomputed verdict may be reported at all."""
        return self.state in (GateState.REPRODUCED, GateState.PARTIAL)

    @property
    def anchored(self) -> bool:
        """Whether there was anything published to check against."""
        return self.state is not GateState.UNANCHORED

    def describe(self) -> str:
        """One line a researcher can act on."""
        if self.state is GateState.UNANCHORED:
            return "nothing published to check against; this verdict is unanchored"
        if self.state is GateState.FAILED:
            return "cannot reproduce the published result; no verdict is issued"
        published = next(
            (c.reported for c in self.comparisons if c.name == "estimate"), None
        )
        anchor = f" {published:g}" if published is not None else ""
        if self.state is GateState.PARTIAL:
            return (
                f"reproduces the published estimate{anchor} "
                f"({self.rule} rule); no published interval to check"
            )
        return f"reproduces the published estimate{anchor} and interval ({self.rule} rule)"


def precision_tolerance(reported: float) -> float:
    """Half a unit in the last digit of `reported`, as it was written.

    0.49 gives 0.005; 0.4896 gives 0.00005. Trailing zeros cannot survive
    JSON parsing, so a value printed as "0.70" arrives as 0.7 and gets the
    looser 0.05. That makes this rule generous rather than wrong, and the
    absolute rule is applied alongside it.
    """
    text = repr(float(reported))
    if "e" in text or "E" in text:
        # A magnitude far from 1; fall back to a relative half-unit.
        exponent = math.floor(math.log10(abs(reported))) if reported else 0
        return 0.5 * 10.0 ** (exponent - 3)
    decimals = len(text.partition(".")[2].rstrip("0")) or 1
    return 0.5 * 10.0 ** (-decimals)


def _pairs_to_check(ma: MetaAnalysis, computed: PooledResult) -> list[tuple[str, float, float]]:
    candidates = (
        ("estimate", ma.reported_estimate, computed.estimate),
        ("ci_low", ma.reported_ci_low, computed.ci_low),
        ("ci_high", ma.reported_ci_high, computed.ci_high),
    )
    return [(name, r, c) for name, r, c in candidates if r is not None]


def check_gate(ma: MetaAnalysis, computed: PooledResult | None = None) -> Gate:
    """Compare our pooling against the numbers the review actually printed.

    This gates everything else. If ReMeta cannot reproduce the published
    result, its recalculation of that result means nothing, and the analysis
    must be reported as unverified rather than as a finding.

    Two rules are tried. The "absolute" rule allows 0.01 on each compared
    value, or 0.03 across all of them; the "precision" rule allows half a
    unit in the last digit each value was printed to. A pass under either is
    a pass, and the rule that granted it is recorded.
    """
    if ma.reported_estimate is None:
        return Gate(state=GateState.UNANCHORED)

    if computed is None:
        computed = pool(ma.studies, ma.measure, ma.model)
    pairs = _pairs_to_check(ma, computed)
    diffs = [abs(c - r) for _, r, c in pairs]

    absolute_ok = (
        all(d <= GATE_ABSOLUTE_PER_VALUE + GATE_EPSILON for d in diffs)
        or sum(diffs) <= GATE_ABSOLUTE_COMBINED + GATE_EPSILON
    )
    precision_ok = all(
        abs(c - r) <= precision_tolerance(r) + GATE_EPSILON for _, r, c in pairs
    )
    rules_passed = tuple(
        name for name, ok in (("absolute", absolute_ok), ("precision", precision_ok)) if ok
    )
    rule = rules_passed[0] if rules_passed else None

    # Report each value against the tolerance that actually decided it.
    applied = (
        (lambda r: GATE_ABSOLUTE_PER_VALUE)
        if rule != "precision"
        else precision_tolerance
    )
    comparisons = tuple(
        GateComparison(
            name=name,
            reported=r,
            computed=c,
            difference=c - r,
            tolerance=applied(r),
            within=abs(c - r) <= applied(r) + GATE_EPSILON,
        )
        for name, r, c in pairs
    )

    if not rules_passed:
        state = GateState.FAILED
    elif ma.reported_ci_low is not None and ma.reported_ci_high is not None:
        state = GateState.REPRODUCED
    else:
        state = GateState.PARTIAL
    return Gate(state=state, rule=rule, rules_passed=rules_passed, comparisons=comparisons)


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
    gate: Gate = field(default_factory=lambda: Gate(state=GateState.UNANCHORED))

    def summary(self) -> str:
        """One-line description of the change, for logs and commit messages."""
        if self.severity is Severity.UNVERIFIED:
            return "unverified: the published result could not be reproduced"
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


def _gate_diff_note(gate: Gate) -> str:
    """Spell out which published numbers we could not match."""
    parts = [
        f"{c.name} published {c.reported:g} against computed {c.computed:g} "
        f"({c.difference:+.4g})"
        for c in gate.comparisons
        if not c.within
    ]
    return "gate detail: " + ("; ".join(parts) if parts else "no value matched")


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
    """Recompute `ma` without its retracted studies and classify the change.

    The reproduction gate runs first. If it fails, no recomputed verdict is
    produced at all: the severity is UNVERIFIED, `recalculated` stays None,
    and every change flag stays false. A comparison you cannot anchor to the
    published result is a different analysis wearing the same name.
    """
    removed = [s.id for s in ma.retracted_studies]
    survivors = ma.surviving_studies

    original = pool(ma.studies, ma.measure, ma.model)
    gate = check_gate(ma, original)

    if not gate.ok and gate.anchored:
        return Impact(
            meta_analysis_id=ma.id,
            severity=Severity.UNVERIFIED,
            original=original,
            recalculated=None,
            removed=removed,
            retracted_weight_pct=sum(
                original.weights.get(sid, 0.0) for sid in removed
            ),
            gate=gate,
            notes=_exclusion_notes(original) + [
                "ReMeta could not reproduce the result this analysis reports "
                "as published, so removing the retracted studies would say "
                "nothing reliable about it",
                _gate_diff_note(gate),
            ],
        )

    if not removed:
        # Still report the reproduced pooled estimate: it is the answer to
        # "what does this analysis say", which is worth printing even when
        # there is nothing to remove.
        return Impact(
            meta_analysis_id=ma.id,
            severity=Severity.NO_RETRACTIONS,
            original=original,
            recalculated=None,
            gate=gate,
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
            gate=gate,
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
        gate=gate,
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
