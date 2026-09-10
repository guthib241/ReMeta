"""ReMeta command line interface.

    remeta check <file.json>            recompute without retracted studies
    remeta check <file.json> --json     machine-readable output
    remeta check <file.json> --loo      leave-one-out influence table
    remeta fragility <file.json>        which study is each result leaning on

Exit codes:
    0  nothing actionable
    1  at least one analysis needs human reassessment
    2  usage or data error
    3  at least one analysis failed the reproduction gate
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap

from . import __version__
from .impact import (
    SUBSTANTIAL_THRESHOLD,
    Gate,
    GateState,
    Impact,
    Severity,
    analyse,
    fragility,
    leave_one_out,
)
from .model import DataError, MetaAnalysis, load
from .stats import PooledResult, pool

PROG = "remeta"

RULE = "─" * 58

COLOR = {
    Severity.REVERSED: "\033[1;35m",
    Severity.UNPOOLABLE: "\033[1;35m",
    Severity.SIGNIFICANCE: "\033[1;31m",
    Severity.SUBSTANTIAL: "\033[1;33m",
    Severity.MINIMAL: "\033[0;36m",
    Severity.NO_RETRACTIONS: "\033[0;32m",
    Severity.UNVERIFIED: "\033[1;35m",
}

GATE_COLOR = {
    GateState.REPRODUCED: "\033[0;32m",
    GateState.PARTIAL: "\033[0;36m",
    GateState.FAILED: "\033[1;35m",
    GateState.UNANCHORED: "\033[0;33m",
}
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

LABEL = {
    Severity.REVERSED: "DIRECTION REVERSED",
    Severity.UNPOOLABLE: "CANNOT BE POOLED",
    Severity.SIGNIFICANCE: "SIGNIFICANCE CHANGED",
    Severity.SUBSTANTIAL: "SUBSTANTIAL SHIFT",
    Severity.MINIMAL: "MINIMAL SHIFT",
    Severity.NO_RETRACTIONS: "NO RETRACTIONS",
    Severity.UNVERIFIED: "UNVERIFIED",
}

ACTION = {
    Severity.REVERSED: "human review recommended",
    Severity.UNPOOLABLE: "human review recommended",
    Severity.SIGNIFICANCE: "human review recommended",
    Severity.SUBSTANTIAL: "no review required, but the estimate moved",
    Severity.MINIMAL: "no review required",
    Severity.NO_RETRACTIONS: "no review required",
    Severity.UNVERIFIED: "check the input against the published forest plot",
}

MODEL_LABEL = {"random": "random-effects", "fixed": "fixed-effect"}


class _HelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Keep the hand-written epilog verbatim, but widen the option column."""

    def __init__(self, prog: str, **kwargs) -> None:
        kwargs.setdefault("max_help_position", 32)
        super().__init__(prog, **kwargs)

    def add_argument(self, action) -> None:
        super().add_argument(action)
        # argparse sizes the help column without allowing for the extra
        # indent it gives subcommand names, so a long command name wraps
        # onto its own line. Reserve that indent.
        if action.nargs == argparse.PARSER:
            try:
                self._action_max_length += self._indent_increment
            except AttributeError:  # pragma: no cover - argparse internals
                pass


# --------------------------------------------------------------------------
# formatting helpers
# --------------------------------------------------------------------------

def paint(text: str, style: str, on: bool) -> str:
    return f"{style}{text}{RESET}" if on else text


def fmt_value(x: float) -> str:
    """Format an effect estimate the way a forest plot would print it."""
    magnitude = abs(x)
    if magnitude >= 0.1 or magnitude == 0:
        return f"{x:.2f}"
    if magnitude >= 0.01:
        return f"{x:.3f}"
    return f"{x:.4f}"


def fmt_p(p: float) -> str:
    if p < 0.001:
        return "<0.001"
    return f"{p:.3f}"


def fmt_pct(x: float) -> str:
    return f"{x:+.1f}%"


def _pooled_block(title: str, result: PooledResult, measure: str, indent: str = "  ") -> list[str]:
    lines = [title]
    lines.append(f"{indent}{measure:<7} {fmt_value(result.estimate)}")
    lines.append(
        f"{indent}{'95% CI':<7} {fmt_value(result.ci_low)}–{fmt_value(result.ci_high)}"
    )
    lines.append(f"{indent}{'p':<7} {fmt_p(result.p_value)}")
    lines.append(
        f"{indent}{result.k} studies, I² {result.i_squared:.0f}%, "
        f"τ² {result.tau_squared:.3f}"
    )
    return lines


