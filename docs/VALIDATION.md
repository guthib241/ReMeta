# Validation

ReMeta recomputes numbers that may end up informing clinical decisions. The
statistics therefore have to be checkable by someone who does not trust us.

This document states exactly what is validated today, what is not, and the
criteria by which the outstanding work will be judged — including the failure
criterion, stated in advance.

---

## Validated

### The pooling engine

The engine is validated against the **BCG vaccine meta-analysis** (Colditz et
al., *JAMA*, 1994): 13 trials of BCG vaccination against tuberculosis. This is
the standard reference dataset for meta-analysis software, and its
DerSimonian-Laird results are reproduced by independent implementations.

Running `pool(bcg_studies, "RR", model="random")`:

| Quantity | Published reference | ReMeta |
| --- | --- | --- |
| Pooled log RR | −0.7141 | −0.7141 |
| Standard error | 0.1787 | 0.1787 |
| Risk ratio | 0.4896 | 0.4896 |
| 95% CI | 0.3449 – 0.6950 | 0.3449 – 0.6950 |
| τ² (DerSimonian-Laird) | 0.3088 | 0.3088 |
| Cochran's Q | 152.23 (df = 12) | 152.23 (df = 12) |
| I² | 92.1% | 92.1% |

Fixed-effect pooling gives log RR −0.4303, which also matches. The gap between
the two models on this dataset is large, which makes it a good test: an error
in τ² estimation would show up immediately rather than hiding.

These are asserted in `tests/test_remeta.py::TestPoolingAgainstReference` and
run on every commit and pull request.

**Anyone can check this independently** in R:

```r
library(metafor)
dat <- escalc(measure="RR", ai=tpos, bi=tneg, ci=cpos, di=cneg, data=dat.bcg)
rma(yi, vi, data=dat, method="DL")
```

### The reproduction gate

Before comparing anything, ReMeta recomputes the estimate the source declared
in `reported_estimate`. The gate has three outcomes — match, mismatch, and
unchecked — and they are kept distinct on purpose: "we could not reproduce
this" and "there was nothing to reproduce against" are different situations
and must not be reported as the same thing.

The shipped reference dataset is asserted to reproduce, so drift in the
pooling code fails the suite rather than silently changing published numbers.

### Software behaviour

The test suite also covers effect-size calculation from 2×2 tables (including
zero cells and the continuity correction), input validation and error
messages, all six severity classes, leave-one-out influence, and the command
line interface including its exit codes. Continuous integration runs it on
Python 3.10 through 3.13, runs every command documented in the README, and
verifies the package still imports nothing outside the standard library.

That is software correctness, not scientific validation. It is listed here so
the distinction is not blurred.

---

## In progress

### The impact classification

The severity thresholds are not ours. They come from Graña Possamai et al.
(*JAMA Intern Med*, 2025), who recalculated 166 meta-analyses after removing
the retracted study and reported effect estimate evolution at the 10 / 30 /
50% marks. Using their thresholds is what makes ReMeta's output comparable to
a published recalculation.

**The outstanding milestone: reproduce all 166.** That study is the ground
truth. For each meta-analysis it recalculated, ReMeta should produce the same
effect estimate evolution and the same verdict on whether significance
changed.

- **Success criterion:** agreement with the human recalculation on the direction
  and significance verdict for at least 95% of the 166, with effect estimate
  evolution within 1 percentage point.
- **Failure criterion, stated in advance:** if agreement falls below 90%, the
  automated recalculation is not reliable enough for this purpose and the
  project should not proceed to deployment on live retraction feeds. That
  result would be worth publishing as a negative finding.

Until this is done, **ReMeta is a plausible tool, not a validated one**, and
the README says so. The severity ladder currently rests on the thresholds
being reasonable, not on evidence that ReMeta assigns them the way a human
recalculating by hand would.

### Broader estimator coverage

Only DerSimonian-Laird and inverse-variance pooling are implemented. Reviews
that used Mantel-Haenszel, Peto, REML or Hartung-Knapp will not reproduce, and
will correctly fail the reproduction gate rather than be silently compared
under a different method. Adding those estimators as explicit options, each
with its own reference validation, is future work.

### Extraction

Everything above assumes the forest plot numbers are already in hand. Getting
them out of published PDFs, tables and supplements is **not started and not
solved**, and it is the real bottleneck in practice. Extraction accuracy will
need its own validation against hand-extracted data before any end-to-end
claim can be made.

---

## Why conventional estimators

ReMeta uses DerSimonian-Laird and inverse-variance pooling with
normal-approximation intervals. Better estimators exist (REML, Paule-Mandel,
Hartung-Knapp intervals).

Using them by default here would be a mistake. The question is *what would
this published review have concluded without the retracted study* — so ReMeta
must reproduce the method the review actually used. A different estimator
changes the answer for reasons unrelated to the retraction, which is precisely
the confound this tool exists to avoid.

The reproduction gate enforces this: if ReMeta cannot reproduce the estimate
the review printed, the recalculation is marked unverified rather than
reported as a finding.

---

## Limitations

Statistical and data limitations that hold even where ReMeta is working
correctly:

- **The inputs are yours.** ReMeta is only as good as the study-level data and
  the `retracted` flags supplied to it. It does not judge whether a study is
  trustworthy; retraction status is an input, not an output.
- **Normal-approximation confidence intervals**, matching RevMan. These are poor
  when very few studies remain — which is exactly what a retraction can cause.
  Hartung-Knapp would be better but breaks method-matching (above).
- **DerSimonian-Laird τ² is unreliable with few studies**, and tends to be
  underestimated, which makes random-effects intervals too narrow. The same
  caution applies with more force after studies are removed.
- **0.5 continuity correction for zero cells**, matching RevMan's default. Known
  to bias odds ratios toward the null with rare events.
- **Percentage change is computed on the reporting scale** (the ratio itself for
  ratio measures), matching how the published recalculations report "effect
  estimate evolution". On a log scale the same shift would look different.
- **Direction reversal is only flagged when the original result was
  significant.** A non-significant estimate crossing the null is noise, not a
  reversal.
- **The 0.05 significance boundary is a convention**, and a result moving from
  p = 0.049 to p = 0.051 is flagged as a significance change even though almost
  nothing about the evidence has changed. The percentage change and the
  confidence intervals are reported alongside it for exactly this reason.
- **Removing studies is not the only correct response to a retraction.** A review
  might instead need re-extraction, a different model, or a full reanalysis.
  ReMeta answers one specific, narrow question.
- **No support for** network meta-analysis, individual participant data,
  dose-response models, or multi-arm trials with shared control groups.
- **Not a replacement for expert review.** The output is a ranked queue for a
  human, and nothing in it should change a guideline without a person reading
  it.

---

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
- DerSimonian R, Laird N. Meta-analysis in clinical trials. *Control Clin
  Trials*. 1986;7(3):177-188.
- Higgins JPT, Thompson SG. Quantifying heterogeneity in a meta-analysis.
  *Stat Med*. 2002;21(11):1539-1558.
- Colditz GA, Brewer TF, Berkey CS, et al. Efficacy of BCG vaccine in the
  prevention of tuberculosis: meta-analysis of the published literature.
  *JAMA*. 1994;271(9):698-702.
