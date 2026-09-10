"""Tests for ReMeta.

Run with:  python -m unittest discover

The pooling tests validate against the BCG vaccine meta-analysis (Colditz et
al. 1994), the standard reference dataset for meta-analysis software. Its
DerSimonian-Laird results are widely reproduced by independent
implementations, which makes it a genuine external check rather than a test
of our code against itself.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from remeta import (
    MetaAnalysis,
    Severity,
    Study,
    analyse,
    check_reproduction,
    fragility,
    load,
    pool,
    pool_meta,
)
from remeta import __version__
from remeta.cli import build_parser, main
from remeta.impact import leave_one_out, reproduces_reported
from remeta.model import DataError, DoubleZeroError, from_dict
from remeta.stats import effect_size, z_quantile

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
EXAMPLES_DIR = DATA_DIR / "examples"

BCG_ROWS = [
    ("Aronson 1948", 4, 123, 11, 139),
    ("Ferguson & Simes 1949", 6, 306, 29, 303),
    ("Rosenthal 1960", 3, 231, 11, 220),
    ("Hart & Sutherland 1977", 62, 13598, 248, 12867),
    ("Frimodt-Moller 1973", 33, 5069, 47, 5808),
    ("Stein & Aronson 1953", 180, 1541, 372, 1451),
    ("Vandiviere 1973", 8, 2545, 10, 629),
    ("TPT Madras 1980", 505, 88391, 499, 88391),
    ("Coetzee & Berjak 1968", 29, 7499, 45, 7277),
    ("Rosenthal 1961", 17, 1716, 65, 1665),
    ("Comstock 1974", 186, 50634, 141, 27338),
    ("Comstock & Webster 1969", 5, 2498, 3, 2341),
    ("Comstock 1976", 27, 16913, 29, 17854),
]


def bcg_studies() -> list[Study]:
    return [
        Study(id=n, events_treat=a, total_treat=n1, events_control=c, total_control=n2)
        for n, a, n1, c, n2 in BCG_ROWS
    ]


def bcg_meta(**kwargs) -> MetaAnalysis:
    params = dict(id="bcg", measure="RR", model="random", studies=bcg_studies())
    params.update(kwargs)
    return MetaAnalysis(**params)


def run_cli(*argv: str) -> tuple[int, str, str]:
    """Invoke the CLI in-process and capture its exit code and output."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


# --------------------------------------------------------------------------
# statistics
# --------------------------------------------------------------------------

class TestPoolingAgainstReference(unittest.TestCase):
    """Published DerSimonian-Laird values for dat.bcg, log risk ratio."""

    def setUp(self) -> None:
        self.studies = bcg_studies()

    def test_random_effects_point_estimate(self):
        result = pool(self.studies, "RR", model="random")
        self.assertAlmostEqual(result.estimate_log, -0.7141, places=4)

    def test_random_effects_standard_error(self):
        result = pool(self.studies, "RR", model="random")
        self.assertAlmostEqual(result.se, 0.1787, places=4)

    def test_tau_squared(self):
        result = pool(self.studies, "RR", model="random")
        self.assertAlmostEqual(result.tau_squared, 0.3088, places=4)

    def test_cochrans_q(self):
        result = pool(self.studies, "RR", model="random")
        self.assertAlmostEqual(result.q, 152.233, places=2)
        self.assertEqual(result.q_df, 12)
        self.assertLess(result.q_p_value, 1e-20)

    def test_i_squared(self):
        result = pool(self.studies, "RR", model="random")
        self.assertAlmostEqual(result.i_squared, 92.12, places=1)

    def test_confidence_interval_on_ratio_scale(self):
        result = pool(self.studies, "RR", model="random")
        self.assertAlmostEqual(result.estimate, 0.4896, places=4)
        self.assertAlmostEqual(result.ci_low, 0.3449, places=3)
        self.assertAlmostEqual(result.ci_high, 0.6950, places=3)

    def test_fixed_effect_differs_from_random(self):
        fe = pool(self.studies, "RR", model="fixed")
        re = pool(self.studies, "RR", model="random")
        self.assertAlmostEqual(fe.estimate_log, -0.4303, places=4)
        self.assertNotAlmostEqual(fe.estimate_log, re.estimate_log, places=2)

    def test_fixed_effect_reports_heterogeneity_without_using_it(self):
        """Q, tau^2 and I^2 describe the data, not the weighting scheme."""
        fe = pool(self.studies, "RR", model="fixed")
        re = pool(self.studies, "RR", model="random")
        self.assertAlmostEqual(fe.q, re.q, places=9)
        self.assertAlmostEqual(fe.tau_squared, re.tau_squared, places=9)
        self.assertAlmostEqual(fe.i_squared, re.i_squared, places=9)
        # Fixed weights are the inverse variances alone.
        self.assertNotAlmostEqual(
            max(fe.weights.values()), max(re.weights.values()), places=3
        )

    def test_weights_sum_to_one_hundred(self):
        for model in ("fixed", "random"):
            result = pool(self.studies, "RR", model=model)
            self.assertAlmostEqual(sum(result.weights.values()), 100.0, places=6)

    def test_random_effects_weights_are_more_even(self):
        """Random effects should shrink the dominance of the largest trial."""
        fe = pool(self.studies, "RR", model="fixed")
        re = pool(self.studies, "RR", model="random")
        self.assertLess(max(re.weights.values()), max(fe.weights.values()))

    def test_pool_meta_uses_the_declared_measure_and_model(self):
        ma = bcg_meta(model="fixed")
        self.assertAlmostEqual(pool_meta(ma).estimate_log, -0.4303, places=4)
        self.assertEqual(pool_meta(ma).model, "fixed")

    def test_homogeneous_data_gives_zero_tau_squared(self):
        studies = [Study(id=f"s{i}", yi=0.5, vi=0.04) for i in range(4)]
        result = pool(studies, "RR", model="random")
        self.assertEqual(result.tau_squared, 0.0)
        self.assertEqual(result.i_squared, 0.0)
        self.assertAlmostEqual(result.q, 0.0, places=12)
        # With tau^2 = 0 the two models coincide.
        self.assertAlmostEqual(
            result.estimate_log, pool(studies, "RR", model="fixed").estimate_log, places=12
        )

    def test_single_study_pools_to_itself(self):
        result = pool([Study(id="only", yi=-0.5, vi=0.04)], "RR")
        self.assertEqual(result.k, 1)
        self.assertEqual(result.q_df, 0)
        self.assertEqual(result.tau_squared, 0.0)
        self.assertAlmostEqual(result.estimate_log, -0.5, places=12)
        self.assertAlmostEqual(result.se, 0.2, places=12)

    def test_pooling_nothing_is_an_error(self):
        with self.assertRaises(DataError):
            pool([], "RR")

    def test_unknown_model_is_an_error(self):
        with self.assertRaises(DataError):
            pool(bcg_studies(), "RR", model="bayesian")

    def test_wider_confidence_gives_wider_interval(self):
        narrow = pool(bcg_studies(), "RR", confidence=0.95)
        wide = pool(bcg_studies(), "RR", confidence=0.99)
        self.assertLess(wide.ci_low, narrow.ci_low)
        self.assertGreater(wide.ci_high, narrow.ci_high)
        self.assertEqual(wide.confidence, 0.99)


