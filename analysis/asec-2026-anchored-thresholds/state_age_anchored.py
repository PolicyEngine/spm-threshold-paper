"""2025 SPM poverty, published and at 2024 thresholds x CPI-U, by state and by detailed age,
with replicate-weight standard errors. Inputs: pppub26.csv + asec_csv_repwgt_2026.csv (2026 CPS ASEC PU).
Anchoring identical to spm-threshold-paper analysis/asec-2026-anchored-thresholds/replicate_and_anchor.py."""
import sys, json, numpy as np, pandas as pd
S = sys.argv[1]; OUT = sys.argv[2]
cols = ["PH_SEQ","PPPOS","A_AGE","MARSUPWT","SPM_POOR","SPM_RESOURCES","SPM_POVTHRESHOLD","SPM_TENMORTSTATUS"]
d = pd.read_csv(f"{S}/asec26/pppub26.csv", usecols=cols)
hh = pd.read_csv(f"{S}/asec26/hhpub26.csv", usecols=["H_SEQ","GESTFIPS"])
d = d.merge(hh, left_on="PH_SEQ", right_on="H_SEQ", how="left", validate="many_to_one"); assert d.GESTFIPS.notna().all()
rw = pd.read_csv(f"{S}/asec26/asec_csv_repwgt_2026.csv")
rw.columns = [c.upper() for c in rw.columns]
m = d.merge(rw, left_on=["PH_SEQ","PPPOS"], right_on=["H_SEQ","PPPOS"], how="left", validate="one_to_one")
assert m.PWWGT0.notna().all(), "unmatched replicate rows"
assert np.allclose(m.PWWGT0, m.MARSUPWT / 100, rtol=1e-4), "PWWGT0 != MARSUPWT/100"  # MARSUPWT carries two implied decimals
cpi = 32649/31812; t25 = {1:41322.707, 2:34325.998, 3:41700.556}; t24 = {1:39231.0, 2:32879.0, 3:39220.0}
fac = m.SPM_TENMORTSTATUS.map({k:(t24[k]*cpi)/t25[k] for k in t25})
pub = (m.SPM_POOR == 1).to_numpy(float); anc = (m.SPM_RESOURCES < m.SPM_POVTHRESHOLD*fac).to_numpy(float)
W = m[[f"PWWGT{i}" for i in range(161)]].to_numpy(float)  # col 0 = full sample
def est(mask):
    w = W[mask]; p, a = pub[mask], anc[mask]
    rp = (w * p[:,None]).sum(0) / w.sum(0) * 100; ra = (w * a[:,None]).sum(0) / w.sum(0) * 100
    se = lambda r: float(np.sqrt(4/160 * ((r[1:] - r[0])**2).sum()))
    return {"published": round(float(rp[0]),2), "published_se": round(se(rp),2), "anchored": round(float(ra[0]),2), "anchored_se": round(se(ra),2),
            "effect_pp": round(float(rp[0]-ra[0]),2), "effect_se": round(se(rp-ra),2), "n_persons": int(mask.sum()), "weighted_persons_thousands": round(float(w[:,0].sum()/1e3),0)}
age = m.A_AGE.to_numpy()
ages = {"all": age>=0, "age_0_3": age<=3, "age_0_4": age<=4, "under_6": age<6, "under_18": age<18, "age_6_17": (age>=6)&(age<18), "age_18_64": (age>=18)&(age<65), "age_65_plus": age>=65, "age_75_plus": age>=75}
out = {"method": "2026 CPS ASEC public-use person file; person weight MARSUPWT/100 (= PWWGT0, the replicate base weight); anchoring scales SPM_POVTHRESHOLD by tenure so the national 2A2K base = corrected 2024 BLS value x (32,649/31,812); SEs from the 160 ASEC replicate weights, variance = 4/160 x sum of squared replicate deviations",
       "by_age": {k: est(v) for k, v in ages.items()}}
fips = {1:"AL",2:"AK",4:"AZ",5:"AR",6:"CA",8:"CO",9:"CT",10:"DE",11:"DC",12:"FL",13:"GA",15:"HI",16:"ID",17:"IL",18:"IN",19:"IA",20:"KS",21:"KY",22:"LA",23:"ME",24:"MD",25:"MA",26:"MI",27:"MN",28:"MS",29:"MO",30:"MT",31:"NE",32:"NV",33:"NH",34:"NJ",35:"NM",36:"NY",37:"NC",38:"ND",39:"OH",40:"OK",41:"OR",42:"PA",44:"RI",45:"SC",46:"SD",47:"TN",48:"TX",49:"UT",50:"VT",51:"VA",53:"WA",54:"WV",55:"WI",56:"WY"}
st = m.GESTFIPS.to_numpy()
out["by_state"] = {fips[f]: est(st == f) for f in sorted(fips)}
json.dump(out, open(f"{OUT}/RESULTS.json", "w"), indent=1)
rows = [{"state": k, **v} for k, v in out["by_state"].items()]
pd.DataFrame(rows).to_csv(f"{OUT}/by_state.csv", index=False)
print(json.dumps(out["by_age"], indent=1))
bs = pd.DataFrame(rows).sort_values("effect_pp", ascending=False)
print(bs[["state","published","published_se","anchored","effect_pp","effect_se","n_persons"]].head(12).to_string(index=False))
print("...")
print(bs[["state","published","published_se","anchored","effect_pp","effect_se","n_persons"]].tail(6).to_string(index=False))
print("effect range", bs.effect_pp.min(), bs.effect_pp.max(), "| states with effect > 2 SE:", int((bs.effect_pp > 2*bs.effect_se).sum()), "of", len(bs))
