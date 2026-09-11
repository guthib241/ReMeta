# Claims

Every percentage and every decimal in [README.md](README.md) is listed here
with either its source, as a DOI plus a location in the paper, or the test
that proves it.

The purpose is not tidiness. It is that a reader who doubts any number in the
README can find where it came from in one file, and that a number cannot be
added to the README without someone having to say where it came from.
`scripts/claims_lint.py` fails continuous integration if a number appears in
the README without an entry here.

Test ids are paths into `tests/test_remeta.py`.

---

## 1. External claims

Each of these comes from a published paper, cited in the README's references
section. **The attribution and the wording were both checked** — the earlier
version of this project got both wrong, as recorded in section 5.

| Number | Claim | Source |
| --- | --- | --- |
| 8.4% | Excluding retracted trials changed the direction of the pooled effect in 8.4% of meta-analyses | Xu C et al., VITALITY Study I, *BMJ* 2025;389:e082068, abstract results |
| 16.0% | ...and changed statistical significance in 16.0%. **Changed in either direction, not "lost"** | same, abstract results |
| 42% | Effect estimate changed by at least 10% in 42% of primary outcomes | Graña Possamai C et al., *JAMA Intern Med* 2025;185(6):702-709, abstract results |
| 96% | 160 of 166 recalculated effect estimates fell inside the confidence interval of the original | same, results |

Also stated in the README's prose and covered by the entries above: the
cohort size of 3,902 replicated meta-analyses (VITALITY) and 166 recalculated
meta-analyses (JAMA). Both are integers, so the lint does not extract them;
they are recorded here anyway because they are load-bearing.

## 2. Statistical constants and thresholds

| Number | What it is | Source or test |
| --- | --- | --- |
| 10% | Default change in the point estimate counted as substantial | The 10 / 30 / 50% marks reported by Graña Possamai et al. 2025; `TestImpact::test_threshold_is_configurable` |
| 30% | Second mark used in that literature, quoted for context | same paper |
| 50% | Third mark used in that literature | same paper |
| 0.05 | Conventional two-sided significance boundary | `PooledResult.significant`; `TestImpact::test_removing_protective_trials_loses_significance` |
| 95% | Confidence level ReMeta reports by default | `TestPoolingAgainstReference::test_confidence_interval_on_ratio_scale` |
| 0.5 | Continuity correction added to all four cells of a zero-cell study, RevMan's default | `TestEffectSizes::test_continuity_correction_matches_revman_default` |
| 0.01 | Gate absolute tolerance, per compared value | `TestGateTolerance::test_absolute_thresholds_are_the_documented_ones` |
| 0.03 | Gate absolute tolerance, summed across the estimate and both bounds | same test |
| 0.005 | Gate precision tolerance for a value printed as 0.49, being half a unit in the last digit | `TestGateTolerance::test_precision_tolerance_is_half_a_unit_in_the_last_digit` |

**The 0.01 and 0.03 thresholds are attributed in this project's specification
to VITALITY Study I's replication tolerance. We were not able to verify that
attribution against the paper**, because its full text is not reachable from
this build environment. The numbers are therefore presented in the README as
ReMeta's own gate tolerance, with no claim about their provenance, and the
attribution should be confirmed against the paper's methods section before
any such claim is made. See section 5.

## 3. Reference validation: the BCG dataset

Published DerSimonian-Laird values for the BCG vaccine meta-analysis
(Colditz GA et al., *JAMA* 1994;271(9):698-702), widely reproduced by
independent implementations as `metafor::dat.bcg`. Every value below is
asserted in `TestPoolingAgainstReference`.

| Number | Quantity | Test |
| --- | --- | --- |
| 0.7141 | Pooled log risk ratio, negative | `test_random_effects_point_estimate` |
| 0.1787 | Standard error | `test_random_effects_standard_error` |
| 0.4896 | Risk ratio | `test_confidence_interval_on_ratio_scale` |
| 0.49 | The same risk ratio as ReMeta prints it, to two decimals | `TestCli::test_readme_headline_block_matches_real_output` |
| 0.3449 | Lower 95% bound | `test_confidence_interval_on_ratio_scale` |
| 0.6950 | Upper 95% bound | `test_confidence_interval_on_ratio_scale` |
| 0.3088 | tau-squared | `test_tau_squared` |
| 152.23 | Cochran's Q on 12 degrees of freedom | `test_cochrans_q` |
| 92.1% | I-squared | `test_i_squared` |
| 0.4303 | Fixed-effect pooled log risk ratio, negative | `test_fixed_effect_differs_from_random` |

## 4. Numbers ReMeta produces, shown in the README

The README's worked-output blocks are captured from real runs, not written by
hand. `TestCli::test_readme_headline_block_matches_real_output` re-runs the
command and fails if the README block and the live output differ, so none of
these can drift.

