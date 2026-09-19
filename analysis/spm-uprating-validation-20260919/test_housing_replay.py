"""Independent arithmetic fixtures for the declared model contract, not Census parity."""

import numpy as np
import pandas as pd
import pytest
from housing_replay import build_membership, packet_array, replay_housing_cap


def membership(spm=(10, 20, 20), households=(7, 7, 7), spm_ids=(10, 20)):
    return build_membership(
        person_ids=list(range(len(spm))),
        spm_ids=spm_ids,
        household_ids=sorted(set(households)),
        person_spm_ids=spm,
        person_household_ids=households,
    )


def replay(awards, tenant, housing, members=None):
    return replay_housing_cap(
        np.array(awards, dtype=np.float32),
        np.array(tenant, dtype=np.float32),
        np.array(housing, dtype=np.float64),
        members or membership(),
    )


def test_one_award_is_shared_with_unequal_sized_co_resident_unit():
    # Three residents: both units share the award; only the recipient's TTP counts.
    result = replay([12_000, 0], [3_600, 45_000], [5_000, 9_000])
    np.testing.assert_array_equal(result["allocated_subsidy"], [4_000, 8_000])
    np.testing.assert_array_equal(result["allocated_tenant_payment"], [1_200, 2_400])
    np.testing.assert_array_equal(result["capped_subsidy"], [3_800, 6_600])


def test_two_awards_are_counted_once_per_native_spm_not_once_per_member():
    result = replay([12_000, 3_000], [3_600, 900], [5_000, 9_000])
    np.testing.assert_array_equal(result["allocated_subsidy"], [5_000, 10_000])
    np.testing.assert_array_equal(result["allocated_tenant_payment"], [1_500, 3_000])
    np.testing.assert_array_equal(result["capped_subsidy"], [3_500, 6_000])


def test_cap_is_nonnegative_without_redistributing_unused_award():
    result = replay([12_000, 0], [3_600, 45_000], [1_000, 9_000])
    np.testing.assert_array_equal(result["capped_subsidy"], [0, 6_600])


def test_no_assistance_needs_no_housing_portion_and_ignores_hypothetical_ttp():
    result = replay([0, 0], [3_600, 45_000], [np.nan, np.nan])
    for field in result:
        np.testing.assert_array_equal(result[field], [0, 0])


def test_single_unit_census_example_is_7200():
    # Annual form of Census's monthly example: min(1500, 1100 - 500) * 12.
    members = membership(spm=(10,), households=(7,), spm_ids=(10,))
    result = replay([18_000], [6_000], [13_200], members)
    np.testing.assert_array_equal(result["capped_subsidy"], [7_200])


def test_household_totals_do_not_leak_between_households():
    members = membership(spm=(10, 20, 20), households=(7, 8, 8))
    result = replay([12_000, 0], [3_600, 45_000], [5_000, 9_000], members)
    np.testing.assert_array_equal(result["capped_subsidy"], [1_400, 0])


def test_allocation_rounds_to_float32_before_the_cap():
    # 1000/3 rounds upward in float32, just above the first housing portion.
    result = replay([1_000, 0], [1_000, 0], [333.33334, 1_000])
    assert result["capped_subsidy"][0] == 0
    assert result["allocated_tenant_payment"].dtype == np.float32
    assert result["allocated_subsidy"].dtype == np.float32


def test_cap_uses_unrounded_housing_portion_before_one_final_cast():
    members = membership(spm=(10,), households=(7,), spm_ids=(10,))
    result = replay([1_000], [300], [400.00001], members)
    assert result["capped_subsidy"][0] == np.float32(100.00001)
    assert result["capped_subsidy"][0] != np.float32(100)


def test_noncontiguous_reordered_ids_and_people_preserve_native_unit_order():
    members = membership(spm=(20, 10, 20), households=(7, 7, 7), spm_ids=(20, 10))
    result = replay([0, 12_000], [45_000, 3_600], [9_000, 5_000], members)
    np.testing.assert_array_equal(result["capped_subsidy"], [6_600, 3_800])


@pytest.mark.parametrize(
    "overrides",
    [
        {"person_ids": [0, 0, 2]},
        {"spm_ids": [10, 10]},
        {"spm_ids": [10, 20, 30]},
        {"person_spm_ids": [10, 99, 20]},
        {"person_household_ids": [7, 7, 8], "household_ids": [7, 8]},
        {"person_spm_ids": [10, 20]},
    ],
)
def test_invalid_membership_is_rejected(overrides):
    args = {
        "person_ids": [0, 1, 2],
        "spm_ids": [10, 20],
        "household_ids": [7],
        "person_spm_ids": [10, 20, 20],
        "person_household_ids": [7, 7, 7],
    }
    args.update(overrides)
    with pytest.raises(ValueError):
        build_membership(**args)


@pytest.mark.parametrize("bad", [np.nan, np.inf, -1])
def test_invalid_raw_awards_are_rejected(bad):
    with pytest.raises(ValueError):
        replay([bad, 0], [0, 0], [5_000, 9_000])


def test_missing_housing_portion_for_assisted_unit_is_rejected():
    with pytest.raises(ValueError):
        replay([1_000, 0], [0, 0], [np.nan, 9_000])


@pytest.mark.parametrize("problem", ["entity", "index", "dtype", "length"])
def test_native_packet_validation_rejects_ambiguous_rows(problem):
    packet = {
        "format": "spm-final-native-v2",
        "ids": {"spm_unit": [10, 20]},
        "entities": {"housing_assistance": "spm_unit"},
        "vectors": {
            "housing_assistance": {
                "series": pd.Series([1_000, 0], dtype=np.float32),
                "dtype": "float32",
            }
        },
    }
    if problem == "entity":
        packet["entities"]["housing_assistance"] = "person"
    elif problem == "index":
        packet["vectors"]["housing_assistance"]["series"].index = [1, 0]
    elif problem == "dtype":
        packet["vectors"]["housing_assistance"]["dtype"] = "float64"
    else:
        packet["ids"]["spm_unit"].append(30)
    with pytest.raises(ValueError):
        packet_array(packet, "housing_assistance", "spm_unit")
