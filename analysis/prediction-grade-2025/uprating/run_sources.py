"""One population run: each SPM resource source, projected to persons, plus SPM poverty, for one year and variant.

Variants replace 2025 input values with 2024 values times a chosen growth factor, before anything that depends
on them is computed:
  baseline             the model as released (policyengine 6.0.0 / policyengine-us 2.2.1)
  ss_cola              Social Security benefits grow with gov.ssa.uprating (the 2.5 percent COLA)
  ss_cola_pension_cpi  ss_cola, and pensions and retirement distributions grow with CPI-U
  wages_by_decile      wages grow by the survey's 2024->2025 growth of mean wages within each wage decile
  se_like_wages        self-employment income grows with the model's wage index instead of CBO business income
  all_three            ss_cola_pension_cpi and se_like_wages together
  all_three_cpi_avg    all_three, with pensions at CPI-U annual-average growth (2.63%) instead of January over January
  all_three_ss_survey  all_three_cpi_avg, with Social Security at the survey's age-adjusted per-recipient growth (3.45%)
  all_three_ss_66plus  all_three_cpi_avg, with Social Security at the survey's age-adjusted growth for recipients 66+ (4.04%)
  wages_by_family_decile  wages grow by the survey's growth of mean wages within each decile of the earner's SPM
                       unit's resources over threshold (needs sources-2024-baseline.npz in the working directory)
  all_four             all_three_cpi_avg and wages_by_family_decile together

usage: python run_sources.py <year> <variant>"""
import json, resource, sys, time
import numpy as np
from policyengine_us import Microsimulation
from policyengine_us.system import DEFAULT_DATASET, DEFAULT_DATASET_SHA256

year, variant = int(sys.argv[1]), sys.argv[2]
sim = Microsimulation()
t0 = time.time()
p = sim.tax_benefit_system.parameters

SS = ["social_security_retirement", "social_security_disability", "social_security_survivors", "social_security_dependents"]
PENSIONS = ["tax_exempt_public_pension_income", "tax_exempt_private_pension_income", "taxable_public_pension_income",
            "taxable_private_pension_income", "taxable_ira_distributions", "taxable_401k_distributions",
            "taxable_sep_distributions", "taxable_403b_distributions", "keogh_distributions", "tax_exempt_ira_distributions",
            "tax_exempt_401k_distributions", "tax_exempt_sep_distributions", "tax_exempt_403b_distributions"]
SELF_EMPLOYMENT = ["self_employment_income_before_lsr", "sstb_self_employment_income_before_lsr"]
# ASEC 2025 -> 2026, earners 16+ with wages, growth of mean wage within each decile of their SPM unit's
# resources over threshold (asec/wage_deciles.py, "by_spm_ratio_decile")
FAMILY_DECILE_GROWTH_PCT = [6.57, 4.88, 5.66, 5.59, 4.31, 4.73, 6.12, 3.04, 3.5, 5.28]
# CPI-U annual-average growth, 2024 to 2025: the growth of the official poverty threshold (P60-290 Table 10)
CPI_ANNUAL_AVERAGE = 32649 / 31812
# ASEC 2025 -> 2026 Social Security per recipient, holding the 2024 recipient age mix (asec/survey_growth.py)
SS_SURVEY_AGE_ADJUSTED = 1.0345
# Same, recipients 66 and over only (four age bands)
SS_SURVEY_66_PLUS = 1.0404
# ASEC 2025 -> 2026, all earners 16+, growth of mean wage within each wage decile (asec/wage_deciles.json)
WAGE_DECILE_GROWTH_PCT = [4.85, 4.62, 4.43, 5.11, 4.43, 4.61, 4.26, 4.12, 4.65, 5.31]