def _gate_block(gate: Gate, color: bool) -> list[str]:
    """The gate, printed before anything a reader might act on."""
    headline = f"GATE: {gate.state.value.upper()} — {gate.describe()}"
    out = ["GATE: " + paint(
        f"{gate.state.value.upper()}", GATE_COLOR[gate.state], color
    ) + f" — {gate.describe()}" if color else headline]
    for c in gate.comparisons:
        # Full precision here on purpose: rounding is the thing the gate
        # adjudicates, so the forest-plot formatter would hide the evidence.
        mark = " " if c.within else "!"
        out.append(
            f"  {mark} {c.name:<9} published {c.reported:<10.4f} "
            f"computed {c.computed:<10.4f} "
            f"difference {c.difference:+.5f}   tolerance {c.tolerance:g}"
        )
    return out


# --------------------------------------------------------------------------
# human-readable report
# --------------------------------------------------------------------------

def render_analysis(
    ma: MetaAnalysis, impact: Impact, color: bool, show_loo: bool
) -> list[str]:
    """Build the report block for one meta-analysis."""
    out: list[str] = []
    n_retracted = len(ma.retracted_studies)

    # The gate comes before anything else. A reader who stops after one line
    # must still know whether these numbers are anchored to the paper.
    out += _gate_block(impact.gate, color)
    out.append("")

    out.append(f"Analysis: {paint(ma.id, BOLD, color)}")
    if ma.title:
        out.append(f"Title:    {ma.title}")
    if ma.outcome:
        out.append(f"Outcome:  {ma.outcome}")
    out.append(f"Measure:  {ma.measure}")
    out.append(f"Model:    {MODEL_LABEL[ma.model]}")
    out.append(
        f"Studies:  {len(ma.studies)} ({n_retracted} retracted)"
        if n_retracted
        else f"Studies:  {len(ma.studies)} (none retracted)"
    )
    out.append("")

    if impact.original is not None:
        if impact.severity is Severity.UNVERIFIED:
            heading = "What ReMeta computes from these studies"
        elif not n_retracted:
            heading = "Pooled estimate"
        else:
            heading = "Original"
        out += _pooled_block(heading, impact.original, ma.measure)
        out.append("")

    if impact.recalculated is not None:
        out += _pooled_block(
            "After removing retracted studies", impact.recalculated, ma.measure
        )
        out.append("")
    elif impact.severity is Severity.UNPOOLABLE:
        survivors = len(ma.surviving_studies)
        out.append("After removing retracted studies")
        out.append(f"  cannot be pooled — only {survivors} study(ies) remain")
        out.append("")

    out.append("Impact")
    out.append("  " + paint(LABEL[impact.severity], COLOR[impact.severity], color))
    if impact.severity is Severity.NO_RETRACTIONS:
        out.append("  No study in this file is marked retracted, so there is "
                   "nothing to remove.")
    if impact.severity is Severity.UNVERIFIED:
        out.append("  No verdict is issued. The gate above did not pass, so a "
                   "recalculation")
        out.append("  would not tell you anything about the published review.")
    if impact.evolution_pct is not None:
        out.append(f"  Change in estimate: {fmt_pct(impact.evolution_pct)}")
    if impact.removed:
        out.append(f"  Retracted weight:   {impact.retracted_weight_pct:.1f}%")
        out.append(f"  Removed:            {', '.join(impact.removed)}")
    for note in impact.notes:
        out += _wrap_note(note)
    out.append("")

    if show_loo:
        out += _loo_block(ma, color)

    out.append(f"Action: {ACTION[impact.severity]}")
    return out


def _wrap_note(note: str) -> list[str]:
    """Wrap a note so a long explanation stays readable in a terminal."""
    return textwrap.wrap(
        note, width=74, initial_indent="  Note: ", subsequent_indent="        "
    ) or ["  Note: " + note]


def _loo_block(ma: MetaAnalysis, color: bool) -> list[str]:
    results = leave_one_out(ma)
    out = ["Leave-one-out influence"]
    if not results:
        out.append("  too few studies to assess")
        out.append("")
        return out
    base = pool(ma.studies, ma.measure, ma.model).estimate
    rows = []
    for sid, res in results.items():
        shift = 100.0 * (res.estimate - base) / abs(base) if base else 0.0
        rows.append((abs(shift), sid, res.estimate, shift))
    width = min(34, max(len(r[1]) for r in rows))
    for _, sid, est, shift in sorted(rows, key=lambda r: -r[0]):
        label = sid if len(sid) <= width else sid[: width - 1] + "…"
        out.append(f"  without {label:<{width}}  {fmt_value(est)}  ({fmt_pct(shift)})")
    out.append("")
    return out


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def _use_color(args) -> bool:
    if args.no_color or os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


