"""Properties of the in-kind recomputation in scripts/inkind_inputs.py.

The paper rebuilds BLS's imputed terms from the component shares BLS
publishes. These tests state what that rebuild must satisfy for every band,
not only the committed ones, and compare it with a direct evaluation of the
threshold identity. A seeded generator draws the bands, which keeps CI
deterministic without a property-testing dependency.
"""

import importlib.util
import json
import math
import random
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DRAWS = 2000


def load_inkind_module():
    spec = importlib.util.spec_from_file_location(
        "paper_inkind_inputs", REPO / "scripts/inkind_inputs.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(REPO / "scripts"))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


INKIND = load_inkind_module()
TENURES = INKIND.TENURES
# The classification the paper states ("We add every benefit to FCSUti and
# add LIHEAP and rental assistance to shelter and utilities as well"),
# declared here rather than read from the module, so that a
# misclassified benefit cannot pass the properties below.
SHARED = ("nslp", "wic", "broadband")
SHELTER_UTILITY = ("liheap", "rental_assistance")
ALL_IMPUTED = SHARED + SHELTER_UTILITY


def random_band(rng):
    """A band with a tenure mix on the simplex and nonnegative means."""
    weights = [rng.random() + 1e-6 for _ in TENURES]
    mix = {tenure: weight / sum(weights) for tenure, weight in zip(TENURES, weights)}
    return {
        "tenure_mix": mix,
        "pooled": {name: rng.uniform(0, 1500) for name in SHARED},
        "by_tenure": {
            tenure: {name: rng.uniform(0, 3000) for name in SHELTER_UTILITY}
            for tenure in TENURES
        },
    }


def thresholds(band, shared_out_of_pocket, su_out_of_pocket, components):
    """BLS's identity evaluated directly: T_h = 0.82 (C + SU_h + 0.2 F), with
    F = C + sum_h P_h SU_h, after adding the named imputed means to C and SU_h."""
    shared = shared_out_of_pocket + sum(
        band["pooled"][name] for name in SHARED if name in components
    )
    su = {
        tenure: su_out_of_pocket[tenure]
        + sum(
            band["by_tenure"][tenure][name]
            for name in SHELTER_UTILITY
            if name in components
        )
        for tenure in TENURES
    }
    fcsu = shared + sum(band["tenure_mix"][tenure] * su[tenure] for tenure in TENURES)
    return {tenure: 0.82 * (shared + su[tenure] + 0.2 * fcsu) for tenure in TENURES}


class ImputedTermProperties(unittest.TestCase):
    def assertClose(self, actual, expected, label=""):
        self.assertTrue(
            math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-9),
            f"{label}: {actual!r} != {expected!r}",
        )

    def test_terms_equal_the_threshold_change_from_adding_the_benefits(self):
        """Differential: the rebuild matches a direct evaluation of the
        identity, whatever the out-of-pocket means."""
        rng = random.Random(20261106)
        for _ in range(DRAWS):
            band = random_band(rng)
            shared_oop = rng.uniform(5000, 20000)
            su_oop = {tenure: rng.uniform(5000, 25000) for tenure in TENURES}
            subset = tuple(name for name in ALL_IMPUTED if rng.random() < 0.6)
            terms = INKIND._imputed_terms(band, subset)
            with_benefits = thresholds(band, shared_oop, su_oop, subset)
            without = thresholds(band, shared_oop, su_oop, ())
            for tenure in TENURES:
                self.assertClose(
                    terms[tenure], with_benefits[tenure] - without[tenure], tenure
                )

    def test_terms_add_over_disjoint_components(self):
        rng = random.Random(1)
        for _ in range(DRAWS):
            band = random_band(rng)
            first = tuple(name for name in ALL_IMPUTED if rng.random() < 0.5)
            second = tuple(name for name in ALL_IMPUTED if name not in first)
            together = INKIND._imputed_terms(band, ALL_IMPUTED)
            apart = (
                INKIND._imputed_terms(band, first),
                INKIND._imputed_terms(band, second),
            )
            for tenure in TENURES:
                self.assertClose(together[tenure], apart[0][tenure] + apart[1][tenure])

    def test_no_components_add_nothing(self):
        rng = random.Random(2)
        for _ in range(DRAWS):
            terms = INKIND._imputed_terms(random_band(rng), ())
            self.assertEqual(set(terms), set(TENURES))
            self.assertTrue(all(value == 0 for value in terms.values()))

    def test_module_classifies_the_benefits_as_the_paper_states(self):
        self.assertEqual(set(INKIND.SHARED_IMPUTED), set(SHARED))
        self.assertEqual(set(INKIND.SHELTER_UTILITY_IMPUTED), set(SHELTER_UTILITY))

    def test_broadband_alone_adds_the_same_dollars_to_every_tenure(self):
        rng = random.Random(8)
        for _ in range(DRAWS):
            band = random_band(rng)
            terms = INKIND._imputed_terms(band, ("broadband",))
            expected = 0.82 * 1.2 * band["pooled"]["broadband"]
            for tenure in TENURES:
                self.assertClose(terms[tenure], expected, tenure)

    def test_shared_benefits_add_the_same_dollars_to_every_tenure(self):
        rng = random.Random(3)
        for _ in range(DRAWS):
            band = random_band(rng)
            terms = INKIND._imputed_terms(band, SHARED)
            expected = 0.82 * 1.2 * sum(band["pooled"].values())
            for tenure in TENURES:
                self.assertClose(terms[tenure], expected, tenure)

    def test_mix_weighted_terms_scale_the_pooled_benefits(self):
        """With tenure shares summing to one, the mix-weighted mean term is
        0.82 x 1.2 times the band's pooled imputed benefits."""
        rng = random.Random(4)
        for _ in range(DRAWS):
            band = random_band(rng)
            mix = band["tenure_mix"]
            terms = INKIND._imputed_terms(band, ALL_IMPUTED)
            pooled = sum(band["pooled"].values()) + sum(
                mix[tenure] * sum(band["by_tenure"][tenure].values())
                for tenure in TENURES
            )
            self.assertClose(
                sum(mix[tenure] * terms[tenure] for tenure in TENURES),
                0.82 * 1.2 * pooled,
            )

    def test_a_tenures_own_rental_assistance_moves_its_threshold_most(self):
        """Raising one tenure's rental assistance by a dollar adds
        0.82 (1 + 0.2 P_h) to its term and 0.82 x 0.2 P_h to each other's."""
        rng = random.Random(5)
        for _ in range(DRAWS):
            band = random_band(rng)
            tenure = rng.choice(TENURES)
            before = INKIND._imputed_terms(band, ALL_IMPUTED)
            band["by_tenure"][tenure]["rental_assistance"] += 1
            after = INKIND._imputed_terms(band, ALL_IMPUTED)
            share = band["tenure_mix"][tenure]
            for other in TENURES:
                expected = 0.82 * ((other == tenure) + 0.2 * share)
                self.assertClose(after[other] - before[other], expected, other)
            self.assertTrue(
                all(
                    after[tenure] - before[tenure] > after[other] - before[other]
                    for other in TENURES
                    if other != tenure
                )
            )

    def test_nonnegative_benefits_never_lower_a_threshold(self):
        rng = random.Random(6)
        for _ in range(DRAWS):
            terms = INKIND._imputed_terms(random_band(rng), ALL_IMPUTED)
            self.assertTrue(all(value >= 0 for value in terms.values()))