class TestEffectSizes(unittest.TestCase):
    def test_log_risk_ratio(self):
        s = Study(id="s", events_treat=10, total_treat=100,
                  events_control=20, total_control=100)
        yi, vi = effect_size(s, "RR")
        self.assertAlmostEqual(yi, -0.693147, places=5)   # log(0.10/0.20)
        self.assertAlmostEqual(vi, 1/10 - 1/100 + 1/20 - 1/100, places=9)

    def test_log_odds_ratio(self):
        s = Study(id="s", events_treat=10, total_treat=100,
                  events_control=20, total_control=100)
        yi, vi = effect_size(s, "OR")
        self.assertAlmostEqual(yi, -0.81093, places=4)    # log((10*80)/(90*20))
        self.assertAlmostEqual(vi, 1/10 + 1/90 + 1/20 + 1/80, places=9)

    def test_risk_difference(self):
        s = Study(id="s", events_treat=10, total_treat=100,
                  events_control=20, total_control=100)
        yi, vi = effect_size(s, "RD")
        self.assertAlmostEqual(yi, -0.10, places=9)
        self.assertAlmostEqual(vi, 0.1*0.9/100 + 0.2*0.8/100, places=12)

    def test_zero_cell_gets_continuity_correction(self):
        s = Study(id="s", events_treat=0, total_treat=50,
                  events_control=5, total_control=50)
        yi, vi = effect_size(s, "OR")
        self.assertTrue(all(map(lambda x: x == x, (yi, vi))))  # not NaN
        self.assertGreater(vi, 0)
        self.assertLess(yi, 0)

    def test_continuity_correction_matches_revman_default(self):
        """0.5 added to every cell, and only when a cell is zero."""
        s = Study(id="s", events_treat=0, total_treat=50,
                  events_control=5, total_control=50)
        yi, vi = effect_size(s, "OR")
        a, b, c, d = 0.5, 50.5, 5.5, 45.5
        import math
        self.assertAlmostEqual(yi, math.log((a * d) / (b * c)), places=12)
        self.assertAlmostEqual(vi, 1/a + 1/b + 1/c + 1/d, places=12)

    def test_no_correction_when_no_cell_is_zero(self):
        s = Study(id="s", events_treat=1, total_treat=50,
                  events_control=5, total_control=50)
        yi, _ = effect_size(s, "RR")
        import math
        self.assertAlmostEqual(yi, math.log((1/50) / (5/50)), places=12)

    def test_double_zero_study_is_refused_not_corrected(self):
        """Contract changed in Phase 0 R1.

        This test previously asserted that a double-zero study yielded a
        finite corrected effect. That was the defect: the correction handed a
        study with no events a real pooled weight. It is now refused, and
        TestDoubleZeroStudies covers the exclusion behaviour in full.
        """
        s = Study(id="s", events_treat=0, total_treat=40,
                  events_control=0, total_control=40)
        with self.assertRaises(DoubleZeroError):
            effect_size(s, "RR")
        yi, vi = effect_size(s, "RR", include_double_zero=True)
        self.assertAlmostEqual(yi, 0.0, places=12)
        self.assertGreater(vi, 0)

    def test_risk_difference_with_no_events_cannot_be_pooled(self):
        """RD takes no continuity correction, so a double-zero has no variance."""
        s = Study(id="s", events_treat=0, total_treat=40,
                  events_control=0, total_control=40)
        with self.assertRaises(DataError):
            effect_size(s, "RD")

    def test_precomputed_effect_passes_through(self):
        s = Study(id="s", yi=-0.5, vi=0.04)
        self.assertEqual(effect_size(s, "RR"), (-0.5, 0.04))

    def test_precomputed_effect_wins_over_a_table(self):
        s = Study(id="s", yi=-0.5, vi=0.04, events_treat=10, total_treat=100,
                  events_control=20, total_control=100)
        self.assertEqual(effect_size(s, "RR"), (-0.5, 0.04))

    def test_hazard_ratio_cannot_come_from_a_two_by_two_table(self):
        """A hazard ratio needs time-to-event data, not counts."""
        s = Study(id="s", events_treat=10, total_treat=100,
                  events_control=20, total_control=100)
        for measure in ("HR", "IRR", "MD", "SMD"):
            with self.subTest(measure=measure):
                with self.assertRaises(DataError) as ctx:
                    effect_size(s, measure)
                self.assertIn("yi", str(ctx.exception))

    def test_hazard_ratio_works_from_precomputed_effects(self):
        studies = [Study(id="a", yi=-0.3, vi=0.02), Study(id="b", yi=-0.2, vi=0.03)]
        result = pool(studies, "HR", model="fixed")
        self.assertLess(result.estimate, 1.0)   # reported exponentiated

    def test_difference_measures_are_not_exponentiated(self):
        studies = [Study(id="a", yi=-0.10, vi=0.001), Study(id="b", yi=-0.08, vi=0.001)]
        result = pool(studies, "RD", model="fixed")
        self.assertLess(result.estimate, 0.0)
        self.assertAlmostEqual(result.estimate, result.estimate_log, places=12)

    def test_z_quantile_matches_known_value(self):
        self.assertAlmostEqual(z_quantile(0.95), 1.959964, places=5)
        self.assertAlmostEqual(z_quantile(0.99), 2.575829, places=5)

    def test_z_quantile_rejects_impossible_confidence(self):
        for bad in (0.0, 1.0, -0.5, 2.0):
            with self.subTest(confidence=bad):
                with self.assertRaises(ValueError):
                    z_quantile(bad)


# --------------------------------------------------------------------------
# input validation
# --------------------------------------------------------------------------