def _load_all(paths: list[str]) -> list[MetaAnalysis]:
    analyses: list[MetaAnalysis] = []
    for path in paths:
        analyses.extend(load(path))
    seen: set[str] = set()
    for ma in analyses:
        if ma.id in seen:
            raise DataError(
                f"two meta-analyses share the id {ma.id!r}; ids must be unique "
                f"across all input files"
            )
        seen.add(ma.id)
    return analyses


def cmd_check(args) -> int:
    try:
        analyses = _load_all(args.path)
        results = [(ma, analyse(ma, substantial_threshold=args.threshold))
                   for ma in analyses]
    except DataError as exc:
        return _fail(exc)

    # Anchored verdicts first, most severe first within each group. An
    # unanchored verdict has nothing holding it to a published paper, so it
    # never outranks one that does.
    results.sort(key=lambda pair: (pair[1].gate.anchored, pair[1].severity.rank),
                 reverse=True)

    if args.json:
        _emit_json(results)
    else:
        _emit_text(results, _use_color(args), args.loo)

    if any(imp.severity is Severity.UNVERIFIED for _, imp in results):
        # The strongest thing we can say about this batch is that part of it
        # could not be verified, so that outranks an actionable verdict.
        return 3
    return 1 if any(imp.severity.actionable for _, imp in results) else 0


def _emit_text(results, color: bool, show_loo: bool) -> None:
    print()
    print(paint("ReMeta", BOLD, color) + paint(f" {__version__}", DIM, color))
    print(RULE)
    print()
    for index, (ma, impact) in enumerate(results):
        if index:
            print(RULE)
            print()
        print("\n".join(render_analysis(ma, impact, color, show_loo)))
        print()
    actionable = [imp for _, imp in results if imp.severity.actionable]
    unverified = [imp for _, imp in results if imp.severity is Severity.UNVERIFIED]
    print(RULE)
    noun = "analysis" if len(results) == 1 else "analyses"
    verb = "needs" if len(actionable) == 1 else "need"
    line = f"{len(results)} {noun} checked · {len(actionable)} {verb} human review"
    if unverified:
        line += f" · {len(unverified)} unverified"
    print(line)
    print()


def _pooled_dict(result: PooledResult | None) -> dict | None:
    if result is None:
        return None
    return {
        "estimate": round(result.estimate, 6),
        "ci_low": round(result.ci_low, 6),
        "ci_high": round(result.ci_high, 6),
        "p_value": result.p_value,
        "k": result.k,
        "i_squared": round(result.i_squared, 2),
        "tau_squared": round(result.tau_squared, 6),
        "q": round(result.q, 4),
        "q_df": result.q_df,
        "model": result.model,
        "excluded": result.excluded,
    }


def _emit_json(results) -> None:
    payload = {
        "tool": "remeta",
        "version": __version__,
        "results": [
            {
                "meta_analysis": ma.id,
                "title": ma.title,
                "outcome": ma.outcome,
                "measure": ma.measure,
                "model": ma.model,
                "primary_outcome": ma.is_primary_outcome,
                "severity": imp.severity.value,
                "actionable": imp.severity.actionable,
                "action": ACTION[imp.severity],
                "removed": imp.removed,
                "retracted_weight_pct": round(imp.retracted_weight_pct, 2),
                "evolution_pct": (
                    round(imp.evolution_pct, 3) if imp.evolution_pct is not None else None
                ),
                "lost_significance": imp.lost_significance,
                "gained_significance": imp.gained_significance,
                "direction_reversed": imp.direction_reversed,
                "within_original_ci": imp.within_original_ci,
                "gate": _gate_dict(imp.gate),
                "original": _pooled_dict(imp.original),
                "recalculated": _pooled_dict(imp.recalculated),
                "notes": imp.notes,
            }
            for ma, imp in results
        ],
    }
    print(json.dumps(payload, indent=2))


def _gate_dict(gate: Gate) -> dict:
    """The gate, as a pipeline reads it. This is the critical one.

    JSON is what an automated consumer acts on, so the gate state travels
    with every result and an unverified analysis carries actionable=false.
    """
    return {
        "state": gate.state.value,
        "ok": gate.ok,
        "anchored": gate.anchored,
        "rule": gate.rule,
        "rules_passed": list(gate.rules_passed),
        "description": gate.describe(),
        "comparisons": [
            {
                "name": c.name,
                "reported": c.reported,
                "computed": round(c.computed, 6),
                "difference": round(c.difference, 6),
                "tolerance": c.tolerance,
                "within": c.within,
            }
            for c in gate.comparisons
        ],
    }