class GrowthAndToleranceProperties(unittest.TestCase):
    def test_growth_round_trips(self):
        rng = random.Random(7)
        for _ in range(DRAWS):
            start = rng.uniform(1000, 60000)
            rate = rng.uniform(-50, 100)
            self.assertTrue(
                math.isclose(
                    INKIND._growth(start, start * (1 + rate / 100)),
                    rate,
                    rel_tol=1e-9,
                    abs_tol=1e-9,
                )
            )

    def test_close_rejects_values_that_are_not_finite(self):
        """math.isclose(inf, inf) is true, so _close must check finiteness
        itself; a receipt with an infinite or missing value fails."""
        for actual, expected in (
            (math.inf, math.inf),
            (-math.inf, -math.inf),
            (math.nan, math.nan),
            (math.nan, 1.0),
        ):
            with self.subTest(actual=actual, expected=expected):
                with self.assertRaises(ValueError):
                    INKIND._close(actual, expected, "non-finite")

    def test_close_accepts_rounding_and_rejects_a_cent(self):
        INKIND._close(35000.0, 35000.0 * (1 + 5e-10), "dollars within 1e-9")
        INKIND._close(4.85, 4.85 + 5e-7, "points within 1e-6")
        with self.assertRaises(ValueError):
            INKIND._close(35000.0, 35000.01, "a cent")


