"""Properties of the in-kind recomputation in scripts/inkind_inputs.py.

The paper rebuilds BLS's imputed terms from the component shares BLS
publishes. These tests state what that rebuild must satisfy for every band,
not only the committed ones, and compare it with a direct evaluation of the
threshold identity. A seeded generator draws the bands, which keeps CI
deterministic without a property-testing dependency.
"""

import importlib.util
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
SHARED = INKIND.SHARED_IMPUTED
SHELTER_UTILITY = INKIND.SHELTER_UTILITY_IMPUTED
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


if __name__ == "__main__":
    unittest.main()