class TestValidation(unittest.TestCase):
    def test_study_needs_data(self):
        with self.assertRaises(DataError):
            Study(id="empty")

    def test_incomplete_table_says_what_is_missing(self):
        with self.assertRaises(DataError) as ctx:
            Study(id="s", events_treat=10, total_treat=100)
        self.assertIn("events_control", str(ctx.exception))

    def test_yi_without_vi_says_so(self):
        with self.assertRaises(DataError) as ctx:
            Study(id="s", yi=0.4)
        self.assertIn("'vi'", str(ctx.exception))

    def test_negative_variance_rejected(self):
        with self.assertRaises(DataError):
            Study(id="s", yi=0.1, vi=-1.0)

    def test_zero_variance_rejected(self):
        with self.assertRaises(DataError):
            Study(id="s", yi=0.1, vi=0.0)

    def test_events_cannot_exceed_total(self):
        with self.assertRaises(DataError):
            Study(id="s", events_treat=200, total_treat=100,
                  events_control=5, total_control=100)

    def test_negative_events_rejected(self):
        with self.assertRaises(DataError):
            Study(id="s", events_treat=-1, total_treat=100,
                  events_control=5, total_control=100)

    def test_empty_total_rejected(self):
        with self.assertRaises(DataError):
            Study(id="s", events_treat=0, total_treat=0,
                  events_control=5, total_control=100)

    def test_non_numeric_effect_rejected(self):
        with self.assertRaises(DataError) as ctx:
            Study(id="s", yi="-0.5", vi=0.04)  # type: ignore[arg-type]
        self.assertIn("expected a number", str(ctx.exception))

    def test_non_finite_effect_rejected(self):
        with self.assertRaises(DataError):
            Study(id="s", yi=float("nan"), vi=0.04)
        with self.assertRaises(DataError):
            Study(id="s", yi=float("inf"), vi=0.04)

    def test_fractional_counts_rejected(self):
        with self.assertRaises(DataError):
            Study(id="s", events_treat=10.5, total_treat=100,  # type: ignore[arg-type]
                  events_control=5, total_control=100)

    def test_study_needs_an_id(self):
        with self.assertRaises(DataError):
            Study(id="", yi=0.1, vi=0.04)

    def test_meta_analysis_needs_two_studies(self):
        with self.assertRaises(DataError):
            MetaAnalysis(id="m", measure="RR", studies=[bcg_studies()[0]])

    def test_duplicate_study_ids_rejected(self):
        s = bcg_studies()[0]
        with self.assertRaises(DataError):
            MetaAnalysis(id="m", measure="RR", studies=[s, s])

    def test_unknown_measure_rejected(self):
        with self.assertRaises(DataError) as ctx:
            MetaAnalysis(id="m", measure="BOGUS", studies=bcg_studies())
        self.assertIn("Supported measures", str(ctx.exception))

    def test_unknown_model_rejected(self):
        with self.assertRaises(DataError):
            MetaAnalysis(id="m", measure="RR", studies=bcg_studies(), model="bayes")

    def test_null_value_depends_on_the_measure(self):
        self.assertEqual(bcg_meta().null_value, 1.0)
        self.assertTrue(bcg_meta().is_ratio)
        rd = MetaAnalysis(
            id="m", measure="RD",
            studies=[Study(id="a", yi=0.1, vi=0.01), Study(id="b", yi=0.2, vi=0.01)],
        )
        self.assertEqual(rd.null_value, 0.0)
        self.assertFalse(rd.is_ratio)


class TestLoading(unittest.TestCase):
    def _write(self, payload) -> Path:
        tmp = tempfile.mkdtemp()
        path = Path(tmp) / "input.json"
        text = payload if isinstance(payload, str) else json.dumps(payload)
        path.write_text(text, encoding="utf-8")
        return path

    def test_missing_file_is_a_data_error(self):
        with self.assertRaises(DataError) as ctx:
            load(Path(tempfile.mkdtemp()) / "nope.json")
        self.assertIn("no such file", str(ctx.exception))

    def test_directory_is_a_data_error(self):
        with self.assertRaises(DataError):
            load(Path(tempfile.mkdtemp()))

    def test_invalid_json_reports_the_position(self):
        with self.assertRaises(DataError) as ctx:
            load(self._write('{"id": "x", '))
        message = str(ctx.exception)
        self.assertIn("not valid JSON", message)
        self.assertIn("line 1", message)

    def test_missing_studies_key(self):
        with self.assertRaises(DataError) as ctx:
            load(self._write({"id": "x", "measure": "RR"}))
        self.assertIn("'studies'", str(ctx.exception))

    def test_missing_measure_key(self):
        with self.assertRaises(DataError) as ctx:
            load(self._write({"id": "x", "studies": []}))
        self.assertIn("measure", str(ctx.exception))

    def test_unknown_field_is_named(self):
        with self.assertRaises(DataError) as ctx:
            load(self._write({
                "id": "x", "measure": "RR", "effect_model": "random",
                "studies": [{"id": "a", "yi": 0.1, "vi": 0.1},
                            {"id": "b", "yi": 0.2, "vi": 0.1}],
            }))
        self.assertIn("effect_model", str(ctx.exception))

    def test_unknown_study_field_is_named(self):
        with self.assertRaises(DataError) as ctx:
            load(self._write({
                "id": "x", "measure": "RR",
                "studies": [{"id": "a", "yi": 0.1, "variance": 0.1},
                            {"id": "b", "yi": 0.2, "vi": 0.1}],
            }))
        self.assertIn("variance", str(ctx.exception))

    def test_study_without_id_is_named_by_position(self):
        with self.assertRaises(DataError) as ctx:
            load(self._write({
                "id": "x", "measure": "RR",
                "studies": [{"yi": 0.1, "vi": 0.1}, {"id": "b", "yi": 0.2, "vi": 0.1}],
            }))
        self.assertIn("study #1", str(ctx.exception))

    def test_empty_list_is_rejected(self):
        with self.assertRaises(DataError):
            load(self._write([]))

    def test_a_list_of_analyses_loads(self):
        one = {"id": "one", "measure": "RR",
               "studies": [{"id": "a", "yi": -0.1, "vi": 0.01},
                           {"id": "b", "yi": -0.2, "vi": 0.01}]}
        two = dict(one, id="two")
        loaded = load(self._write([one, two]))
        self.assertEqual([ma.id for ma in loaded], ["one", "two"])

    def test_from_dict_does_not_mutate_its_input(self):
        record = {
            "id": "x", "measure": "RR",
            "studies": [{"id": "a", "yi": -0.1, "vi": 0.01},
                        {"id": "b", "yi": -0.2, "vi": 0.01}],
        }
        snapshot = json.loads(json.dumps(record))
        from_dict(record)
        self.assertEqual(record, snapshot)

    def test_json_load_matches_in_memory(self):
        ma = bcg_meta()
        payload = {
            "id": ma.id, "measure": ma.measure, "model": ma.model,
            "studies": [
                {"id": s.id, "events_treat": s.events_treat,
                 "total_treat": s.total_treat, "events_control": s.events_control,
                 "total_control": s.total_control}
                for s in ma.studies
            ],
        }
        loaded = load(self._write(payload))
        self.assertEqual(len(loaded), 1)
        self.assertAlmostEqual(
            pool(loaded[0].studies, "RR", "random").estimate_log,
            pool(ma.studies, "RR", "random").estimate_log,
            places=10,
        )