Every number here comes from `data/examples/example-significance-loss.json`
or `data/examples/example-unverified.json`, both of which are **synthetic**
and labelled as such in their own metadata.

| Number | Where | Test |
| --- | --- | --- |
| 0.74 | Published estimate declared by the significance-loss example, and the value ReMeta computes to two decimals | `TestShippedExamples::test_significance_example_passes_its_gate` |
| 0.7400 | The same, at gate precision | same |
| 0.7351 | The same estimate at full precision | `TestGateGovernsTheVerdict` |
| 0.735 | The same, rounded in the Python API example | `TestShippedExamples::test_significance_example_really_crosses_the_threshold` |
| 0.56 | Lower bound before removal | `test_readme_headline_block_matches_real_output` |
| 0.5600 | The same, at gate precision | same |
| 0.5629 | The same at full precision | same |
| 0.96 | Upper bound before removal | same |
| 0.9600 | The same, at gate precision | same |
| 0.024 | p-value before removal | same |
| 0.0238 | The same, as the Python API prints it | same |
| 65% | I-squared before removal | same |
| 0.047 | tau-squared before removal | same |
| 0.84 | Estimate after removing the retracted study | `TestShippedExamples::test_significance_example_really_crosses_the_threshold` |
| 0.843 | The same, rounded in the Python API example | same |
| 0.68 | Lower bound after removal | `test_readme_headline_block_matches_real_output` |
| 1.04 | Upper bound after removal | same |
| 0.112 | p-value after removal | same |
| 0% | I-squared after removal | same |
| 0.000 | tau-squared after removal | same |
| 14.7% | Change in the point estimate | `TestShippedExamples` |
| 32.3% | Share of the pooled weight the retracted study carried | `TestCli::test_json_output_is_valid_and_complete` |
| 0.00002 | Gate difference on the upper bound | `test_readme_headline_block_matches_real_output` |
| 0.00288 | Gate difference on the lower bound | same |
| 0.00491 | Gate difference on the estimate | same |
| 0.3000 | Published estimate declared by the unverified example | `TestShippedUnverifiedExample::test_example_fails_its_gate` |
| 0.1800 | Its published lower bound | same |
| 0.5000 | Its published upper bound | same |
| 0.43509 | Gate difference on its estimate | same |
| 0.38288 | Gate difference on its lower bound | same |
| 0.45998 | Gate difference on its upper bound | same |
| 0.51 | An illustrative `yi` in the input-format example, not a result | not a claim; schema illustration |
| 0.043 | An illustrative `vi` in the same example | not a claim; schema illustration |

## 5. Claims removed, and why

Recorded so the corrections are auditable rather than silent.

- **"89% of reviews were still uncorrected a year later", attributed to
  "Schneider et al."** Removed. The DOI given
  (`10.1080/08989621.2022.2082290`) belongs to Avenell A, Bolland MJ,
  Gamble GD, Grey A in *Accountability in Research*, not to Schneider. That
  paper's own reported figures are that 51% (45 of 88) of citing publications
  had findings likely to change, and that corrections were made by 5% (6 of
  130) of evidence syntheses and 11% (2 of 18) of guidelines. No 89% figure
  could be verified, so the claim is not made anywhere in the project.
  `git grep -i schneider` returns nothing.
- **The 8.4% and 16.0% figures credited to the JAMA study.** Corrected. They
  are from VITALITY Study I. The two papers are now cited separately for the
  figures each one reports.
- **"Lost statistical significance" for VITALITY's 16.0%.** Corrected to
  "changed", which is what the paper measured: significance changing in
  either direction.
- **A headline demo showing the real BCG dataset with seven trials removed
  and labelled SIGNIFICANCE CHANGED.** Removed. None of those tuberculosis
  trials is retracted, and no command in the repository produces that output.
  The gap it left is covered by `simulated_removal`, which banners any
  hypothetical removal, and by synthetic examples that are labelled as
  synthetic.

## 6. Structural numbers

Not claims. Listed because the lint deliberately has no allowlist: all
justification lives here rather than half of it in the script.

| Token | What it is |
| --- | --- |
| 0.1 | From the version string `0.1.0` in the captured output and the badge |
| 3.10 | Minimum supported Python version |
| 3.13 | Highest Python version in the CI matrix |
| 3.10% | An artefact of the badge URL `python-3.10%2B-blue`; the `%2B` is an encoded `+` |
| 10.1136 | DOI prefix, BMJ |
| 10.1001 | DOI prefix, JAMA Network |
| 10.1080 | DOI prefix, Taylor & Francis |
| 2025.0256 | Part of the JAMA DOI suffix `jamainternmed.2025.0256` |
| 08989621.2022 | Part of the *Accountability in Research* DOI suffix |
