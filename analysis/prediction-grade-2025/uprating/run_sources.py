"""One population run: each SPM resource source, projected to persons, plus SPM poverty, for one year and variant.

Variants replace 2025 input values with 2024 values times a chosen growth factor, before anything that depends
on them is computed:
  baseline             the model as released (policyengine 6.0.0 / policyengine-us 2.2.1)
  ss_cola              Social Security benefits grow with gov.ssa.uprating (the 2.5 percent COLA)
  ss_cola_pension_cpi  ss_cola, and pensions and retirement distributions grow with CPI-U
  wages_by_decile      wages grow by the survey's 2024->2025 growth of mean wages within each wage decile
  se_like_wages        self-employment income grows with the model's wage index instead of CBO business income
  all_three            ss_cola_pension_cpi and se_like_wages together

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
    cola = p.gov.ssa.uprating("2025-01-01") / p.gov.ssa.uprating("2024-01-01")
    cpi = p.gov.bls.cpi.cpi_u("2025-01-01") / p.gov.bls.cpi.cpi_u("2024-01-01")
    wage = p.calibration.gov.irs.soi.employment_income("2025-01-01") / p.calibration.gov.irs.soi.employment_income("2024-01-01")
    if variant in ("ss_cola", "ss_cola_pension_cpi", "all_three"):
        regrow(SS, cola)
    if variant in ("ss_cola_pension_cpi", "all_three"):
        regrow(PENSIONS, cpi)
    if variant in ("se_like_wages", "all_three"):
        regrow(SELF_EMPLOYMENT, wage)
    if variant == "wages_by_decile":
        v = "employment_income_before_lsr"
        s24 = sim.calculate(v, period=2024)
        x24, w = np.asarray(s24.values, dtype=np.float64), np.asarray(s24.weights, dtype=np.float64)
        pos = x24 > 0
        o = np.argsort(x24[pos], kind="stable")
        c = np.cumsum(w[pos][o]) / w[pos].sum()
        dec = np.zeros(pos.sum(), dtype=int)
        dec[o] = np.minimum((c * 10).astype(int), 9)
        f = np.ones_like(x24) * (p.calibration.gov.irs.soi.employment_income("2025-01-01") / p.calibration.gov.irs.soi.employment_income("2024-01-01"))
        f[pos] = 1 + np.asarray(WAGE_DECILE_GROWTH_PCT)[dec] / 100
        before = float(sim.calculate(v, period=2025).sum())
        sim.set_input(v, 2025, x24 * f)
        got = np.asarray(sim.calculate(v, period=2025).values, dtype=np.float64)
        assert np.allclose(got, x24 * f)
        overrides[v] = {"decile_growth_pct": WAGE_DECILE_GROWTH_PCT, "before_2025_total": before, "after_2025_total": float(sim.calculate(v, period=2025).sum())}

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
np.savez_compressed(f"sources-{year}-{variant}.npz", **cols)
w, a = cols["weight"], cols["age"]
groups = {"all": a >= 0, "under_18": a < 18, "age_18_64": (a >= 18) & (a < 65), "age_65_plus": a >= 65}
meta = {"year": year, "variant": variant, "dataset": DEFAULT_DATASET, "dataset_sha256": DEFAULT_DATASET_SHA256,
        "spm_pct": {g: float((cols["in_spm_poverty"][m] * w[m]).sum() / w[m].sum() * 100) for g, m in groups.items()},
        "overrides": overrides,
        "calc_seconds": round(time.time() - t0, 1), "peak_rss_gb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9, 2)}
json.dump(meta, open(f"sources-meta-{year}-{variant}.json", "w"), indent=1)
print(json.dumps(meta), flush=True)