# --------------------------------------------------------------------------
# impact analysis
# --------------------------------------------------------------------------

class TestImpact(unittest.TestCase):
    def test_no_retractions_is_reported_as_such(self):
        impact = analyse(bcg_meta())
        self.assertIs(impact.severity, Severity.NO_RETRACTIONS)
        self.assertFalse(impact.severity.actionable)
        self.assertEqual(impact.removed, [])
        self.assertIsNone(impact.recalculated)
        self.assertIn("no retracted studies", impact.summary())

    def test_no_retractions_still_reproduces_the_pooled_estimate(self):
        impact = analyse(bcg_meta())
        self.assertIsNotNone(impact.original)
        assert impact.original is not None
        self.assertAlmostEqual(impact.original.estimate, 0.4896, places=4)

    def test_removing_protective_trials_loses_significance(self):
        studies = bcg_studies()
        drop = {"Vandiviere 1973", "Rosenthal 1961", "Stein & Aronson 1953",
                "Aronson 1948", "Ferguson & Simes 1949", "Rosenthal 1960",
                "Frimodt-Moller 1973"}
        for s in studies:
            s.retracted = s.id in drop
        impact = analyse(bcg_meta(studies=studies))
        self.assertIs(impact.severity, Severity.SIGNIFICANCE)
        self.assertTrue(impact.lost_significance)
        self.assertFalse(impact.gained_significance)
        self.assertTrue(impact.severity.actionable)
        assert impact.original and impact.recalculated
        self.assertTrue(impact.original.significant)
        self.assertFalse(impact.recalculated.significant)

    def test_gained_significance_is_also_a_significance_change(self):
        """Removing a null-ish outlier can make a result significant."""
        studies = [
            Study(id="outlier", yi=0.55, vi=0.02, retracted=True),
            Study(id="a", yi=-0.30, vi=0.02),
            Study(id="b", yi=-0.28, vi=0.02),
        ]
        ma = MetaAnalysis(id="m", measure="RR", studies=studies, model="random")
        impact = analyse(ma)
        self.assertIs(impact.severity, Severity.SIGNIFICANCE)
        self.assertTrue(impact.gained_significance)
        self.assertFalse(impact.lost_significance)

    def test_removing_one_small_trial_is_minimal(self):
        studies = bcg_studies()
        for s in studies:
            s.retracted = s.id == "Comstock & Webster 1969"
        impact = analyse(bcg_meta(studies=studies))
        self.assertIs(impact.severity, Severity.MINIMAL)
        self.assertFalse(impact.severity.actionable)
        assert impact.evolution_pct is not None
        self.assertLess(abs(impact.evolution_pct), 10.0)

    def test_direction_reversal_detected(self):
        """A significant benefit that becomes a significant-side harm."""
        studies = [
            Study(id="big-fraud", yi=-1.2, vi=0.01, retracted=True),
            Study(id="a", yi=0.15, vi=0.02),
            Study(id="b", yi=0.20, vi=0.02),
        ]
        ma = MetaAnalysis(id="m", measure="RR", studies=studies, model="fixed")
        impact = analyse(ma)
        self.assertIs(impact.severity, Severity.REVERSED)
        self.assertTrue(impact.direction_reversed)
        assert impact.original and impact.recalculated
        self.assertLess(impact.original.estimate, 1.0)
        self.assertGreater(impact.recalculated.estimate, 1.0)

    def test_no_reversal_when_the_original_was_not_significant(self):
        """Crossing the null from a non-significant start is noise."""
        studies = [
            Study(id="wobble", yi=-0.20, vi=0.5, retracted=True),
            Study(id="a", yi=0.05, vi=0.5),
            Study(id="b", yi=0.06, vi=0.5),
        ]
        ma = MetaAnalysis(id="m", measure="RR", studies=studies, model="fixed")
        impact = analyse(ma)
        self.assertFalse(impact.direction_reversed)
        self.assertIsNot(impact.severity, Severity.REVERSED)

    def test_unpoolable_when_too_few_survive(self):
        studies = [
            Study(id="a", yi=-0.5, vi=0.02, retracted=True),
            Study(id="b", yi=-0.4, vi=0.02, retracted=True),
            Study(id="c", yi=-0.3, vi=0.02),
        ]
        ma = MetaAnalysis(id="m", measure="RR", studies=studies)
        impact = analyse(ma)
        self.assertIs(impact.severity, Severity.UNPOOLABLE)
        self.assertTrue(impact.severity.actionable)
        self.assertIsNone(impact.recalculated)
        self.assertIsNotNone(impact.original)
        self.assertIsNone(impact.evolution_pct)
        self.assertIn("too few to pool", impact.summary())

    def test_unpoolable_ranks_above_reversal(self):
        self.assertGreater(Severity.UNPOOLABLE.rank, Severity.REVERSED.rank)

    def test_retracted_weight_is_reported(self):
        studies = bcg_studies()
        for s in studies:
            s.retracted = s.id == "TPT Madras 1980"
        impact = analyse(bcg_meta(studies=studies))
        self.assertGreater(impact.retracted_weight_pct, 0)
        self.assertLess(impact.retracted_weight_pct, 100)

    def test_majority_retracted_weight_is_noted(self):
        studies = [
            Study(id="dominant", yi=-1.0, vi=0.001, retracted=True),
            Study(id="a", yi=-0.1, vi=0.05),
            Study(id="b", yi=-0.1, vi=0.05),
        ]
        ma = MetaAnalysis(id="m", measure="RR", studies=studies, model="fixed")
        impact = analyse(ma)
        self.assertGreater(impact.retracted_weight_pct, 50)
        self.assertTrue(any("pooled weight" in note for note in impact.notes))

    def test_threshold_is_configurable(self):
        studies = bcg_studies()
        for s in studies:
            s.retracted = s.id == "Hart & Sutherland 1977"
        lenient = analyse(bcg_meta(studies=studies), substantial_threshold=50.0)
        strict = analyse(bcg_meta(studies=studies), substantial_threshold=1.0)
        self.assertIs(lenient.severity, Severity.MINIMAL)
        self.assertIs(strict.severity, Severity.SUBSTANTIAL)

    def test_severity_ordering(self):
        self.assertGreater(Severity.REVERSED.rank, Severity.SIGNIFICANCE.rank)
        self.assertGreater(Severity.SIGNIFICANCE.rank, Severity.SUBSTANTIAL.rank)
        self.assertGreater(Severity.SUBSTANTIAL.rank, Severity.MINIMAL.rank)
        self.assertGreater(Severity.MINIMAL.rank, Severity.NO_RETRACTIONS.rank)
        self.assertTrue(Severity.REVERSED.actionable)
        self.assertTrue(Severity.SIGNIFICANCE.actionable)
        self.assertFalse(Severity.SUBSTANTIAL.actionable)
        self.assertFalse(Severity.MINIMAL.actionable)

    def test_outside_original_ci_is_noted(self):
        studies = [
            Study(id="fraud", yi=-1.2, vi=0.005, retracted=True),
            Study(id="a", yi=0.10, vi=0.01),
            Study(id="b", yi=0.12, vi=0.01),
        ]
        ma = MetaAnalysis(id="m", measure="RR", studies=studies, model="fixed")
        impact = analyse(ma)
        self.assertFalse(impact.within_original_ci)
        self.assertTrue(any("confidence interval" in n for n in impact.notes))

    def test_risk_difference_impact_uses_the_zero_null(self):
        studies = [
            Study(id="fraud", yi=-0.20, vi=0.0005, retracted=True),
            Study(id="a", yi=0.02, vi=0.001),
            Study(id="b", yi=0.03, vi=0.001),
        ]
        ma = MetaAnalysis(id="m", measure="RD", studies=studies, model="fixed")
        impact = analyse(ma)
        assert impact.original and impact.recalculated
        self.assertLess(impact.original.estimate, 0.0)
        self.assertGreater(impact.recalculated.estimate, 0.0)
        self.assertIs(impact.severity, Severity.REVERSED)


