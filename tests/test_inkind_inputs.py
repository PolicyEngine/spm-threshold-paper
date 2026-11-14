"""Properties of the in-kind recomputation in scripts/inkind_inputs.py.

The paper rebuilds BLS's imputed terms from the component shares BLS
publishes. These tests state what that rebuild must satisfy for every band,
not only the committed ones, and compare it with a direct evaluation of the
threshold identity. A seeded generator draws the bands, which keeps CI
deterministic without a property-testing dependency.
"""

import hashlib
import importlib.util
import json
import math
import random
import shutil
import sys
import tempfile
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

    def test_reflecting_replicates_around_the_full_sample_keeps_every_variance(self):
        """Replicates mirrored around the full-sample estimate keep every
        squared deviation, so no variance check can tell them from the
        originals. The receipt pins exist for this case."""
        for _ in range(DRAWS):
            series = random_implicates(self.rng)
            mirrored = [[values[0]] + [2 * values[0] - x for x in values[1:]] for values in series]
            self.assertNotEqual(mirrored, series)
            for values, mirror in zip(series, mirrored):
                self.assertTrue(
                    math.isclose(
                        INKIND._replicate_variance(mirror[0], mirror[1:]),
                        INKIND._replicate_variance(values[0], values[1:]),
                        rel_tol=1e-9,
                        abs_tol=1e-12,
                    )
                )
            original, reflected = INKIND._rubin(series), INKIND._rubin(mirrored)
            for key in ("estimate", "within_variance", "between_variance", "total_variance", "df"):
                self.assertTrue(math.isclose(reflected[key], original[key], rel_tol=1e-9, abs_tol=1e-12), key)

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

    def test_committed_receipts_match_their_pins(self):
        INKIND.check_receipt_pins(REPO / "data/inkind")
        self.assertEqual(set(INKIND.RECEIPT_PINS), set(INKIND.INKIND_FILES) - {INKIND.PROVENANCE})

    def test_reflected_receipt_passes_every_consistency_check_but_not_the_pins(self):
        """Mirror the 2019 replicates, reseal the receipt with every hash that
        records it, and only check_receipt_pins rejects the copy."""
        with tempfile.TemporaryDirectory(prefix="inkind-pins-") as temp:
            data = Path(temp)
            for name in (*INKIND.INKIND_FILES, "SHA256SUMS"):
                shutil.copyfile(REPO / "data/inkind" / name, data / name)
            uncertainty = json.loads((data / INKIND.UNCERTAINTY).read_text())
            for run in uncertainty["runs"].values():
                replicates = run["years"]["2019"]["replicates"]
                series = list(replicates["without_in_kind"].values())
                series += [draw for draws in replicates["with_in_kind"].values() for draw in draws]
                for values in series:
                    values[1:] = [2 * values[0] - value for value in values[1:]]
                # The lift is a ratio of thresholds, so reflection moves its
                # variance; reseal the recorded lift as a forger would.
                for tenure, without in replicates["without_in_kind"].items():
                    lifts = [
                        [INKIND._growth(w, v) for w, v in zip(without, draw)]
                        for draw in replicates["with_in_kind"][tenure]
                    ]
                    run["years"]["2019"]["in_kind_lift_percent"][tenure].update(INKIND._rubin(lifts))
            (data / INKIND.UNCERTAINTY).write_text(json.dumps(uncertainty))
            digest = hashlib.sha256((data / INKIND.UNCERTAINTY).read_bytes()).hexdigest()
            provenance = json.loads((data / INKIND.PROVENANCE).read_text())
            provenance["artifacts"][f"data/inkind/{INKIND.UNCERTAINTY}"]["sha256"] = digest
            (data / INKIND.PROVENANCE).write_text(json.dumps(provenance))
            (data / "SHA256SUMS").write_text(
                "".join(
                    f"{hashlib.sha256((data / name).read_bytes()).hexdigest()}  data/inkind/{name}\n"
                    for name in INKIND.INKIND_FILES
                )
            )
            inputs = INKIND.load_inkind(data, REPO / "data/current")
            INKIND.uncertainty_figures(inputs, self.published)
            with self.assertRaisesRegex(ValueError, f"{INKIND.UNCERTAINTY} matches the SHA-256 pinned"):
                INKIND.check_receipt_pins(data)

    def test_reflected_replicates_without_a_resealed_lift_fail(self):
        inputs = self.fresh_inputs()
        replicates = inputs["uncertainty"]["runs"]["package"]["years"]["2019"]["replicates"]
        series = list(replicates["without_in_kind"].values())
        series += [draw for draws in replicates["with_in_kind"].values() for draw in draws]
        for values in series:
            values[1:] = [2 * values[0] - value for value in values[1:]]
        with self.assertRaisesRegex(ValueError, "lift package 2019"):
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


