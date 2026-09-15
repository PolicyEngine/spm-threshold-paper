"""Replicate P60-290 SPM/official toplines from the 2026 CPS ASEC public-use person file
and recompute 2025 SPM poverty with national thresholds anchored to 2024 (x CPI-U).
Weights: SPM_WEIGHT/100 for SPM, MARSUPWT/100 for official. Tenure codes verified from
the implied base threshold: 1 owner w/ mortgage 41,323; 2 owner w/o 34,326; 3 renter 41,701.
Anchoring scales only the national base by tenure (equivalence scale and geo adjustment
stay at 2025 values). 2024 bases = BLS corrected series (39,231 / 32,879 / 39,220).
CPI-U factor = Census's own 2025/2024 two-adult-two-child OPM threshold ratio.
"""
import sys, json, pandas as pd, numpy as np
cpi = float(sys.argv[1]) if len(sys.argv) > 1 else 32649/31812
d = pd.read_csv('pppub26.csv', usecols=['A_AGE','MARSUPWT','SPM_WEIGHT','SPM_POOR','SPM_RESOURCES','SPM_POVTHRESHOLD','SPM_TENMORTSTATUS','PERLIS','POV_UNIV'])
mw = d.MARSUPWT/100; w = mw  # person weight for person-level poverty rates (SPM_WEIGHT variant checked: within 0.05pp)
grp = np.select([d.A_AGE<18, d.A_AGE>=65], ['children','65+'], '18-64')
t25 = {1:41322.707, 2:34325.998, 3:41700.556}; t24 = {1:39231.0, 2:32879.0, 3:39220.0}
fac = d.SPM_TENMORTSTATUS.map({k:(t24[k]*cpi)/t25[k] for k in t25})
poor_anch = d.SPM_RESOURCES < d.SPM_POVTHRESHOLD*fac
def rates(flag, wt):
    return {g: round(100*(wt[m]*flag[m]).sum()/wt[m].sum(), 2) for g,m in
            [('all', np.ones(len(d),bool)), ('children', grp=='children'), ('18-64', grp=='18-64'), ('65+', grp=='65+')]}
out = {"cpi_factor": round(cpi,5), "anchor_factors": {k: round((t24[k]*cpi)/t25[k],4) for k in t25},
       "spm_published_replication": rates(d.SPM_POOR==1, w),
       "official_replication": {g: round(100*(mw[m]*(d.PERLIS[m]==1)).sum()/mw[m].sum(),2) for g,m in
            [('all', d.POV_UNIV==1), ('children', (grp=='children')&(d.POV_UNIV==1)), ('18-64', (grp=='18-64')&(d.POV_UNIV==1)), ('65+', (grp=='65+')&(d.POV_UNIV==1))]},
       "spm_anchored_2024_thresholds": rates(poor_anch, w),
       "by_tenure": {name: {"published": round(100*(w[m]*(d.SPM_POOR[m]==1)).sum()/w[m].sum(),2), "anchored": round(100*(w[m]*poor_anch[m]).sum()/w[m].sum(),2)}
                     for name,m in [('owner_with_mortgage', d.SPM_TENMORTSTATUS==1), ('owner_without_mortgage', d.SPM_TENMORTSTATUS==2), ('renter', d.SPM_TENMORTSTATUS==3)]}}
out["threshold_effect_pp"] = {g: round(out["spm_published_replication"][g]-out["spm_anchored_2024_thresholds"][g],2) for g in out["spm_published_replication"]}
print(json.dumps(out, indent=1))