class TestReproductionGate(unittest.TestCase):
    """If we cannot reproduce the published number, we must say so."""

    def test_matching_published_estimate_passes(self):
        ma = bcg_meta(reported_estimate=0.4896)
        ok, diff = reproduces_reported(ma)
        self.assertTrue(ok)
        assert diff is not None
        self.assertLess(abs(diff), 1.0)

    def test_mismatched_published_estimate_fails(self):
        ma = bcg_meta(reported_estimate=0.90)
        ok, _ = reproduces_reported(ma)
        self.assertFalse(ok)

    def test_absent_published_estimate_is_not_a_pass(self):
        ok, diff = reproduces_reported(bcg_meta())
        self.assertFalse(ok)
        self.assertIsNone(diff)

    def test_status_distinguishes_unchecked_from_mismatch(self):
        self.assertEqual(check_reproduction(bcg_meta()).status, "unchecked")
        self.assertFalse(check_reproduction(bcg_meta()).checked)
        self.assertEqual(
            check_reproduction(bcg_meta(reported_estimate=0.90)).status, "mismatch"
        )
        self.assertTrue(check_reproduction(bcg_meta(reported_estimate=0.90)).checked)
        self.assertEqual(
            check_reproduction(bcg_meta(reported_estimate=0.4896)).status, "match"
        )

    def test_tolerance_is_configurable(self):
        ma = bcg_meta(reported_estimate=0.52)   # about 6% away
        self.assertFalse(check_reproduction(ma, tolerance_pct=5.0).ok)
        self.assertTrue(check_reproduction(ma, tolerance_pct=10.0).ok)

    def test_reproduction_reports_both_numbers(self):
        rep = check_reproduction(bcg_meta(reported_estimate=0.4896))
        self.assertAlmostEqual(rep.reported or 0.0, 0.4896, places=4)
        self.assertAlmostEqual(rep.computed or 0.0, 0.4896, places=4)


class TestFragility(unittest.TestCase):
    def test_identifies_most_influential_study(self):
        worst, shift = fragility(bcg_meta())
        self.assertIsNotNone(worst)
        self.assertGreater(abs(shift), 0)

    def test_leave_one_out_covers_every_study(self):
        results = leave_one_out(bcg_meta())
        self.assertEqual(len(results), len(BCG_ROWS))
        for result in results.values():
            self.assertEqual(result.k, len(BCG_ROWS) - 1)

    def test_leave_one_out_is_empty_for_two_studies(self):
        ma = MetaAnalysis(
            id="m", measure="RR",
            studies=[Study(id="a", yi=-0.1, vi=0.01), Study(id="b", yi=-0.2, vi=0.01)],
        )
        self.assertEqual(leave_one_out(ma), {})
        self.assertEqual(fragility(ma), (None, 0.0))

    def test_dominant_study_is_flagged_as_influential(self):
        studies = [
            Study(id="dominant", yi=-1.0, vi=0.001),
            Study(id="small-a", yi=0.1, vi=0.5),
            Study(id="small-b", yi=0.2, vi=0.5),
        ]
        ma = MetaAnalysis(id="m", measure="RR", studies=studies, model="fixed")
        worst, shift = fragility(ma)
        self.assertEqual(worst, "dominant")
        self.assertGreater(abs(shift), 50)


# --------------------------------------------------------------------------
# shipped data
# --------------------------------------------------------------------------

class TestShippedReferenceDataset(unittest.TestCase):
    def test_shipped_reference_dataset_reproduces(self):
        ma = load(DATA_DIR / "bcg_colditz_1994.json")[0]
        rep = check_reproduction(ma)
        self.assertTrue(rep.ok, f"reference dataset drifted by {rep.difference_pct}%")

    def test_reference_dataset_has_no_retractions(self):
        """It validates the maths, not the retraction logic."""
        ma = load(DATA_DIR / "bcg_colditz_1994.json")[0]
        self.assertEqual(ma.retracted_studies, [])
        self.assertIs(analyse(ma).severity, Severity.NO_RETRACTIONS)

    def test_reference_confidence_interval_matches_the_paper(self):
        ma = load(DATA_DIR / "bcg_colditz_1994.json")[0]
        result = pool_meta(ma)
        assert ma.reported_ci_low is not None and ma.reported_ci_high is not None
        self.assertAlmostEqual(result.ci_low, ma.reported_ci_low, places=3)
        self.assertAlmostEqual(result.ci_high, ma.reported_ci_high, places=3)