class GrowthAccountingProperties(unittest.TestCase):
    """The split of BLS's 2022-2025 growth beyond CPI-U into the FCSUti
    index's part, the imputed benefits' part and out-of-pocket spending's
    part, checked on random thresholds and on the committed receipts."""

    @staticmethod
    def synthetic(rng, cpi=None, price=None):
        cpi = rng.uniform(1.0, 1.2) if cpi is None else cpi
        price = cpi + rng.uniform(0.001, 0.1) if price is None else price
        b22, b25, i22, i25 = {}, {}, {}, {}
        for tenure in TENURES:
            b22[tenure] = rng.uniform(20_000, 50_000)
            i22[tenure] = rng.uniform(0, 0.1 * b22[tenure])
            i25[tenure] = cpi * i22[tenure] + rng.uniform(1, 800)
            b25[tenure] = price * (b22[tenure] - i22[tenure]) + rng.uniform(1, 6000) + i25[tenure]
        components = {
            "bls": {
                "years": {"2022": {"published_thresholds": b22}, "2025": {"published_thresholds": b25}},
                "growth_2022_2025": {
                    "by_tenure": {
                        t: {"imputed_term_dollars": {"2022": i22[t], "2025": i25[t]}} for t in TENURES
                    }
                },
            }
        }
        figures = {
            "bls": {
                t: {"imputed_share_beyond_cpi_u": 100 * (i25[t] - cpi * i22[t]) / (b25[t] - cpi * b22[t])}
                for t in TENURES
            }
        }
        return figures, components, cpi, price

    def test_parts_sum_to_growth_beyond_cpi(self):
        rng = random.Random(20261111)
        for _ in range(DRAWS):
            figures, components, cpi, price = self.synthetic(rng)
            split = INKIND._growth_accounting(figures, components, cpi, price)
            for tenure in TENURES:
                part = split[tenure]
                b22 = components["bls"]["years"]["2022"]["published_thresholds"][tenure]
                b25 = components["bls"]["years"]["2025"]["published_thresholds"][tenure]
                self.assertTrue(math.isclose(part["excess"], 100 * (b25 / b22 - cpi), rel_tol=1e-9))
                self.assertTrue(
                    math.isclose(
                        part["prices"] + part["benefits"] + part["out_of_pocket"], part["excess"], rel_tol=1e-9
                    )
                )
                self.assertTrue(math.isclose(sum(part["shares"].values()), 100, rel_tol=1e-9))
                self.assertTrue(all(value > 0 for value in part["shares"].values()))

    def test_index_on_the_benefits_moves_only_the_index_lead_on_their_terms(self):
        """Applying the index's lead to the benefits' terms too keeps the
        sum and the out-of-pocket part, and moves exactly
        (phi - pi) I22 / B22 from the benefits' part to the prices' part."""
        rng = random.Random(20261112)
        for _ in range(DRAWS):
            figures, components, cpi, price = self.synthetic(rng)
            split = INKIND._growth_accounting(figures, components, cpi, price)
            for tenure in TENURES:
                part = split[tenure]
                alt = part["index_on_benefits_shares"]
                b22 = components["bls"]["years"]["2022"]["published_thresholds"][tenure]
                i22 = components["bls"]["growth_2022_2025"]["by_tenure"][tenure]["imputed_term_dollars"]["2022"]
                moved = 100 * 100 * (price - cpi) * i22 / b22 / part["excess"]
                self.assertTrue(math.isclose(sum(alt.values()), 100, rel_tol=1e-9))
                self.assertTrue(
                    math.isclose(alt["out_of_pocket"], part["shares"]["out_of_pocket"], rel_tol=1e-9, abs_tol=1e-9)
                )
                self.assertTrue(math.isclose(part["shares"]["benefits"] - alt["benefits"], moved, abs_tol=1e-9))
                self.assertTrue(math.isclose(alt["prices"] - part["shares"]["prices"], moved, abs_tol=1e-9))
                self.assertTrue(
                    math.isclose(alt["prices"], 100 * 100 * (price - cpi) / part["excess"], rel_tol=1e-9)
                )

    def test_split_does_not_depend_on_the_dollar_unit(self):
        rng = random.Random(7)
        for _ in range(200):
            figures, components, cpi, price = self.synthetic(rng)
            scale = rng.uniform(0.01, 100)
            scaled = json.loads(json.dumps(components))
            for year in ("2022", "2025"):
                for tenure in TENURES:
                    scaled["bls"]["years"][year]["published_thresholds"][tenure] *= scale
                    scaled["bls"]["growth_2022_2025"]["by_tenure"][tenure]["imputed_term_dollars"][year] *= scale
            base = INKIND._growth_accounting(figures, components, cpi, price)
            other = INKIND._growth_accounting(figures, scaled, cpi, price)
            for tenure in TENURES:
                for name in ("excess", "prices", "benefits", "out_of_pocket"):
                    self.assertTrue(math.isclose(base[tenure][name], other[tenure][name], rel_tol=1e-9))

    def test_a_misstated_share_is_rejected(self):
        figures, components, cpi, price = self.synthetic(random.Random(3))
        figures["bls"]["renter"]["imputed_share_beyond_cpi_u"] += 0.01
        with self.assertRaisesRegex(ValueError, "accounting's benefit share renter"):
            INKIND._growth_accounting(figures, components, cpi, price)

    def test_a_part_below_zero_is_rejected(self):
        figures, components, cpi, price = self.synthetic(random.Random(4))
        terms = components["bls"]["growth_2022_2025"]["by_tenure"]["renter"]["imputed_term_dollars"]
        terms["2025"] = 0.5 * cpi * terms["2022"]
        b22 = components["bls"]["years"]["2022"]["published_thresholds"]["renter"]
        b25 = components["bls"]["years"]["2025"]["published_thresholds"]["renter"]
        figures["bls"]["renter"]["imputed_share_beyond_cpi_u"] = (
            100 * (terms["2025"] - cpi * terms["2022"]) / (b25 - cpi * b22)
        )
        with self.assertRaisesRegex(ValueError, "accounting parts positive renter"):
            INKIND._growth_accounting(figures, components, cpi, price)

    def test_committed_split_matches_the_receipts_directly(self):
        """A second reading of the receipts, with no code shared with the
        module beyond loading them, gives the same parts."""
        inputs = INKIND.load_inkind(REPO / "data/inkind", REPO / "data/current")
        figures = INKIND.inkind_figures(inputs)
        components = inputs["components"]
        cpi = components["inputs"]["cpi"]["cpi_u_ratio_2022_2025"]
        price = inputs["replication"]["decompositions"]["2022-2025"]["bls_price_factor"]
        for tenure in TENURES:
            b22 = components["bls"]["years"]["2022"]["published_thresholds"][tenure]
            b25 = components["bls"]["years"]["2025"]["published_thresholds"][tenure]
            terms = components["bls"]["growth_2022_2025"]["by_tenure"][tenure]["imputed_term_dollars"]
            out_of_pocket_growth = (b25 - terms["2025"]) / (b22 - terms["2022"])
            part = figures["accounting"][tenure]
            self.assertTrue(
                math.isclose(part["out_of_pocket"], 100 * (out_of_pocket_growth - price) * (1 - terms["2022"] / b22))
            )
            self.assertTrue(math.isclose(part["prices"] / (1 - terms["2022"] / b22), 100 * (price - cpi)))
            self.assertTrue(
                math.isclose(part["shares"]["benefits"], figures["bls"][tenure]["imputed_share_beyond_cpi_u"])
            )


