# Housing-cap contract adjudication

Assessment date: 2026-09-19. This note assesses the policyengine-us 2.2.1
housing-resource contract used in the September 15 registry matrix. It reads
source code and saved receipts; it does not execute a population simulation.

## Decision

The frozen replay must change to test the documented model contract. Its
unit-local formula omits household subsidy proration. Restoring that formula in
the country model would remove an allocation step supported by Census's
methodology.

The current country formula implements that proration and retains an explicit
assumption about tenant contributions. A successor can establish **model-contract
agreement under assumption A4**. It cannot establish full Census replication or
remove A4 from the limitations. The sources reviewed here do not justify changing
the country formula merely to make the frozen replay pass.

## Primary-source boundary

Census's technical documentation, updated September 15, 2026, describes housing
subsidies as market rent less tenant payment, initially at household level. It
prorates subsidy value across Supplemental Poverty Measure (SPM) units by their
shares of household members. It caps the resource at the appropriate threshold's
housing portion less tenant payment. Census estimates tenant payment by applying
HUD rules to household income. The passage does not specify how to allocate that
payment across multiple SPM units. [Census technical documentation, pp. 14-15](https://www2.census.gov/programs-surveys/supplemental-poverty-measure/datasets/spm/spm_techdoc.pdf#page=14).

Johnson, Renwick and Short explain why the tenant contribution must reduce the
cap. Their example has a $30,000 threshold, a $13,200 housing portion, an $18,000
uncapped subsidy and a $6,000 contribution. The resulting housing resource is
$7,200. With $20,000 cash income, resources total $27,200, below the threshold.
The paper also describes headcount proration of household subsidies in its
discussion of the earlier method. It does not resolve the current model's
awarded-family contribution assumption. [Census housing-assistance paper,
pp. 8 and 11](https://www.census.gov/content/dam/Census/library/working-papers/2010/demo/spm-housingassistancejuly2011.pdf#page=11).

BLS describes the housing component as shelter and utilities and distinguishes
the housing share from the whole poverty threshold. Its discussion supports
using the unit's housing amount as the cap input; it does not supply an
alternative tenant-payment allocation rule. [Renwick and Garner, 2020](https://www.bls.gov/osmr/research-papers/2020/ec200090.htm).

## Exact model and replay contracts

For native SPM unit `i` in household `h`, define:

- `a_i`: stored, uncapped `housing_assistance` program award.
- `t_i`: stored `hud_ttp`, including hypothetical values for nonrecipients.
- `n_i`: actual member count; `N_h`: household member count.
- `H_i`: canonical, unrounded, geographically adjusted housing portion.

The September 15 model computes:

```text
A_h = sum(a_j for native SPM units j in household h)
T_h = sum(t_j for native SPM units j in h with a_j > 0)
allocated_award_i   = float32((n_i / N_h) * A_h)
allocated_payment_i = float32((n_i / N_h) * T_h)
resource_i = float32(
    min(float64(allocated_award_i),
        max(H_i - float64(allocated_payment_i), 0))
) when allocated_award_i > 0, otherwise 0
```

**Both household totals reach every SPM unit by member share**, including units
with zero original award. Only the construction of `T_h` filters to positively
awarded units. The final assisted mask tests the allocated award. General
housing benefits retain the original awards.

The model stores the two allocated variables as float32 before the cap reads
them as float64. The canonical `H_i` remains float64 until the final result.
The arithmetic above expresses the mathematical aggregation; byte-level replay
must also check the runtime's allocation and reduction order.

The frozen runner instead computes, directly from person-broadcast unit values:

```text
old_resource_i = float32(min(a_i, max(H_i - t_i, 0)))
```

It neither pools nor prorates. A zero-award co-resident consequently receives
zero in this replay even when the model allocates them a household subsidy.
For a household containing one SPM unit, the two contracts agree for nonnegative
awards and payments, apart from any storage details.

The country documentation calls the construction of `T_h` **A4**: retain the
contribution associated with actual modeled awards and exclude other units'
hypothetical payments. This preserves the existing HUD program-family
approximation. It does not reproduce Census's household-income estimator by
construction. Summing every unit's hypothetical `hud_ttp` would not generally
reproduce that estimator either: per-unit deductions, minimum payments and
maximum operators need not commute with household aggregation. No source-backed
case was found for silently substituting either estimator in this replay.

The three country formulas and A4 documentation remain unchanged on the live
country `main` inspected at commit
`c353e9b46cdb25ba34e262253aa5eeec19f8d062` (September 19):

- [Award allocation](https://github.com/PolicyEngine/policyengine-us/blob/c353e9b46cdb25ba34e262253aa5eeec19f8d062/policyengine_us/variables/household/income/spm_unit/spm_unit_allocated_housing_subsidy.py)
- [Tenant-payment allocation and A4](https://github.com/PolicyEngine/policyengine-us/blob/c353e9b46cdb25ba34e262253aa5eeec19f8d062/policyengine_us/variables/household/income/spm_unit/spm_unit_allocated_tenant_payment.py)
- [Final cap](https://github.com/PolicyEngine/policyengine-us/blob/c353e9b46cdb25ba34e262253aa5eeec19f8d062/policyengine_us/variables/household/income/spm_unit/spm_unit_capped_housing_subsidy.py)
- [Documented assumptions](https://github.com/PolicyEngine/policyengine-us/blob/c353e9b46cdb25ba34e262253aa5eeec19f8d062/docs/spm.md#housing-allocation-and-its-assumptions)

## Independent fixture expectations

These are proposed arithmetic fixtures, not newly executed simulation results.
Amounts are annual dollars. Except for the first row's published example, they
are synthetic cases derived from the explicit contract above. The supplied
`H` values isolate allocation and capping; they are not asserted to be actual
county threshold values.

| Case | Inputs | Expected allocated award | Expected allocated payment | Expected capped resource |
|---|---|---|---|---|
| Published single-unit cap | `a=18,000; t=6,000; H=13,200` | `18,000` | `6,000` | `7,200` |
| Unequal units, one original award | Same household, `n=[1,2]; a=[12,000,0]; t=[3,600,45,000]; H=[5,000,9,000]` | `[4,000,8,000]` | `[1,200,2,400]` | `[3,800,6,600]` |
| Multiple original awards | Same household, `n=[1,2]; a=[12,000,3,000]; t=[3,600,900]; H=[5,000,9,000]` | `[5,000,10,000]` | `[1,500,3,000]` | `[3,500,6,000]` |
| No redistribution after a cap binds | Same as one-award case, but `H=[1,000,9,000]` | `[4,000,8,000]` | `[1,200,2,400]` | `[0,6,600]` |
| Zero household awards | `a=[0,0]`, arbitrary nonnegative `t`, missing geography allowed for this resource | `[0,0]` | `[0,0]` | `[0,0]`; no housing-threshold call |
| Cap floor and equality | Single unit, `a=10,000; t=5,000; H=5,000` | `10,000` | `5,000` | `0`; remains `0` when `t > H` |

In the unequal-unit case the old formula gives `[1,400,0]`, which discriminates
the contracts. Changing the nonrecipient's hypothetical payment from `45,000`
to `0` must leave the A4 result unchanged. Changing that unit to a positive
original award must include its payment in `T_h`.

Additional required fixtures should interleave persons and households, permute
SPM-unit order, and include an independent household to catch index alignment
or cross-household leakage. A seven-person household split into units of sizes
one and six, with a $10,000 household award, exercises noninteger shares and
float32 storage. Check conservation before storage, then use dtype-appropriate
rounding checks after storage. Do not require exact mathematical conservation
of separately rounded float32 allocations.

Every SPM unit must belong wholly to one household. Reject inconsistent
memberships, missing native values, nonfinite numbers and negative program
awards rather than silently assigning an allocation. Validate member counts
against the packet's membership arrays. A person-mapped unit award is duplicated
on each member: summing that vector directly would inflate household awards.
Reconstruct one value per native unit, or use the native vectors.

## Scope of a successor pass

The September 15 receipts record 16 failed endpoints, with housing cap the only
failed direct-replay field. They also record unchanged printed poverty rates,
exact within-run loader/seed parity and changes to a small number of housing-cap
records. Those measurements motivate a successor; they do not adjudicate A4 or
certify external statistical accuracy. [Original verdict and limits](/Users/maxghenis/spm-rebuild-20260908/rollout/requalification-registry-20260915/FINAL-REPORT.md:426).

A successor should retain the original receipts and produce a separately named
result, such as `MODEL_CONTRACT_REPLAY_PASS`, identifying the formula above and
A4. It should report the canonical calculator-field checks separately from the
country allocation/cap check. Reconstruct the cap from primitive awards,
payments and memberships rather than treating the model's allocated outputs as
the oracle inputs. Compare reconstructed allocations with those outputs when
available.

Passing saved-packet replay alone does not confer the frozen coordinator's
`VERIFIED_ENDPOINT_SUCCESS` status or replace its eight missing comparator
receipts. A newly reviewed execution gate and its fresh authenticated run remain
separate evidence. Full Census housing-resource parity would additionally
require a validated household contribution estimator and evidence of the
multi-unit allocation used by Census, ideally production-code or microdata
comparisons. This note neither requests contact with Census nor claims that
such confirmation has occurred.

## Read-only inputs for replay implementation

The following local artifacts were inspected without loading the population H5
or unpickling person vectors:

- Frozen replay: `/Users/maxghenis/spm-rebuild-20260908/rollout/final-core-execution-preparation-r5-agefix-20260911/run_endpoint.py`, `direct_calculator_replay`, lines 202-265.
- Frozen packet schema and helpers: `/Users/maxghenis/spm-rebuild-20260908/rollout/final-core-execution-preparation-r5-agefix-20260911/endpoint_support.py`.
- Registry endpoint example: `/Users/maxghenis/spm-rebuild-20260908/rollout/requalification-registry-20260915/endpoints/direct_country/canonical-direct_country-2024-ce_trend-seed0/`; inspect `failure.json`, `input-schema.json`, `calculator-replay.json` and packet definitions before reading saved vectors.
- Other endpoints: sibling directories for 2025/2026 `ce_trend`, 2026 `zero_real`, seeds 0/42, and the `base_wrapper` arm.
- Cross-run receipt: `/Users/maxghenis/spm-rebuild-20260908/rollout/requalification-registry-20260915/receipts/CROSS-RUN-VS-R2.json`.
- Within-run receipt: `/Users/maxghenis/spm-rebuild-20260908/rollout/requalification-registry-20260915/receipts/WITHIN-RUN-PARITY.json`.
- Installed model formulas: `/Users/maxghenis/spm-rebuild-20260908/rollout/requalification-registry-20260915/runtime-env/lib/python3.13/site-packages/policyengine_us/variables/household/income/spm_unit/`, the three files linked above.
- Core mapping semantics: `/Users/maxghenis/spm-rebuild-20260908/rollout/requalification-registry-20260915/runtime-env/lib/python3.13/site-packages/policyengine_core/simulations/simulation.py`, `map_result`, line 629. Group-to-group mapping divides source amounts across members and sums into the target group.
- Calculator housing amount: `/Users/maxghenis/spm-rebuild-20260908/rollout/requalification-registry-20260915/runtime-env/lib/python3.13/site-packages/spm_calculator/release.py`, lines 500-514. It computes `H = unadjusted_threshold * (geographic_factor + housing_share - 1)`.
- Existing model tests: `/Users/maxghenis/spm-rebuild-20260908/rollout/codex-continuation-20260912/downstream-execution-review/source/api-inventory-0/policyengine_us/tests/unit/test_spm_housing_allocation.py`.

Skills loaded for this work: `policyengine`, `policyengine-data`,
`policyengine-model-development` (including agent loading, variables,
periods/aggregation and tests references), `pdf`, `policyengine-writing` and
`policyengine-standards`. Repository instructions were read; the original
country checkout was dirty and stale, so no work was performed there. This note
is the only file authored by this worker, in the coordinator's fresh paper
worktree.