class TestShippedExamples(unittest.TestCase):
    """Every example fixture must actually demonstrate what its name claims.

    Added after a fixture named "significance-loss" shipped with data whose
    result was never significant to begin with. A worked example that does not
    work is worse than no example: it teaches the wrong thing silently.
    """

    EXPECTED = {
        "example-significance-loss.json": Severity.SIGNIFICANCE,
        "example-direction-reversal.json": Severity.REVERSED,
    }

    def test_every_example_demonstrates_its_claim(self):
        for filename, expected in self.EXPECTED.items():
            with self.subTest(fixture=filename):
                ma = load(EXAMPLES_DIR / filename)[0]
                impact = analyse(ma)
                self.assertIs(
                    impact.severity, expected,
                    f"{filename} claims {expected.value} but produces "
                    f"{impact.severity.value}",
                )

    def test_significance_example_really_crosses_the_threshold(self):
        ma = load(EXAMPLES_DIR / "example-significance-loss.json")[0]
        impact = analyse(ma)
        assert impact.original and impact.recalculated
        self.assertTrue(impact.original.significant)
        self.assertFalse(impact.recalculated.significant)
        self.assertTrue(impact.lost_significance)

    def test_reversal_example_really_crosses_the_null(self):
        ma = load(EXAMPLES_DIR / "example-direction-reversal.json")[0]
        impact = analyse(ma)
        assert impact.original and impact.recalculated
        self.assertLess(impact.original.estimate, 1.0)
        self.assertGreater(impact.recalculated.estimate, 1.0)
        self.assertTrue(impact.direction_reversed)

    def test_all_example_files_are_loadable(self):
        found = sorted(p.name for p in EXAMPLES_DIR.glob("*.json"))
        self.assertEqual(found, sorted(self.EXPECTED),
                         "an example fixture exists with no expectation declared")
        for path in EXAMPLES_DIR.glob("*.json"):
            self.assertTrue(load(path), f"{path.name} failed to load")

    def test_significance_example_reproduces_its_declared_estimate(self):
        ma = load(EXAMPLES_DIR / "example-significance-loss.json")[0]
        rep = check_reproduction(ma)
        self.assertEqual(rep.status, "match")

    def test_reversal_example_declares_no_published_estimate(self):
        ma = load(EXAMPLES_DIR / "example-direction-reversal.json")[0]
        self.assertEqual(check_reproduction(ma).status, "unchecked")

    def test_every_example_marks_at_least_one_retraction(self):
        for path in EXAMPLES_DIR.glob("*.json"):
            with self.subTest(fixture=path.name):
                ma = load(path)[0]
                self.assertTrue(ma.retracted_studies)
                for study in ma.retracted_studies:
                    self.assertTrue(study.retraction_reason)


# --------------------------------------------------------------------------
# command line interface
# --------------------------------------------------------------------------