class OtherSeparateAccountingProperties(unittest.TestCase):
    """The split with BLS's Other share kept separate: the benefits' part
    counts their five share rows, s times school lunch and WIC at equal
    dollars and s times each tenure's LIHEAP, rental assistance and
    broadband subsidy, and the Other share joins the rest."""

    CPI, PRICE = 1.10, 1.14

    def synthetic(self, rng):
        """Bands for 2022 and 2025 with the tenure-specific benefits pooled
        under the tenure mix, as BLS's workbook gives them, and thresholds
        from BLS's identity. Out-of-pocket spending grows 25 percent and
        each benefit 15 to 60 percent, so every part of either split is
        positive."""
        weights = [rng.random() + 1e-6 for _ in TENURES]
        mix = {tenure: weight / sum(weights) for tenure, weight in zip(TENURES, weights)}
        shared_oop = rng.uniform(5000, 20000)
        su_oop = {tenure: rng.uniform(5000, 25000) for tenure in TENURES}
        by_tenure = {
            tenure: {name: rng.uniform(0, 3000) for name in ("liheap", "rental_assistance")} | {
                "broadband": rng.uniform(0, 30)
            }
            for tenure in TENURES
        }
        shared = {name: rng.uniform(0, 1500) for name in ("nslp", "wic")}
        years, terms = {}, {tenure: {} for tenure in TENURES}
        for year, oop_growth in (("2022", 1.0), ("2025", 1.25)):
            growth = {name: 1.0 if year == "2022" else rng.uniform(1.15, 1.6) for name in ALL_IMPUTED}
            tenure_means = {
                tenure: {name: value * growth[name] for name, value in means.items()}
                for tenure, means in by_tenure.items()
            }
            pooled = {name: value * growth[name] for name, value in shared.items()}
            for name in ("liheap", "rental_assistance", "broadband"):
                pooled[name] = sum(mix[tenure] * tenure_means[tenure][name] for tenure in TENURES)
            band = {"tenure_mix": mix, "pooled": pooled, "by_tenure": tenure_means}
            published = thresholds(
                band, oop_growth * shared_oop, {t: oop_growth * v for t, v in su_oop.items()}, ALL_IMPUTED
            )
            for tenure, value in INKIND._imputed_terms(band, ALL_IMPUTED).items():
                terms[tenure][year] = value
            years[year] = {
                "band": band,
                "published_thresholds": published,
                "imputed_total": sum(pooled[name] for name in ALL_IMPUTED),
            }
        return {
            "bls": {
                "years": years,
                "growth_2022_2025": {
                    "by_tenure": {tenure: {"imputed_term_dollars": terms[tenure]} for tenure in TENURES}
                },
            }
        }

    def test_parts_sum_to_the_same_growth_beyond_cpi(self):
        rng = random.Random(20261113)
        for _ in range(DRAWS // 4):
            components = self.synthetic(rng)
            separate = INKIND._growth_accounting_other_separate(components, self.CPI, self.PRICE)
            for tenure in TENURES:
                part = separate[tenure]
                years = components["bls"]["years"]
                b22 = years["2022"]["published_thresholds"][tenure]
                b25 = years["2025"]["published_thresholds"][tenure]
                self.assertTrue(math.isclose(part["excess"], 100 * (b25 / b22 - self.CPI), rel_tol=1e-9))
                self.assertTrue(
                    math.isclose(part["prices"] + part["benefits"] + part["out_of_pocket"], part["excess"], rel_tol=1e-9)
                )
                self.assertTrue(math.isclose(sum(part["shares"].values()), 100, rel_tol=1e-9))

    def test_rows_equal_the_identity_without_the_other_row(self):
        """Differential: a tenure's benefit rows are the threshold change from
        adding the benefits, less their 0.2 share of FCSUti, with that
        tenure's broadband subsidy in place of the band's."""
        rng = random.Random(20261114)
        for _ in range(DRAWS // 4):
            components = self.synthetic(rng)
            for year in ("2022", "2025"):
                band = components["bls"]["years"][year]["band"]
                rows = INKIND._benefit_rows(band)
                shared_oop, su_oop = 10_000.0, {tenure: 12_000.0 for tenure in TENURES}
                change = {
                    tenure: thresholds(band, shared_oop, su_oop, ALL_IMPUTED)[tenure]
                    - thresholds(band, shared_oop, su_oop, ())[tenure]
                    for tenure in TENURES
                }
                total = components["bls"]["years"][year]["imputed_total"]
                for tenure in TENURES:
                    expected = change[tenure] - 0.82 * (
                        0.2 * total + band["pooled"]["broadband"] - band["by_tenure"][tenure]["broadband"]
                    )
                    self.assertTrue(math.isclose(rows[tenure], expected, rel_tol=1e-9, abs_tol=1e-9), tenure)

    def test_rows_fall_short_of_the_terms(self):
        """Keeping the Other share separate lowers each tenure's benefits'
        part, since the rows leave out their 0.2 share of FCSUti."""
        rng = random.Random(20261115)
        for _ in range(DRAWS // 4):
            components = self.synthetic(rng)
            figures = {
                "bls": {
                    tenure: {
                        "imputed_share_beyond_cpi_u": INKIND._three_parts(
                            components["bls"]["years"]["2022"]["published_thresholds"][tenure],
                            components["bls"]["years"]["2025"]["published_thresholds"][tenure],
                            components["bls"]["growth_2022_2025"]["by_tenure"][tenure]["imputed_term_dollars"]["2022"],
                            components["bls"]["growth_2022_2025"]["by_tenure"][tenure]["imputed_term_dollars"]["2025"],
                            self.CPI,
                            self.PRICE,
                            tenure,
                        )["shares"]["benefits"]
                    }
                    for tenure in TENURES
                }
            }
            spread = INKIND._growth_accounting(figures, components, self.CPI, self.PRICE)
            separate = INKIND._growth_accounting_other_separate(components, self.CPI, self.PRICE)
            for tenure in TENURES:
                self.assertLess(separate[tenure]["benefits"], spread[tenure]["benefits"])
                self.assertGreater(separate[tenure]["prices"], spread[tenure]["prices"])

    def test_a_changed_tenure_row_is_rejected(self):
        components = self.synthetic(random.Random(5))
        components["bls"]["years"]["2025"]["band"]["by_tenure"]["renter"]["broadband"] += 1
        with self.assertRaisesRegex(ValueError, "band mean of broadband pools the tenures' means 2025"):
            INKIND._growth_accounting_other_separate(components, self.CPI, self.PRICE)

    def test_a_changed_shared_row_is_rejected(self):
        components = self.synthetic(random.Random(6))
        components["bls"]["years"]["2022"]["band"]["pooled"]["nslp"] += 1
        with self.assertRaisesRegex(ValueError, "benefit rows fall short of the benefits' terms by their Other share 2022"):
            INKIND._growth_accounting_other_separate(components, self.CPI, self.PRICE)

    def test_committed_split_matches_the_receipt_directly(self):
        """A second reading of the component receipt, with no code shared
        with the module beyond loading it."""
        inputs = INKIND.load_inkind(REPO / "data/inkind", REPO / "data/current")
        figures = INKIND.inkind_figures(inputs)
        components = inputs["components"]
        cpi = components["inputs"]["cpi"]["cpi_u_ratio_2022_2025"]
        price = inputs["replication"]["decompositions"]["2022-2025"]["bls_price_factor"]
        years = components["bls"]["years"]
        for tenure in TENURES:
            rows = {}
            for year in ("2022", "2025"):
                band = years[year]["band"]
                rows[year] = 0.82 * (
                    band["pooled"]["nslp"]
                    + band["pooled"]["wic"]
                    + band["by_tenure"][tenure]["broadband"]
                    + band["by_tenure"][tenure]["liheap"]
                    + band["by_tenure"][tenure]["rental_assistance"]
                )
            b22 = years["2022"]["published_thresholds"][tenure]
            b25 = years["2025"]["published_thresholds"][tenure]
            part = figures["accounting_other_separate"][tenure]
            excess = b25 / b22 - cpi
            self.assertTrue(math.isclose(part["shares"]["benefits"], 100 * (rows["2025"] / b22 - cpi * rows["2022"] / b22) / excess))
            self.assertTrue(math.isclose(part["prices"], 100 * (price - cpi) * (1 - rows["2022"] / b22)))
            self.assertTrue(
                math.isclose(
                    part["index_on_benefits_shares"]["benefits"],
                    100 * (rows["2025"] / b22 - price * rows["2022"] / b22) / excess,
                )
            )

    def test_internet_row_is_its_term_without_the_other_share(self):
        inputs = INKIND.load_inkind(REPO / "data/inkind", REPO / "data/current")
        levels = INKIND._internet_and_levels(inputs["components"])
        term, row = levels["bls_internet_share_range"], levels["bls_internet_row_share_range"]
        for t, r in zip(term, row):
            self.assertTrue(math.isclose(t, 1.2 * r, rel_tol=1e-12))


class ReceiptTieProperties(unittest.TestCase):
    """The new figures tie to other fields of the same receipts, and a
    changed field breaks the tie."""

    @classmethod
    def setUpClass(cls):
        cls.inputs = INKIND.load_inkind(REPO / "data/inkind", REPO / "data/current")
        cls.published = INKIND.published_standard_errors(REPO / "data")

    def components_copy(self):
        return json.loads(json.dumps(self.inputs["components"]))

    def test_rank_shift_is_the_stage_change_less_the_band_fixed_effect(self):
        components = self.components_copy()
        shifts = INKIND._rank_shift(components)
        for tenure in TENURES:
            row = components["runs"]["package"]["growth_2022_2025"]["by_tenure"][tenure]
            self.assertTrue(
                math.isclose(
                    shifts[tenure],
                    row["stage_change_points"] - (row["growth_with_stage"] - row["growth_without_imputed_terms"]),
                    abs_tol=1e-9,
                )
            )
        components["runs"]["package"]["growth_2022_2025"]["by_tenure"]["renter"]["rank_shift_points"] += 0.01
        with self.assertRaisesRegex(ValueError, "rank shift renter"):
            INKIND._rank_shift(components)

    def test_internet_share_ties_to_the_level_decomposition(self):
        components = self.components_copy()
        levels = INKIND._internet_and_levels(components)
        low, high = levels["bls_internet_share_range"]
        self.assertTrue(0 < low < high < 5)
        for run, (gap_low, gap_high) in levels["gap_with_bls_internet"].items():
            self.assertTrue(0 < gap_low < gap_high, run)
        terms = components["runs"]["package"]["years"]["2023"]["level_gap_percent_of_bls"]["renter"]["terms"]
        terms["internet"] += 0.01
        with self.assertRaisesRegex(ValueError, "BLS internet term package 2023 renter"):
            INKIND._internet_and_levels(components)

    def test_amount_rises_pair_the_same_replicate_weight(self):
        """Rotating 2025's replicates keeps that year's own standard error
        but changes the rise's, so the recorded rise pins the pairing."""
        inputs = {**self.inputs, "uncertainty": json.loads(json.dumps(self.inputs["uncertainty"]))}
        years = inputs["uncertainty"]["runs"]["package"]["years"]
        for draws in years["2025"]["replicates"]["amounts"]["rental_assistance_per_renter"]:
            draws[1:] = draws[2:] + draws[1:2]
        with self.assertRaisesRegex(ValueError, "rental_assistance_per_renter rise package"):
            INKIND.uncertainty_figures(inputs, self.published)

    def test_lifts_and_rises_have_positive_standard_errors(self):
        figures = INKIND.uncertainty_figures(self.inputs, self.published)
        for run in INKIND.UNCERTAINTY_RUNS:
            entry = figures["runs"][run]
            for name, rise in entry["amount_rises"].items():
                self.assertGreater(rise["standard_error"], 0, f"{run} {name}")
            for tenure in TENURES:
                for year, lift in entry["lifts"][tenure].items():
                    self.assertGreater(lift["standard_error"], 0, f"{run} {tenure} {year}")
                    self.assertGreater(lift["estimate"], 0, f"{run} {tenure} {year}")

    def test_cpi_vintage_matches_bls_page(self):
        INKIND.check_cpi_vintage(2.699)
        with self.assertRaisesRegex(ValueError, "BLS's page growth for 2025 CPI-U"):
            INKIND.check_cpi_vintage(2.70)


if __name__ == "__main__":
    unittest.main()
