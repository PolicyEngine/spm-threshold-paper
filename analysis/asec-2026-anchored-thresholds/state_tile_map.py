"""Render a state tile map in the style of the PolicyEngine slides' state map (StateChildPovertyMapSlide): 11x8 tile grid, teal shading.
usage: python state_tile_map.py <csv> <out.png> [--value COL] [--title T] [--subtitle S] [--us LABEL] [--bins "0.4:under 0.4,0.8:0.4 to 0.8,..."] [--note N] [--source SRC] [--decimals 1] [--logo PNG]
Defaults render the 2025 threshold effect from by_state.csv. Needs: uv run --with playwright --with pandas; playwright chromium installed."""
import sys, argparse, pathlib, pandas as pd
from playwright.sync_api import sync_playwright
POS = {"AK": (0, 0), "AL": (6, 6), "AR": (4, 5), "AZ": (1, 5), "CA": (0, 4), "CO": (2, 4), "CT": (9, 3), "DC": (8, 5), "DE": (9, 4), "FL": (7, 7), "GA": (7, 6), "HI": (0, 7), "IA": (4, 3), "ID": (1, 2), "IL": (5, 2), "IN": (5, 3), "KS": (3, 5), "KY": (5, 4), "LA": (4, 6), "MA": (9, 2), "MD": (8, 4), "ME": (10, 0), "MI": (6, 2), "MN": (4, 2), "MO": (4, 4), "MS": (5, 6), "MT": (2, 2), "NC": (6, 5), "ND": (3, 2), "NE": (3, 4), "NH": (10, 1), "NJ": (8, 3), "NM": (2, 5), "NV": (1, 3), "NY": (8, 2), "OH": (6, 3), "OK": (3, 6), "OR": (0, 3), "PA": (7, 3), "RI": (10, 3), "SC": (7, 5), "SD": (3, 3), "TN": (5, 5), "TX": (3, 7), "UT": (1, 4), "VA": (7, 4), "VT": (9, 1), "WA": (0, 2), "WI": (5, 1), "WV": (6, 4), "WY": (2, 3)}
SHADES = [("rgba(44,110,107,0.12)", "#1f2937"), ("rgba(44,110,107,0.30)", "#1f2937"), ("rgba(44,110,107,0.52)", "#ffffff"), ("rgba(44,110,107,0.74)", "#ffffff"), ("rgba(44,110,107,1)", "#ffffff")]
ap = argparse.ArgumentParser(); ap.add_argument("csv"); ap.add_argument("out")
ap.add_argument("--value", default="effect_pp"); ap.add_argument("--se", default="effect_se")
ap.add_argument("--title", default="Points added to 2025 SPM poverty by threshold growth beyond CPI-U, by state")
ap.add_argument("--subtitle", default="Published 2025 rate minus the rate at 2024 thresholds grown by CPI-U, in percentage points")
ap.add_argument("--us", default="United States: 0.8"); ap.add_argument("--decimals", type=int, default=1); ap.add_argument("--logo", default=None, help="path to the PolicyEngine teal wordmark PNG; rendered bottom-right as a watermark")
ap.add_argument("--bins", default="0.4:under 0.4,0.8:0.4 to 0.8,1.2:0.8 to 1.2,1.6:1.2 to 1.6,99:1.6 and up")
ap.add_argument("--note", default="Single-year state estimates; replicate-weight standard errors run 0.1 to 0.7 points. Tiles are equal in size, so the layout is about position, not area.")
ap.add_argument("--source", default="Source: PolicyEngine recomputation from the 2026 CPS ASEC public-use file; 2024 thresholds from BLS's corrected series, grown by CPI-U (32,649 / 31,812).")
args = ap.parse_args()
BINS = [(float(b.split(":")[0]), b.split(":")[1], SHADES[i][0], SHADES[i][1]) for i, b in enumerate(args.bins.split(","))]
def bin_for(v): return next(b for b in BINS if v < b[0])
df = pd.read_csv(args.csv); out = args.out; VAL, SE, D = args.value, args.se, args.decimals
tiles = "".join(f'<div class="tile" style="grid-column:{POS[r["state"]][0]+1};grid-row:{POS[r["state"]][1]+1};background:{bin_for(r[VAL])[2]};color:{bin_for(r[VAL])[3]}" title="{r["state"]}: {r[VAL]:.2f} ± {r[SE]:.2f}"><b>{r["state"]}</b><span>{r[VAL]:.{D}f}</span></div>' for _, r in df.iterrows())
logo = f'<img src="file://{pathlib.Path(args.logo).resolve()}" alt="PolicyEngine">' if args.logo else ""
legend = "".join(f'<li><i style="background:{b[2]}"></i>{b[1]}</li>' for b in BINS)
html = f"""<!doctype html><html><head><meta charset="utf-8"><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet"><style>
body{{margin:0;background:#fff;font-family:Inter,system-ui,sans-serif;color:#1f2937}} .wrap{{width:1440px;padding:28px 36px 24px;box-sizing:border-box}}
h2{{font-size:30px;margin:0 0 4px;font-weight:700;color:#0B1F2A}} .sub{{color:#475467;font-size:16px;margin:0 0 18px}}
.row{{display:flex;align-items:flex-start;gap:32px}} .grid{{display:grid;gap:4px;grid-template-columns:repeat(11,88px);grid-template-rows:repeat(8,56px)}}
.tile{{border-radius:6px;display:flex;flex-direction:column;align-items:center;justify-content:center;line-height:1.15;font-size:15px}} .tile b{{font-weight:600}}
.card{{border:1px solid #E2E8F0;border-radius:10px;padding:16px 20px;min-width:230px;background:#F8FAFB}} .card p{{margin:0 0 8px;font-weight:600;font-size:16px}}
.card ul{{list-style:none;margin:0;padding:0}} .card li{{display:flex;align-items:center;gap:10px;font-size:15px;color:#374151;margin:5px 0}} .card i{{display:inline-block;width:18px;height:18px;border-radius:4px}}
.note{{font-size:13px;color:#6B7280;margin:10px 0 0}} .src{{font-size:13px;color:#6B7280;margin:0}} .foot{{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;margin-top:14px}} .foot img{{height:26px;width:auto;opacity:0.9}}
</style></head><body><div class="wrap">
<h2>{args.title}</h2>
<p class="sub">{args.subtitle}</p>
<div class="row"><div class="grid">{tiles}</div>
<div class="card"><p>{args.us}</p><ul>{legend}</ul><p class="note">{args.note}</p></div></div>
<div class="foot"><p class="src">{args.source}</p>{logo}</div>
</div></body></html>"""
htmlp = pathlib.Path(out).with_suffix(".html"); htmlp.write_text(html)
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1440, "height": 720}, device_scale_factor=2)
    pg.goto(f"file://{htmlp.resolve()}"); pg.wait_for_load_state("networkidle"); pg.wait_for_timeout(700)
    pg.locator(".wrap").screenshot(path=out); b.close()
print("wrote", out)