class TestCli(unittest.TestCase):
    SIG_LOSS = str(EXAMPLES_DIR / "example-significance-loss.json")
    REVERSAL = str(EXAMPLES_DIR / "example-direction-reversal.json")
    BCG = str(DATA_DIR / "bcg_colditz_1994.json")

    def test_parser_builds(self):
        self.assertIsNotNone(build_parser())

    def test_no_arguments_prints_help_and_fails(self):
        code, out, _ = run_cli()
        self.assertEqual(code, 2)
        self.assertIn("usage: remeta", out)

    def test_help_mentions_both_commands_and_exit_codes(self):
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit) as ctx:
            main(["--help"])
        self.assertEqual(ctx.exception.code, 0)
        text = out.getvalue()
        for expected in ("check", "fragility", "exit codes", "examples:"):
            self.assertIn(expected, text)

    def test_subcommand_help_is_self_explanatory(self):
        for command in ("check", "fragility"):
            with self.subTest(command=command):
                out = io.StringIO()
                with redirect_stdout(out), self.assertRaises(SystemExit):
                    main([command, "--help"])
                self.assertIn("--threshold", out.getvalue())

    def test_version_matches_the_package(self):
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit) as ctx:
            main(["--version"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn(__version__, out.getvalue())

    def test_actionable_analysis_exits_one(self):
        code, out, err = run_cli("check", self.SIG_LOSS, "--no-color")
        self.assertEqual(code, 1)
        self.assertEqual(err, "")
        self.assertIn("SIGNIFICANCE CHANGED", out)
        self.assertIn("Action: human review recommended", out)
        self.assertIn("needs human review", out)

    def test_reversal_analysis_is_labelled(self):
        code, out, _ = run_cli("check", self.REVERSAL, "--no-color")
        self.assertEqual(code, 1)
        self.assertIn("DIRECTION REVERSED", out)

    def test_analysis_without_retractions_exits_zero(self):
        code, out, err = run_cli("check", self.BCG, "--no-color")
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertIn("NO RETRACTIONS", out)
        self.assertIn("0 need human review", out)

    def test_reproduction_status_is_printed(self):
        _, out, _ = run_cli("check", self.BCG, "--no-color")
        self.assertIn("Reproduction", out)
        self.assertIn("matches the published", out)

    def test_unreproduced_analysis_is_flagged(self):
        tmp = Path(tempfile.mkdtemp()) / "wrong.json"
        payload = json.loads(Path(self.BCG).read_text(encoding="utf-8"))
        payload["reported_estimate"] = 0.95
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        _, out, _ = run_cli("check", str(tmp), "--no-color")
        self.assertIn("FAILED", out)
        self.assertIn("unverified", out)

    def test_no_color_output_has_no_escape_codes(self):
        _, out, _ = run_cli("check", self.SIG_LOSS, "--no-color")
        self.assertNotIn("\033[", out)

    def test_json_output_is_valid_and_complete(self):
        code, out, _ = run_cli("check", self.SIG_LOSS, "--json")
        self.assertEqual(code, 1)
        payload = json.loads(out)
        self.assertEqual(payload["tool"], "remeta")
        self.assertEqual(payload["version"], __version__)
        self.assertEqual(len(payload["results"]), 1)
        result = payload["results"][0]
        self.assertEqual(result["meta_analysis"], "example-significance-loss")
        self.assertEqual(result["severity"], "significance_change")
        self.assertTrue(result["actionable"])
        self.assertTrue(result["lost_significance"])
        self.assertEqual(result["removed"], ["Fabricated 2015"])
        self.assertEqual(result["reproduction"]["status"], "match")
        self.assertLess(result["original"]["p_value"], 0.05)
        self.assertGreater(result["recalculated"]["p_value"], 0.05)

    def test_json_output_marks_an_unchecked_reproduction(self):
        _, out, _ = run_cli("check", self.REVERSAL, "--json")
        result = json.loads(out)["results"][0]
        self.assertEqual(result["reproduction"]["status"], "unchecked")
        self.assertIsNone(result["reproduction"]["reported"])

    def test_json_output_for_the_reference_dataset(self):
        code, out, _ = run_cli("check", self.BCG, "--json")
        self.assertEqual(code, 0)
        result = json.loads(out)["results"][0]
        self.assertEqual(result["severity"], "no_retractions")
        self.assertEqual(result["reproduction"]["status"], "match")
        self.assertIsNone(result["recalculated"])
        self.assertAlmostEqual(result["original"]["estimate"], 0.4896, places=4)

    def test_loo_flag_adds_an_influence_table(self):
        _, plain, _ = run_cli("check", self.SIG_LOSS, "--no-color")
        _, with_loo, _ = run_cli("check", self.SIG_LOSS, "--no-color", "--loo")
        self.assertNotIn("Leave-one-out", plain)
        self.assertIn("Leave-one-out influence", with_loo)
        self.assertIn("without Fabricated 2015", with_loo)

    def test_threshold_flag_changes_the_classification(self):
        studies = json.loads(Path(self.BCG).read_text(encoding="utf-8"))
        for study in studies["studies"]:
            study["retracted"] = study["id"] == "Hart & Sutherland 1977"
        tmp = Path(tempfile.mkdtemp()) / "one-retracted.json"
        tmp.write_text(json.dumps(studies), encoding="utf-8")
        _, lenient, _ = run_cli("check", str(tmp), "--no-color", "--threshold", "50")
        _, strict, _ = run_cli("check", str(tmp), "--no-color", "--threshold", "1")
        self.assertIn("MINIMAL SHIFT", lenient)
        self.assertIn("SUBSTANTIAL SHIFT", strict)

    def test_several_files_are_ranked_most_severe_first(self):
        code, out, _ = run_cli("check", self.SIG_LOSS, self.REVERSAL, self.BCG,
                               "--no-color")
        self.assertEqual(code, 1)
        self.assertIn("3 analyses checked", out)
        self.assertIn("2 need human review", out)
        order = [
            out.index("DIRECTION REVERSED"),
            out.index("SIGNIFICANCE CHANGED"),
            out.index("NO RETRACTIONS"),
        ]
        self.assertEqual(order, sorted(order))

    def test_duplicate_ids_across_files_are_rejected(self):
        code, _, err = run_cli("check", self.BCG, self.BCG)
        self.assertEqual(code, 2)
        self.assertIn("unique", err)

    def test_missing_file_exits_two_with_a_readable_message(self):
        code, out, err = run_cli("check", "does-not-exist.json")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("remeta: error:", err)
        self.assertIn("no such file", err)

    def test_malformed_json_exits_two(self):
        tmp = Path(tempfile.mkdtemp()) / "broken.json"
        tmp.write_text('{"id": "x",', encoding="utf-8")
        code, _, err = run_cli("check", str(tmp))
        self.assertEqual(code, 2)
        self.assertIn("not valid JSON", err)

    def test_unpoolable_input_exits_two_not_a_traceback(self):
        tmp = Path(tempfile.mkdtemp()) / "single.json"
        tmp.write_text(json.dumps({
            "id": "x", "measure": "RR",
            "studies": [{"id": "a", "yi": -0.2, "vi": 0.01}],
        }), encoding="utf-8")
        code, _, err = run_cli("check", str(tmp))
        self.assertEqual(code, 2)
        self.assertIn("at least 2 studies", err)

    def test_fragility_reports_the_load_bearing_study(self):
        code, out, err = run_cli("fragility", self.BCG, "--no-color")
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertIn("Most influential study: Hart & Sutherland 1977", out)
        self.assertIn("threshold", out)

    def test_fragility_threshold_flag(self):
        _, loose, _ = run_cli("fragility", self.BCG, "--no-color", "--threshold", "50")
        _, tight, _ = run_cli("fragility", self.BCG, "--no-color", "--threshold", "1")
        self.assertIn("robust", loose)
        self.assertIn("fragile", tight)

    def test_fragility_handles_a_two_study_analysis(self):
        tmp = Path(tempfile.mkdtemp()) / "pair.json"
        tmp.write_text(json.dumps({
            "id": "pair", "measure": "RR",
            "studies": [{"id": "a", "yi": -0.2, "vi": 0.01},
                        {"id": "b", "yi": -0.1, "vi": 0.01}],
        }), encoding="utf-8")
        code, out, _ = run_cli("fragility", str(tmp), "--no-color")
        self.assertEqual(code, 0)
        self.assertIn("too few studies to assess", out)

    def test_fragility_reports_data_errors_without_a_traceback(self):
        tmp = Path(tempfile.mkdtemp()) / "bad-measure.json"
        tmp.write_text(json.dumps({
            "id": "x", "measure": "HR",
            "studies": [{"id": "a", "events_treat": 5, "total_treat": 50,
                         "events_control": 9, "total_control": 50},
                        {"id": "b", "events_treat": 4, "total_treat": 40,
                         "events_control": 8, "total_control": 40}],
        }), encoding="utf-8")
        code, _, err = run_cli("fragility", str(tmp))
        self.assertEqual(code, 2)
        self.assertIn("remeta: error:", err)


# --------------------------------------------------------------------------
# Phase 0 / R1: incidence rate ratios need person-time
# --------------------------------------------------------------------------

class TestIncidenceRateRatio(unittest.TestCase):
    """An IRR needs person-time denominators, not participant totals."""

    def test_irr_without_person_time_is_refused(self):
        s = Study(id="s", events_treat=10, total_treat=100,
                  events_control=20, total_control=100)
        with self.assertRaises(DataError) as ctx:
            effect_size(s, "IRR")
        self.assertIn("person-time", str(ctx.exception))

    def test_irr_uses_person_time_not_participants(self):
        # 10 events / 500 py vs 20 events / 250 py -> IRR 0.25, log = -1.3863
        s = Study(id="s", events_treat=10, person_time_treat=500,
                  events_control=20, person_time_control=250)
        yi, vi = effect_size(s, "IRR")
        self.assertAlmostEqual(yi, -1.386294, places=5)
        self.assertAlmostEqual(vi, 1 / 10 + 1 / 20, places=9)

    def test_person_time_study_needs_no_participant_totals(self):
        s = Study(id="s", events_treat=10, person_time_treat=500,
                  events_control=20, person_time_control=250)
        self.assertTrue(s.has_person_time)
        self.assertFalse(s.has_table)

    def test_person_time_must_be_positive(self):
        with self.assertRaises(DataError):
            Study(id="s", events_treat=10, person_time_treat=0,
                  events_control=20, person_time_control=250)
        with self.assertRaises(DataError):
            Study(id="s", events_treat=10, person_time_treat=-5,
                  events_control=20, person_time_control=250)

    def test_person_time_does_not_make_a_risk_ratio_computable(self):
        """Rates carry no participant denominator, so RR is not derivable."""
        s = Study(id="s", events_treat=10, person_time_treat=500,
                  events_control=20, person_time_control=250)
        with self.assertRaises(DataError):
            effect_size(s, "RR")

    def test_irr_pools_from_person_time(self):
        studies = [
            Study(id="a", events_treat=10, person_time_treat=500,
                  events_control=20, person_time_control=250),
            Study(id="b", events_treat=12, person_time_treat=600,
                  events_control=22, person_time_control=280),
        ]
        result = pool(studies, "IRR", model="fixed")
        self.assertLess(result.estimate, 1.0)   # reported exponentiated
        self.assertEqual(result.k, 2)

    def test_irr_zero_in_one_arm_gets_the_continuity_correction(self):
        s = Study(id="s", events_treat=0, person_time_treat=500,
                  events_control=20, person_time_control=250)
        yi, vi = effect_size(s, "IRR")
        self.assertTrue(yi == yi and vi == vi)   # not NaN
        self.assertGreater(vi, 0)
        self.assertLess(yi, 0)

    def test_irr_from_precomputed_effect_still_works(self):
        s = Study(id="s", yi=-1.2, vi=0.05)
        self.assertEqual(effect_size(s, "IRR"), (-1.2, 0.05))

    def test_person_time_loads_from_json(self):
        payload = {
            "id": "rates", "measure": "IRR", "model": "fixed",
            "studies": [
                {"id": "a", "events_treat": 10, "person_time_treat": 500,
                 "events_control": 20, "person_time_control": 250},
                {"id": "b", "events_treat": 12, "person_time_treat": 600,
                 "events_control": 22, "person_time_control": 280},
            ],
        }
        tmp = Path(tempfile.mkdtemp()) / "rates.json"
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        ma = load(tmp)[0]
        self.assertAlmostEqual(pool_meta(ma).estimate_log, -1.3, delta=0.2)


# --------------------------------------------------------------------------
# Phase 0 / R1: double-zero studies
# --------------------------------------------------------------------------

class TestDoubleZeroStudies(unittest.TestCase):
    """A study with no events in either arm carries no information."""

    def _rows(self):
        return [
            Study(id="dz", events_treat=0, total_treat=50,
                  events_control=0, total_control=50),
            Study(id="a", events_treat=5, total_treat=50,
                  events_control=10, total_control=50),
            Study(id="b", events_treat=6, total_treat=50,
                  events_control=11, total_control=50),
        ]

    def test_effect_size_raises_double_zero_error(self):
        dz = self._rows()[0]
        for measure in ("RR", "OR", "RD"):
            with self.subTest(measure=measure):
                with self.assertRaises(DoubleZeroError):
                    effect_size(dz, measure)

    def test_double_zero_error_is_a_data_error(self):
        self.assertTrue(issubclass(DoubleZeroError, DataError))

    def test_double_zero_excluded_from_rr_by_default(self):
        result = pool(self._rows(), "RR", "fixed")
        self.assertEqual(result.k, 2)
        self.assertNotIn("dz", result.weights)

    def test_double_zero_excluded_from_or_by_default(self):
        result = pool(self._rows(), "OR", "fixed")
        self.assertEqual(result.k, 2)
        self.assertNotIn("dz", result.weights)

    def test_exclusion_is_recorded_on_the_result(self):
        result = pool(self._rows(), "RR", "fixed")
        self.assertIn("dz", result.excluded)
        self.assertIn("no events in either arm", result.excluded["dz"])

    def test_double_zero_included_when_requested(self):
        """include_double_zero=True is the path software-fingerprinting needs."""
        result = pool(self._rows(), "RR", "fixed", include_double_zero=True)
        self.assertEqual(result.k, 3)
        self.assertIn("dz", result.weights)
        self.assertEqual(result.excluded, {})

    def test_included_double_zero_reproduces_the_uncorrected_values(self):
        dz = self._rows()[0]
        yi, vi = effect_size(dz, "RR", include_double_zero=True)
        self.assertAlmostEqual(yi, 0.0, places=12)
        self.assertAlmostEqual(vi, 3.9607843137254903, places=9)

    def test_double_zero_kept_for_risk_difference_as_an_estimate(self):
        """RD is estimable at zero, so the point estimate exists...

        ...but its variance is exactly zero, so it cannot carry an
        inverse-variance weight. It is excluded from pooling with that
        reason recorded, rather than given an infinite weight.
        """
        dz = self._rows()[0]
        with self.assertRaises(DoubleZeroError) as ctx:
            effect_size(dz, "RD")
        self.assertIn("zero variance", str(ctx.exception))
        result = pool(self._rows(), "RD", "fixed")
        self.assertEqual(result.k, 2)
        self.assertIn("dz", result.excluded)

    def test_double_zero_cannot_be_included_for_risk_difference(self):
        with self.assertRaises(DataError):
            pool(self._rows(), "RD", "fixed", include_double_zero=True)

    def test_all_double_zero_leaves_nothing_to_pool(self):
        studies = [
            Study(id="x", events_treat=0, total_treat=40,
                  events_control=0, total_control=40),
            Study(id="y", events_treat=0, total_treat=30,
                  events_control=0, total_control=30),
        ]
        with self.assertRaises(DataError) as ctx:
            pool(studies, "RR", "fixed")
        self.assertIn("no events in either arm", str(ctx.exception))

    def test_single_zero_arm_is_still_pooled_with_correction(self):
        """Only DOUBLE zeros are excluded; a single zero arm is corrected."""
        studies = [
            Study(id="one-zero", events_treat=0, total_treat=50,
                  events_control=5, total_control=50),
            Study(id="a", events_treat=5, total_treat=50,
                  events_control=10, total_control=50),
        ]
        result = pool(studies, "RR", "fixed")
        self.assertEqual(result.k, 2)
        self.assertEqual(result.excluded, {})

    def test_exclusions_surface_in_impact_notes(self):
        rows = self._rows()
        rows[1].retracted = True
        ma = MetaAnalysis(id="m", measure="RR", studies=rows, model="fixed")
        impact = analyse(ma)
        self.assertTrue(any("dz" in note for note in impact.notes))

    def test_exclusions_surface_in_json_output(self):
        payload = {
            "id": "dzjson", "measure": "RR", "model": "fixed",
            "reported_estimate": 0.5,
            "studies": [
                {"id": "dz", "events_treat": 0, "total_treat": 50,
                 "events_control": 0, "total_control": 50},
                {"id": "a", "events_treat": 5, "total_treat": 50,
                 "events_control": 10, "total_control": 50, "retracted": True},
                {"id": "b", "events_treat": 6, "total_treat": 50,
                 "events_control": 11, "total_control": 50},
            ],
        }
        tmp = Path(tempfile.mkdtemp()) / "dz.json"
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        _, out, _ = run_cli("check", str(tmp), "--json")
        result = json.loads(out)["results"][0]
        self.assertIn("dz", result["original"]["excluded"])


if __name__ == "__main__":
    unittest.main()