overrides = {}
if year == 2025 and variant != "baseline":
    def regrow(vs, factor):
        for v in vs:
            x24 = np.asarray(sim.calculate(v, period=2024).values, dtype=np.float64)
            overrides[v] = {"factor": factor, "before_2025_total": float(sim.calculate(v, period=2025).sum())}
            sim.set_input(v, 2025, x24 * factor)
            got = np.asarray(sim.calculate(v, period=2025).values, dtype=np.float64)
            assert np.allclose(got, x24 * factor), v
            overrides[v]["after_2025_total"] = float(sim.calculate(v, period=2025).sum())

    def regrow_wages_by_decile(rank, growth_pct, label):
        """Grow each earner's wages by the growth for their decile of `rank` among 2024 earners (person-weighted)."""
        v = "employment_income_before_lsr"
        s24 = sim.calculate(v, period=2024)
        x24, w = np.asarray(s24.values, dtype=np.float64), np.asarray(s24.weights, dtype=np.float64)
        pos = x24 > 0
        o = np.argsort(rank[pos], kind="stable")
        c = np.cumsum(w[pos][o]) / w[pos].sum()
        dec = np.zeros(pos.sum(), dtype=int)
        dec[o] = np.minimum((c * 10).astype(int), 9)
        f = np.ones_like(x24) * wage
        f[pos] = 1 + np.asarray(growth_pct)[dec] / 100
        before = float(sim.calculate(v, period=2025).sum())
        sim.set_input(v, 2025, x24 * f)
        got = np.asarray(sim.calculate(v, period=2025).values, dtype=np.float64)
        assert np.allclose(got, x24 * f)
        overrides[v] = {"ranked_by": label, "decile_growth_pct": list(growth_pct), "before_2025_total": before,
                        "after_2025_total": float(sim.calculate(v, period=2025).sum())}

    cola = p.gov.ssa.uprating("2025-01-01") / p.gov.ssa.uprating("2024-01-01")
    cpi = p.gov.bls.cpi.cpi_u("2025-01-01") / p.gov.bls.cpi.cpi_u("2024-01-01")  # January over January
    wage = p.calibration.gov.irs.soi.employment_income("2025-01-01") / p.calibration.gov.irs.soi.employment_income("2024-01-01")
    ss_rate = {"ss_cola": cola, "ss_cola_pension_cpi": cola, "all_three": cola, "all_three_cpi_avg": cola,
               "all_three_ss_survey": SS_SURVEY_AGE_ADJUSTED, "all_three_ss_66plus": SS_SURVEY_66_PLUS,
               "all_four": cola}.get(variant)
    pension_rate = {"ss_cola_pension_cpi": cpi, "all_three": cpi, "all_three_cpi_avg": CPI_ANNUAL_AVERAGE,
                    "all_three_ss_survey": CPI_ANNUAL_AVERAGE, "all_three_ss_66plus": CPI_ANNUAL_AVERAGE,
                    "all_four": CPI_ANNUAL_AVERAGE}.get(variant)
    if ss_rate is not None:
        regrow(SS, ss_rate)
    if pension_rate is not None:
        regrow(PENSIONS, pension_rate)
    if variant in ("se_like_wages", "all_three", "all_three_cpi_avg", "all_three_ss_survey", "all_three_ss_66plus", "all_four"):
        regrow(SELF_EMPLOYMENT, wage)
    if variant == "wages_by_decile":
        x24 = np.asarray(sim.calculate("employment_income_before_lsr", period=2024).values, dtype=np.float64)
        regrow_wages_by_decile(x24, WAGE_DECILE_GROWTH_PCT, "2024 wage")
    if variant in ("wages_by_family_decile", "all_four"):
        base = np.load("sources-2024-baseline.npz")
        ids = np.asarray(sim.calculate("person_id", period=2024).values)
        assert (base["person_id"] == ids).all(), "2024 baseline arrays are not aligned with this simulation"
        ratio = base["net_income"] / base["threshold"]
        regrow_wages_by_decile(ratio, FAMILY_DECILE_GROWTH_PCT, "2024 SPM resources / threshold")

PERSON_SOURCES = {
    "wages": ["employment_income"],
    "self_employment": ["self_employment_income", "sstb_self_employment_income"],
    "pensions_retirement": ["pension_income", "retirement_distributions"],
    "interest_dividends_gains": ["interest_income", "dividend_income", "capital_gains"],
    "rental": ["rental_income"],
    "market_total": ["market_income"],
    "social_security": ["social_security"],
    "social_security_retirement": ["social_security_retirement"],
    "social_security_disability": ["social_security_disability"],
    "social_security_survivors": ["social_security_survivors"],
    "social_security_dependents": ["social_security_dependents"],
    "ssi": ["ssi"],
    "unemployment": ["unemployment_compensation"],
}
UNIT_SOURCES = {
    "snap": ["snap"],
    "housing_subsidy": ["spm_unit_capped_housing_subsidy"],
    "school_meals": ["free_school_meals", "reduced_price_school_meals"],
    "wic": ["wic"],
    "tanf": ["tanf"],
    "benefits_total": ["spm_unit_benefits"],
    "payroll_tax": ["spm_unit_payroll_tax", "spm_unit_self_employment_tax"],
    "federal_tax": ["spm_unit_federal_tax"],
    "state_tax": ["spm_unit_state_tax"],
    "taxes_total": ["spm_unit_taxes"],
    "moop": ["spm_unit_medical_out_of_pocket_expenses"],
    "work_childcare": ["spm_unit_capped_work_childcare_expenses"],
    "child_support_paid": ["child_support_expense"],
    "expenses_total": ["spm_unit_spm_expenses"],
    "net_income": ["spm_unit_net_income"],
    "threshold": ["spm_unit_spm_threshold"],
    "in_spm_poverty": ["spm_unit_is_in_spm_poverty"],
}
cols = {}
for name, vs in PERSON_SOURCES.items():
    unit = sum(np.asarray(sim.calculate(v, period=year, map_to="spm_unit").values, dtype=np.float64) for v in vs)
    cols[name] = np.asarray(sim.map_result(unit, "spm_unit", "person"), dtype=np.float64)
for name, vs in UNIT_SOURCES.items():
    cols[name] = sum(np.asarray(sim.calculate(v, period=year, map_to="person").values, dtype=np.float64) for v in vs)
age = sim.calculate("age", period=year, map_to="person")
cols["age"] = np.asarray(age.values)
cols["weight"] = np.asarray(age.weights)
cols["person_id"] = np.asarray(sim.calculate("person_id", period=year).values)
cols["tenure"] = np.asarray(sim.calculate("spm_unit_tenure_type", period=year, map_to="person").values).astype(str)
np.savez_compressed(f"sources-{year}-{variant}.npz", **cols)
w, a = cols["weight"], cols["age"]
groups = {"all": a >= 0, "under_18": a < 18, "age_18_64": (a >= 18) & (a < 65), "age_65_plus": a >= 65}
meta = {"year": year, "variant": variant, "dataset": DEFAULT_DATASET, "dataset_sha256": DEFAULT_DATASET_SHA256,
        "spm_pct": {g: float((cols["in_spm_poverty"][m] * w[m]).sum() / w[m].sum() * 100) for g, m in groups.items()},
        "overrides": overrides,
        "calc_seconds": round(time.time() - t0, 1), "peak_rss_gb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9, 2)}
json.dump(meta, open(f"sources-meta-{year}-{variant}.json", "w"), indent=1)
print(json.dumps(meta), flush=True)