def random_implicates(rng, implicates=None):
    """Implicates of [full sample, 44 replicates] around a common level."""
    count = implicates or rng.randint(2, 8)
    level = rng.uniform(-50, 50000)
    spread = 10 ** rng.uniform(-3, 3)
    return [
        [value := level + rng.gauss(0, spread)]
        + [value + rng.gauss(0, spread * rng.uniform(0.1, 3)) for _ in range(INKIND.REPLICATES)]
        for _ in range(count)
    ]


def direct_rubin(series):
    """Rubin's rules written out from the definitions, as a differential
    reference for inkind_inputs._rubin."""
    m, r = len(series), INKIND.REPLICATES
    thetas = [values[0] for values in series]
    theta_bar = sum(thetas) / m
    within = sum(sum((x - values[0]) ** 2 for x in values[1:]) / r for values in series) / m
    between = sum((t - theta_bar) ** 2 for t in thetas) / (m - 1)
    total = within + (1 + 1 / m) * between
    lam = (1 + 1 / m) * between / total
    nu_com = INKIND.COMPLETE_DATA_DF
    nu_obs = nu_com * (nu_com + 1) * (1 - lam) / (nu_com + 3)
    nu_m = (m - 1) / lam**2 if lam > 0 else math.inf
    return theta_bar, within, between, total, lam, 1 / (1 / nu_m + 1 / nu_obs)


