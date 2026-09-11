# ReMeta

**Reassess meta-analysis results after study retractions.**

[![CI](https://github.com/guthib241/ReMeta/actions/workflows/ci.yml/badge.svg)](https://github.com/guthib241/ReMeta/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)
[![Dependencies: none](https://img.shields.io/badge/dependencies-none-lightgrey)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

A study in a systematic review gets retracted. ReMeta takes the review's
study-level data, removes the retracted study, recalculates the pooled
estimate, and tells you whether the conclusion actually changed.

```text
ReMeta 0.1.0
──────────────────────────────────────────────────────────

GATE: REPRODUCED — reproduces the published estimate and interval (absolute rule)
    estimate  published 0.7400     computed 0.7351     difference -0.00491   tolerance 0.01
    ci_low    published 0.5600     computed 0.5629     difference +0.00288   tolerance 0.01
    ci_high   published 0.9600     computed 0.9600     difference -0.00002   tolerance 0.01

Analysis: example-significance-loss
Title:    Worked example: retraction removes statistical significance
Outcome:  Synthetic outcome
Measure:  RR
Model:    random-effects
Studies:  4 (1 retracted)

Original
  RR      0.74
  95% CI  0.56–0.96
  p       0.024
  4 studies, I² 65%, τ² 0.047

After removing retracted studies
  RR      0.84
  95% CI  0.68–1.04
  p       0.112
  3 studies, I² 0%, τ² 0.000

Impact
  SIGNIFICANCE CHANGED
  Change in estimate: +14.7%
  Retracted weight:   32.3%
  Removed:            Fabricated 2015

Action: human review recommended

──────────────────────────────────────────────────────────
1 analysis checked · 1 needs human review
```

## Why ReMeta?

When a study included in a systematic review or meta-analysis is later
retracted, the important question is not simply whether the paper was
retracted — it is whether removing that study changes the review's conclusion.

Those are different questions, and only the second one matters for practice.
Some retractions barely move the pooled estimate. Others flip its direction.
Existing tools tell you that a review cites retracted work; they do not tell
you whether the review's answer survives without it.

That question has been asked at scale, and the answer is not reassuring. In a
retrospective cohort of 3,902 meta-analyses that included retracted trials,
removing those trials changed the direction of the pooled effect in 8.4% of
them and its statistical significance in 16.0%
([Xu et al., *BMJ*, 2025](https://doi.org/10.1136/bmj-2024-082068)).
A separate hand recalculation of 166 meta-analyses in high-impact journals
found the effect estimate moved by at least 10% in 42% of primary outcomes,
while 96% of recalculated estimates still fell inside the original confidence
interval ([Graña Possamai et al., *JAMA Internal Medicine*,
2025](https://doi.org/10.1001/jamainternmed.2025.0256)).

So most retractions are survivable and some are not, and the only way to know
which is to redo the arithmetic. ReMeta redoes the arithmetic.

## What it does

Given a meta-analysis and which of its studies are retracted, ReMeta:

1. **reproduces** the original pooled estimate from the study-level data,
2. **removes** the studies marked as retracted,
3. **recalculates** the pooled estimate, confidence interval and p-value,
4. **compares** the two results,
5. **classifies** the impact on a published set of thresholds,
6. **highlights** the cases that need human review.

This is a reproducible recalculation, not an AI opinion. You supply the
study-level data; ReMeta runs closed-form, deterministic statistics on it.
Anyone with the same numbers gets the same answer, by hand if they like.

Step 1 is a gate, not a formality, and it is enforced in code. Before forming
any verdict, ReMeta recomputes the estimate and confidence interval the
review itself printed. If it cannot reproduce them, **no verdict is issued at
all**: the result is `UNVERIFIED`, nothing is compared, and the command exits
`3`. A recalculation you cannot anchor to the published result is a different
analysis wearing the same name.

That is a verification problem in the input data, not a finding about the
review. See [The reproduction gate](#the-reproduction-gate).

## Quick start

```bash
git clone https://github.com/guthib241/ReMeta.git
cd ReMeta

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .

remeta --help
remeta check data/examples/example-significance-loss.json
```

On Windows, activate the virtual environment with:

```powershell
.venv\Scripts\activate
```

## Installation

ReMeta needs **Python 3.10 or newer** and nothing else. It has no
dependencies: the chi-square tail and normal quantiles are implemented
directly, so it runs on a locked-down laptop and in CI without a scientific
Python stack.

Install from a clone, as above, or straight from GitHub:

```bash
python -m pip install "git+https://github.com/guthib241/ReMeta.git"
```

Both give you the `remeta` command. `python -m remeta` works identically and
is handy when the script directory is not on your `PATH`:

```bash
python -m remeta check data/examples/example-significance-loss.json
```

To run ReMeta from a clone without installing anything at all:

```bash
PYTHONPATH=src python3 -m remeta check data/examples/example-significance-loss.json
```

## Your first analysis

The repository ships four input files you can run immediately.

```bash
remeta check data/examples/example-significance-loss.json
```

That produces the report at the top of this page. Reading it:

| Line | Meaning |
| --- | --- |
| `GATE` | Whether ReMeta reproduced what the review printed. Nothing below it means anything if this line says `FAILED`. |
| `Original` | The pooled estimate with all studies included, including the retracted one. |
| `After removing…` | The same calculation over the surviving studies only. |
| `Change in estimate` | Percentage move in the point estimate, on the reporting scale. |
| `Retracted weight` | Share of the original pooled weight the retracted studies carried. |
| `Impact` | The severity class (see below). |
| `Action` | Whether a human needs to look at this. |

Every published number the gate checked is shown against the one ReMeta
computed, at full precision, because rounding is exactly what the gate
adjudicates.

In this example a significant risk ratio of 0.74 (p = 0.024) becomes 0.84
(p = 0.112) once the fabricated trial is removed. The direction is unchanged
and the estimate only moves 14.7%, but the result crosses the conventional
significance boundary, so the review's claim no longer holds as stated.

Two more:

```bash
# The pooled effect crosses the null: the review's direction was wrong.
remeta check data/examples/example-direction-reversal.json

# The gate fires and ReMeta refuses to issue a verdict. Exits 3.
remeta check data/examples/example-unverified.json

# A real published meta-analysis with no retractions, used to validate the maths.
remeta check data/bcg_colditz_1994.json
```

The example files under `data/examples/` are **synthetic**, built to
demonstrate each severity class. `data/bcg_colditz_1994.json` is real
published trial data.

## The reproduction gate

Every analysis is checked against what the review printed before anything is
compared. The gate has four outcomes:

| State | Meaning | Verdict issued |
| --- | --- | --- |
| `REPRODUCED` | The estimate and both interval bounds match within tolerance. | yes |
| `PARTIAL` | Everything reported matches, but the interval was not reported, so the check is weaker. | yes, labelled |
| `FAILED` | Something reported falls outside tolerance. | **no** |
| `UNANCHORED` | The input declared nothing to compare against. | yes, labelled, and always ranked below anchored results |

Two tolerance rules are tried, and a pass under either is a pass. The report
records which one granted it.

| Rule | Tolerance |
| --- | --- |
| `absolute` | 0.01 on each compared value, or 0.03 across all of them |
| `precision` | Half a unit in the last digit each value was printed to, so 0.49 allows 0.005 |

A `FAILED` gate is the one case where ReMeta refuses to answer the question
you asked it. That is deliberate. Try it:

```bash
remeta check data/examples/example-unverified.json    # exits 3
```

```text
GATE: FAILED — cannot reproduce the published result; no verdict is issued
  ! estimate  published 0.3000     computed 0.7351     difference +0.43509   tolerance 0.01
  ! ci_low    published 0.1800     computed 0.5629     difference +0.38288   tolerance 0.01
  ! ci_high   published 0.5000     computed 0.9600     difference +0.45998   tolerance 0.01
```

When this happens, the input rows do not produce the published result. The
usual causes are an extraction error, a different pooling method, or a
different set of included studies. All of them are things to investigate in
the data, and none of them is a conclusion about the review.

## Simulated removal

Removing studies that are **not** retracted, to ask what would happen if they
were, is a legitimate thing to want. Presenting it as a retraction impact is
not: a reader who sees real trials listed under "removed" will conclude those
trials were retracted.

Set `"simulated_removal": true` on the analysis and ReMeta prints a banner
above every result, in text and in JSON. There is no flag to suppress it, and
a test asserts there never will be.

```text
SIMULATED REMOVAL — the studies removed below are NOT retracted. This is a
hypothetical recalculation, not a retraction impact.
```

## Input format

One JSON object per meta-analysis, or a JSON array of them. Each study
supplies either a 2×2 table of counts or a precomputed effect with its
variance, whichever the published forest plot gives you.

```json
{
  "id": "example-2024",
  "measure": "RR",
  "model": "random",
  "title": "Drug X for condition Y",
  "outcome": "All-cause mortality",
  "reported_estimate": 0.49,
  "studies": [
    {
      "id": "Smith 2011",
      "events_treat": 4,
      "total_treat": 123,
      "events_control": 11,
      "total_control": 139
    },
    {
      "id": "Jones 2014",
      "yi": -0.51,
      "vi": 0.043,
      "retracted": true,
      "retraction_reason": "Data fabrication"
    }
  ]
}
```

**Analysis fields**

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | yes | Unique identifier for this analysis. |
| `measure` | yes | Effect measure (see below). |
| `studies` | yes | At least two studies. |
| `model` | no | `random` (default) or `fixed`. |
| `title`, `outcome` | no | Free text, shown in the report. |
| `source_doi`, `is_primary_outcome` | no | Provenance. |
| `reported_estimate` | no | What the paper printed, for the reproduction gate. |
| `reported_ci_low`, `reported_ci_high` | no | The published interval. Supply both to get the strongest gate check. |
| `simulated_removal` | no | `true` when the removed studies are not actually retracted. |
| `metadata` | no | Any object; ReMeta stores it and does not interpret it. |

**Study fields**

| Field | Meaning |
| --- | --- |
| `id` | Unique within the analysis. |
| `events_treat`, `total_treat`, `events_control`, `total_control` | The 2×2 table. All four or none. |
| `events_treat`, `person_time_treat`, `events_control`, `person_time_control` | Event counts with person-time at risk, for incidence rate ratios. |
| `yi`, `vi` | Precomputed effect and its variance. `yi` is on the **log scale** for ratio measures. Both or neither. |
| `retracted` | `true` to exclude this study from the recalculation. Defaults to `false`. |
| `retraction_reason`, `doi`, `year`, `notes` | Provenance. |

If a study gives both a table and a precomputed effect, the precomputed
effect wins. Unrecognised fields are rejected rather than ignored, so a typo
in a key is an error you can see instead of a silently dropped retraction
flag.

## Supported measures and models

| Measure | From counts | From `yi`/`vi` | Null |
| --- | --- | --- | --- |
| `RR` risk ratio | 2×2 table | yes | 1 |
| `OR` odds ratio | 2×2 table | yes | 1 |
| `RD` risk difference | 2×2 table | yes | 0 |
| `IRR` incidence rate ratio | events + person-time | yes | 1 |
| `HR` hazard ratio | no | yes | 1 |
| `MD` mean difference | no | yes | 0 |
| `SMD` standardised mean difference | no | yes | 0 |

Ratio measures are pooled in log space and reported exponentiated.

An incidence rate ratio is a ratio of *rates*, so it needs person-time at
risk in each arm, not participant totals. A hazard ratio needs time-to-event
data and cannot be reconstructed from counts at all. ReMeta refuses both
rather than quietly computing a different quantity under the label you asked
for, and says which field to supply instead.

Two models are available, both conventional by design:

- `random` — DerSimonian-Laird random effects (the default)
- `fixed` — inverse-variance fixed effect

Cochran's Q, τ² and I² are reported for both. Under the fixed model they
describe the heterogeneity in the data without being used for weighting.

Zero cells in a 2×2 table get RevMan's default 0.5 continuity correction,
applied to all four cells and only when a cell is actually zero.

A study with **no events in either arm** is a different case: it carries no
information about the contrast, and correcting it would hand it a real pooled
weight it has not earned. Such studies are dropped, and every exclusion is
listed in the report and in the JSON, because a silently dropped row is as
misleading as a silently wrong one. Pass `include_double_zero=True` to the
Python API to pool them under the correction instead, which is what some
meta-analysis software does and what reproducing that software requires.

## Understanding the output

Every analysis lands in exactly one severity class:

| Class | What happened | Needs review |
| --- | --- | --- |
| `DIRECTION REVERSED` | The pooled effect crossed the null. The review's direction was wrong. | yes |
| `CANNOT BE POOLED` | Fewer than two studies survive. The result cannot be reproduced without the retracted work. | yes |
| `SIGNIFICANCE CHANGED` | The effect kept its direction but crossed the 0.05 boundary, in either direction. | yes |
| `UNVERIFIED` | The reproduction gate failed. No verdict was formed. | not a finding; fix the input |
| `SUBSTANTIAL SHIFT` | The estimate moved by at least 10% without changing the verdict. | no |
| `MINIMAL SHIFT` | The estimate moved by less than 10%. | no |
| `NO RETRACTIONS` | Nothing in this file is marked retracted. | no |

The 10% mark, and the 30% and 50% marks used in the literature, come from the
JAMA Internal Medicine recalculation cited above; `--threshold` changes it.
Direction reversal is only flagged when the original result was significant,
because a non-significant estimate drifting across the null is noise rather
than a reversal.

Exit codes make ReMeta usable in a pipeline:

| Code | Meaning |
| --- | --- |
| `0` | Nothing needs human review. |
| `1` | At least one analysis needs human review. |
| `2` | Usage or data error. |
| `3` | At least one analysis failed the reproduction gate, so no verdict could be issued for it. |

`3` outranks `1`: if part of a batch could not be verified, that is the
strongest thing ReMeta can honestly say about the batch.

`--json` prints the same information as machine-readable JSON, including a
`gate` object with a named comparison per value, both pooled results, the
severity class, any excluded studies and the notes. An analysis that failed
the gate carries `"actionable": false` and a null `recalculated`.

## Validation

The pooling engine is checked against the **BCG vaccine meta-analysis**
(Colditz et al. 1994), the standard reference dataset for meta-analysis
software. ReMeta reproduces its published DerSimonian-Laird values:

| Quantity | Published reference | ReMeta |
| --- | --- | --- |
| Pooled log RR | −0.7141 | −0.7141 |
| Standard error | 0.1787 | 0.1787 |
| Risk ratio (95% CI) | 0.4896 (0.3449–0.6950) | 0.4896 (0.3449–0.6950) |
| τ² | 0.3088 | 0.3088 |
| Cochran's Q (df = 12) | 152.23 | 152.23 |
| I² | 92.1% | 92.1% |

That is a check against independent implementations of the same estimators,
not a test of the code against itself, and it runs on every commit. Anyone
can verify it in R with `metafor::dat.bcg`.

Every number in this README is listed in [CLAIMS.md](CLAIMS.md) with its
source or the test that proves it, and continuous integration fails if a
number appears here without an entry there.

**The impact classification itself is not yet externally validated.** The
thresholds are taken from published work, but ReMeta has not been run against
the 166 hand-recalculated meta-analyses that would confirm it reaches the same
verdicts. Until that is done, ReMeta is a plausible tool rather than a
validated one. [docs/VALIDATION.md](docs/VALIDATION.md) sets out what is
validated today, what is in progress, and the pass/fail criteria stated in
advance.

## Limitations

- **Extraction is not solved.** ReMeta works on the numbers you give it. Getting
  study-level data out of published PDFs, tables and supplements is a separate,
  unsolved problem, and it is the real bottleneck in practice.
- **Garbage in, garbage out.** The recalculation is only as good as the extracted
  inputs and the `retracted` flags you set. ReMeta does not decide whether a study
  is trustworthy; retraction status is an input.
- **Conventional estimators, deliberately.** DerSimonian-Laird and normal-approximation
  intervals are used because the question is what *this* review would have concluded
  without the retracted study. Better estimators exist (REML, Paule-Mandel,
  Hartung-Knapp); switching would change the answer for reasons unrelated to the
  retraction.
- **Different methods give different numbers.** A review that used a method ReMeta
  does not implement may not reproduce. That is what the reproduction gate is for,
  and a failed reproduction is a verification problem, not a finding.
- **Few-study analyses need caution.** Normal-approximation intervals and
  DerSimonian-Laird τ² are both unreliable when only a handful of studies remain,
  which is exactly the situation a retraction creates.
- **Rare events.** The 0.5 continuity correction is known to bias odds ratios toward
  the null when events are rare.
- **Not a replacement for expert review.** The output is a ranked queue for a human.
  Nothing here should change a guideline without a person reading it.
- **Out of scope for now:** network meta-analysis, individual participant data, and
  dose-response models.

## CLI reference

```
remeta [--version] [--help] COMMAND ...
```

### `remeta check FILE [FILE ...]`

Reproduce the pooled estimate, remove the studies marked `"retracted": true`,
recalculate, and classify what changed. Multiple analyses are reported
most-severe first.

| Option | Effect |
| --- | --- |
| `--json` | Print machine-readable JSON instead of a report. |
| `--loo` | Also show a leave-one-out influence table. |
| `--threshold PCT` | Percent change counted as substantial (default 10). |
| `--no-color` | Disable coloured output. |

### `remeta fragility FILE [FILE ...]`

Report which single study each pooled result depends on most, and by how much
the estimate would move without it. This needs no retraction to have
happened: a review whose result hinges on one trial is fragile whether or not
that trial has been questioned yet.

| Option | Effect |
| --- | --- |
| `--threshold PCT` | Percent shift at which a result is called fragile (default 20). |
| `--no-color` | Disable coloured output. |

Colour is also disabled automatically when output is not a terminal, or when
the `NO_COLOR` environment variable is set.

## Python API

```python
from remeta import Severity, analyse, fragility, load

for ma in load("data/examples/example-significance-loss.json"):
    impact = analyse(ma)

    # The gate is on every result, and analyse() has already enforced it.
    print(ma.id, impact.gate.state.value, impact.gate.describe())
    # example-significance-loss reproduced
    #   reproduces the published estimate and interval (absolute rule)

    if impact.severity is Severity.UNVERIFIED:
        continue                      # no verdict exists to read

    print(" ", impact.severity.value, impact.summary())
    #   significance_change 0.735 -> 0.843 (+14.7%), p 0.0238 -> 0.112

    if impact.severity.actionable:
        print("  needs human review")

    study, shift = fragility(ma)
    print(f"  most influential study: {study} ({shift:+.1f}%)")
```

The public surface is small and importable straight from `remeta`:

| Name | Purpose |
| --- | --- |
| `load`, `from_dict` | Read `MetaAnalysis` objects from JSON or dictionaries. |
| `Study`, `MetaAnalysis` | The data model. |
| `pool`, `pool_meta` | Pool a set of studies into a `PooledResult`. |
| `effect_size` | Effect and variance for one study, on the analysis scale. |
| `analyse` | Recalculate without retracted studies; returns an `Impact`. |
| `Severity` | The severity classes, with `.rank` and `.actionable`. |
| `GateState`, `Gate`, `GateComparison` | The gate result and its per-value comparisons. |
| `check_gate` | The reproduction gate; returns a `Gate` with a `GateState`. |
| `leave_one_out`, `fragility` | Influence analysis. |
| `DataError` | Raised for every input problem, with a readable message. |
| `DoubleZeroError` | A `DataError` subclass for a study with no events in either arm. |

Invalid input raises `DataError` and nothing else, so a batch job can catch
one exception type and keep going.

## Development

```bash
git clone https://github.com/guthib241/ReMeta.git
cd ReMeta
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

There is nothing else to install. To build the distributions:

```bash
python -m pip install build
python -m build
```

## Testing

```bash
python -m unittest discover
```

Add `-v` to see the test names. The suite covers the pooling engine against
published reference values, effect-size calculation from counts including
zero cells and double zeros, incidence rate ratios from person-time, input
validation and error messages, every severity class, all four gate states
including the rounding boundary, leave-one-out influence, and the command
line interface including its exit codes.

Continuous integration runs it on Python 3.10 through 3.13, then runs every
command shown in this README and asserts its exit code, checks that every
number in this README is accounted for in `CLAIMS.md`, and verifies the
package still imports nothing outside the standard library.

## Contributing

Bug reports, validation datasets and code are all welcome. See
[CONTRIBUTING.md](CONTRIBUTING.md) — the short version is that any change to
the statistics needs a validation case from a published analysis, and ReMeta
stays dependency-free.

The single most useful contribution right now is digitised forest plots from
published meta-analyses that included retracted studies, with
`reported_estimate` filled in from the paper so the reproduction gate can
check them.

## References

- Xu C, Fan S, Tian Y, et al. Investigating the impact of trial retractions on
  the healthcare evidence ecosystem (VITALITY Study I): retrospective cohort
  study. *BMJ*. 2025;389:e082068.
  [doi:10.1136/bmj-2024-082068](https://doi.org/10.1136/bmj-2024-082068)
- Graña Possamai C, Cabanac G, Perrodeau E, Ghosn L, Ravaud P, Boutron I.
  Inclusion of Retracted Studies in Systematic Reviews and Meta-Analyses of
  Interventions: A Systematic Review and Meta-Analysis. *JAMA Intern Med*.
  2025;185(6):702-709.
  [doi:10.1001/jamainternmed.2025.0256](https://doi.org/10.1001/jamainternmed.2025.0256)
- Avenell A, Bolland MJ, Gamble GD, Grey A. A randomized trial alerting
  authors, with or without coauthors or editors, that research they cited in
  systematic reviews and guidelines has been retracted. *Account Res*. 2022.
  [doi:10.1080/08989621.2022.2082290](https://doi.org/10.1080/08989621.2022.2082290)
- DerSimonian R, Laird N. Meta-analysis in clinical trials. *Control Clin
  Trials*. 1986;7(3):177-188.
- Higgins JPT, Thompson SG. Quantifying heterogeneity in a meta-analysis.
  *Stat Med*. 2002;21(11):1539-1558.
- Colditz GA, Brewer TF, Berkey CS, et al. Efficacy of BCG vaccine in the
  prevention of tuberculosis: meta-analysis of the published literature.
  *JAMA*. 1994;271(9):698-702.

If you use ReMeta in research, please cite the underlying methodological work
as well as this tool.

## License

MIT. See [LICENSE](LICENSE).