def cmd_fragility(args) -> int:
    try:
        analyses = _load_all(args.path)
        rows = [(ma, *fragility(ma)) for ma in analyses]
    except DataError as exc:
        return _fail(exc)

    color = _use_color(args)
    print()
    print(paint("ReMeta fragility", BOLD, color))
    print(RULE)
    print()
    print("Which single study is each pooled result leaning on?")
    print("This needs no retraction to have happened.")
    print()
    for ma, worst, shift in rows:
        print(f"Analysis: {paint(ma.id, BOLD, color)}")
        if worst is None:
            print("  too few studies to assess (leave-one-out needs at least 3)")
        else:
            fragile = abs(shift) >= args.threshold
            print(f"  Most influential study: {worst}")
            print(f"  Estimate moves {fmt_pct(shift)} if it is removed")
            verdict = (
                f"fragile at the {args.threshold:g}% threshold"
                if fragile
                else f"robust at the {args.threshold:g}% threshold"
            )
            print("  " + paint(
                verdict,
                COLOR[Severity.SUBSTANTIAL] if fragile else COLOR[Severity.NO_RETRACTIONS],
                color,
            ))
        print()
    return 0


def _fail(exc: DataError) -> int:
    print(f"{PROG}: error: {exc}", file=sys.stderr)
    return 2


# --------------------------------------------------------------------------
# argument parsing
# --------------------------------------------------------------------------

DESCRIPTION = """\
Reassess meta-analysis results after study retractions.

ReMeta reproduces a published pooled estimate, removes the studies marked as
retracted, recalculates, and reports whether the conclusion actually changed.
Every number is a deterministic recalculation from the study-level data you
supply, not a judgement about the papers.
"""

EPILOG = """\
examples:
  remeta check data/examples/example-significance-loss.json
  remeta check data/examples/example-direction-reversal.json
  remeta check data/bcg_colditz_1994.json
  remeta check data/examples/*.json --json
  remeta check data/examples/example-significance-loss.json --loo
  remeta fragility data/bcg_colditz_1994.json

exit codes:
  0  nothing needs human review
  1  at least one analysis needs human review
  2  usage or data error
  3  at least one analysis failed the reproduction gate, so no verdict
     could be issued for it

Input is a JSON file describing one meta-analysis, or a list of them. See the
README for the schema and data/examples for working files.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=_HelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=f"{PROG} {__version__}",
        help="show the version and exit",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    check = sub.add_parser(
        "check",
        help="recalculate an analysis without its retracted studies",
        description=(
            "Reproduce the pooled estimate, remove the studies marked "
            '"retracted": true, recalculate, and classify what changed.'
        ),
        formatter_class=_HelpFormatter,
        epilog=EPILOG,
    )
    check.add_argument(
        "path", nargs="+", metavar="FILE",
        help="JSON file(s) describing one or more meta-analyses",
    )
    check.add_argument(
        "--json", action="store_true",
        help="print machine-readable JSON instead of a report",
    )
    check.add_argument(
        "--loo", action="store_true",
        help="also show a leave-one-out influence table",
    )
    check.add_argument(
        "--threshold", type=float, default=SUBSTANTIAL_THRESHOLD, metavar="PCT",
        help="percent change in the estimate counted as substantial "
             f"(default: {SUBSTANTIAL_THRESHOLD:g})",
    )
    check.add_argument("--no-color", action="store_true", help="disable coloured output")
    check.set_defaults(func=cmd_check)

    frag = sub.add_parser(
        "fragility",
        help="find the load-bearing study in each analysis",
        description=(
            "Report, for each analysis, which single study the pooled result "
            "depends on most. Useful before any retraction has happened."
        ),
        formatter_class=_HelpFormatter,
    )
    frag.add_argument(
        "path", nargs="+", metavar="FILE",
        help="JSON file(s) describing one or more meta-analyses",
    )
    frag.add_argument(
        "--threshold", type=float, default=20.0, metavar="PCT",
        help="percent shift at which a result is called fragile (default: 20)",
    )
    frag.add_argument("--no-color", action="store_true", help="disable coloured output")
    frag.set_defaults(func=cmd_fragility)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns the process exit code."""
    parser = build_parser()
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        parser.print_help()
        return 2
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except BrokenPipeError:  # e.g. `remeta check ... | head`
        return 0
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