class ReplicateVarianceProperties(unittest.TestCase):
    """Standard BRR and Rubin's rules, as the paper recomputes the receipt's
    standard errors from its stored replicate thresholds."""

    def setUp(self):
        self.rng = random.Random(20261107)

    def test_replicate_variance_is_a_nonnegative_mean_square(self):
        for _ in range(DRAWS):
            full = self.rng.uniform(-1000, 1000)
            replicates = [full + self.rng.gauss(0, 10) for _ in range(INKIND.REPLICATES)]
            value = INKIND._replicate_variance(full, replicates)
            self.assertGreaterEqual(value, 0)
            shift = self.rng.uniform(-1e4, 1e4)
            self.assertTrue(
                math.isclose(
                    INKIND._replicate_variance(full + shift, [x + shift for x in replicates]),
                    value,
                    rel_tol=1e-6,
                    abs_tol=1e-9,
                )
            )
            shuffled = replicates[:]
            self.rng.shuffle(shuffled)
            self.assertTrue(math.isclose(INKIND._replicate_variance(full, shuffled), value, rel_tol=1e-12))
        self.assertEqual(INKIND._replicate_variance(5.0, [5.0] * INKIND.REPLICATES), 0.0)

    def test_replicate_variance_requires_every_replicate(self):
        with self.assertRaises(ValueError):
            INKIND._replicate_variance(1.0, [1.0] * (INKIND.REPLICATES - 1))

    def test_rubin_matches_the_definitions(self):
        for _ in range(DRAWS):
            series = random_implicates(self.rng)
            combined = INKIND._rubin(series)
            theta_bar, within, between, total, lam, df = direct_rubin(series)
            for key, expected in (
                ("estimate", theta_bar),
                ("within_variance", within),
                ("between_variance", between),
                ("total_variance", total),
                ("fraction_missing_information", lam),
                ("df", df),
            ):
                self.assertTrue(
                    math.isclose(combined[key], expected, rel_tol=1e-9, abs_tol=1e-12),
                    f"{key}: {combined[key]!r} != {expected!r}",
                )

    def test_rubin_bounds(self):
        for _ in range(DRAWS):
            series = random_implicates(self.rng)
            m = len(series)
            combined = INKIND._rubin(series)
            total = combined["total_variance"]
            self.assertGreaterEqual(total, combined["within_variance"] * (1 - 1e-12))
            self.assertGreaterEqual(total, (1 + 1 / m) * combined["between_variance"] * (1 - 1e-12))
            self.assertTrue(0 <= combined["fraction_missing_information"] <= 1)
            self.assertTrue(0 <= combined["df"] <= INKIND.COMPLETE_DATA_DF)
            self.assertTrue(math.isclose(combined["standard_error"] ** 2, total, rel_tol=1e-12))

    def test_identical_implicates_leave_only_sampling_variance(self):
        for _ in range(200):
            first = random_implicates(self.rng, implicates=1)[0]
            combined = INKIND._rubin([first[:] for _ in range(5)])
            self.assertEqual(combined["between_variance"], 0)
            self.assertEqual(combined["fraction_missing_information"], 0)
            nu = INKIND.COMPLETE_DATA_DF
            self.assertTrue(math.isclose(combined["df"], nu * (nu + 1) / (nu + 3), rel_tol=1e-12))


class UncertaintyReceiptTests(unittest.TestCase):
    """The committed receipt, recomputed in memory."""

    @classmethod
    def setUpClass(cls):
        cls.inputs = INKIND.load_inkind(REPO / "data/inkind", REPO / "data/current")
        cls.published = INKIND.published_standard_errors(REPO / "data")

    def fresh_inputs(self):
        return {**self.inputs, "uncertainty": json.loads(json.dumps(self.inputs["uncertainty"]))}

    def test_committed_receipt_recomputes(self):
        figures = INKIND.uncertainty_figures(self.inputs, self.published)
        for run in INKIND.UNCERTAINTY_RUNS:
            for tenure in TENURES:
                stage = figures["runs"][run]["stage_change"][tenure]
                self.assertGreater(stage["standard_error"], 0)
                self.assertTrue(0 < stage["implicate_variance_share"] < 1)

    def test_one_moved_replicate_fails(self):
        inputs = self.fresh_inputs()
        years = inputs["uncertainty"]["runs"]["fcsuti"]["years"]
        years["2022"]["replicates"]["with_in_kind"]["owner_with_mortgage"][3][11] += 25
        with self.assertRaisesRegex(ValueError, "fcsuti 2022 owner_with_mortgage"):
            INKIND.uncertainty_figures(inputs, self.published)

    def test_growth_replicates_pair_the_same_replicate_weight(self):
        """Pairing replicate r of 2022 with replicate r + 1 of 2025 changes
        the growth standard error, so the recorded value pins the pairing."""
        inputs = self.fresh_inputs()
        years = inputs["uncertainty"]["runs"]["package"]["years"]
        for draws in years["2025"]["replicates"]["with_in_kind"]["renter"]:
            draws[1:] = draws[2:] + draws[1:2]
        unshifted = years["2025"]["replicates"]["without_in_kind"]["renter"]
        unshifted[1:] = unshifted[2:] + unshifted[1:2]
        # Rotating a window's replicates keeps its own variance, so only the
        # growth pairing changes.
        with self.assertRaisesRegex(ValueError, "stage change package 2022-2025 renter"):
            INKIND.uncertainty_figures(inputs, self.published)


if __name__ == "__main__":
    unittest.main()
