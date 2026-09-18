"""Waterfall: 2024 SPM rate -> resources step (to the 2025 rate at 2024 thresholds x CPI-U) -> threshold step -> published 2025 rate, four age groups.
usage: uv run --with playwright python waterfall.py data.json out.png --logo teal.png"""
import json, sys, pathlib, argparse
from playwright.sync_api import sync_playwright
ap=argparse.ArgumentParser(); ap.add_argument("data"); ap.add_argument("out"); ap.add_argument("--logo"); a=ap.parse_args()
D=json.load(open(a.data)); order=["All people","Under 18","18 to 64","65 and over"]
YMAX=16.0; H=380; ppp=H/YMAX  # px per point
TEAL="rgba(44,110,107,1)"; TEAL_DK="#1D4044"; GRAY="#CBD5E1"
def bar(left,bottom_val,top_val,color,label,label_above=True,text_color="#1f2937"):
    b=bottom_val*ppp; h=max((top_val-bottom_val)*ppp,2)
    lab_y = (top_val*ppp+8) if label_above else (bottom_val*ppp-26)
    return (f'<div class="bar" style="left:{left}px;bottom:{b:.1f}px;height:{h:.1f}px;background:{color}"></div>'
            f'<div class="lab" style="left:{left}px;bottom:{lab_y:.1f}px;color:{text_color}">{label}</div>')
panels=""
for g in order:
    d=D[g]; y0=d["y2024_census"]; y1=d["anchored_2025"]; y2=d["published_2025"]; rs=d["resources_step"]; ts=d["threshold_step"]
    xs=[14,84,154,224]; w=56
    els =bar(xs[0],0,y0,TEAL,f"{y0:.1f}")
    els+=bar(xs[1],y1,y0,GRAY,f"{rs:+.1f}".replace("-","−"),label_above=False,text_color="#475467")
    els+=bar(xs[2],y1,y2,TEAL_DK,f"{ts:+.1f}")
    els+=bar(xs[3],0,y2,TEAL,f"{y2:.1f}")
    # connectors
    con=f'<div class="con" style="left:{xs[0]+w}px;width:{xs[1]-xs[0]-w}px;bottom:{y0*ppp:.1f}px"></div>'
    con+=f'<div class="con" style="left:{xs[1]+w}px;width:{xs[2]-xs[1]-w}px;bottom:{y1*ppp:.1f}px"></div>'
    con+=f'<div class="con" style="left:{xs[2]+w}px;width:{xs[3]-xs[2]-w}px;bottom:{y2*ppp:.1f}px"></div>'
    grid="".join(f'<div class="grid" style="bottom:{v*ppp:.1f}px"><span>{v:g}</span></div>' for v in (0,4,8,12,16))
    cats="".join(f'<div class="cat" style="left:{x}px">{t}</div>' for x,t in zip(xs,["2024","Resources","Thresholds","2025"]))
    panels+=f'<div class="panel"><h3>{g}</h3><div class="plot">{grid}{con}{els}</div><div class="cats">{cats}</div></div>'
logo=f'<img src="file://{pathlib.Path(a.logo).resolve()}" alt="PolicyEngine">' if a.logo else ""
html=f"""<!doctype html><html><head><meta charset="utf-8"><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet"><style>
body{{margin:0;background:#fff;font-family:Inter,system-ui,sans-serif;color:#1f2937}} .wrap{{width:1440px;padding:28px 36px 24px;box-sizing:border-box}}
h2{{font-size:30px;margin:0 0 4px;font-weight:700;color:#0B1F2A}} .sub{{color:#475467;font-size:16px;margin:0 0 22px;max-width:1300px}}
.row{{display:flex;gap:28px}} .panel{{width:318px}} .panel h3{{font-size:17px;font-weight:600;margin:0 0 10px 32px;color:#0B1F2A}}
.plot{{position:relative;height:{H}px;margin-left:32px;border-bottom:1px solid #94A3B8}}
.grid{{position:absolute;left:0;right:0;height:0;border-top:1px solid #EEF2F6}} .grid span{{position:absolute;left:-30px;top:-8px;font-size:12px;color:#94A3B8;width:24px;text-align:right}}
.bar{{position:absolute;width:56px;border-radius:3px 3px 0 0}} .lab{{position:absolute;width:56px;text-align:center;font-size:15px;font-weight:600}}
.con{{position:absolute;height:0;border-top:1px dashed #94A3B8}}
.cats{{position:relative;height:22px;margin-left:32px;margin-top:8px}} .cat{{position:absolute;width:56px;text-align:center;font-size:12.5px;color:#475467}}
.legend{{display:flex;gap:22px;font-size:14px;color:#374151;margin:18px 0 0 0}} .legend i{{display:inline-block;width:16px;height:16px;border-radius:3px;vertical-align:-3px;margin-right:7px}}
.foot{{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;margin-top:14px}} .src{{font-size:13px;color:#6B7280;margin:0;max-width:1200px}} .foot img{{height:26px;width:auto;opacity:0.9}}
</style></head><body><div class="wrap">
<h2>SPM poverty, 2024 to 2025: what resources did, and what thresholds did</h2>
<p class="sub">Percent of people below the SPM threshold. Resources: the change from 2024 to the 2025 rate at 2024 thresholds grown by CPI-U, so resources measured against prices. Thresholds: the further change to the published 2025 rate, from threshold growth beyond CPI-U.</p>
<div class="row">{panels}</div>
<div class="legend"><span><i style="background:{TEAL}"></i>Published rate</span><span><i style="background:{GRAY}"></i>Resources, at 2024 thresholds × CPI-U</span><span><i style="background:{TEAL_DK}"></i>Threshold growth beyond CPI-U</span></div>
<div class="foot"><p class="src">Source: U.S. Census Bureau, P60-290 (2024 rates, restated on Vintage 2025 controls); PolicyEngine recomputation from the 2026 CPS ASEC public-use file for the 2025 rates. Labels rounded to one decimal; steps computed from unrounded rates.</p>{logo}</div>
</div></body></html>"""
htmlp=pathlib.Path(a.out).with_suffix(".html"); htmlp.write_text(html)
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_page(viewport={"width":1440,"height":760},device_scale_factor=2)
    pg.goto(f"file://{htmlp.resolve()}"); pg.wait_for_load_state("networkidle"); pg.wait_for_timeout(700); pg.locator(".wrap").screenshot(path=a.out); b.close()
print("wrote",a.out)
