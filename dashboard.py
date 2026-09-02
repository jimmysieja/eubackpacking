"""
eubackpacking — dashboard renderer.

Turns the numbers from ``analytics.py`` into one self-contained
``docs/index.html`` (inline CSS, hand-built SVG, no external requests) plus the
light/dark ``assets/*.svg`` files the README embeds.

    python dashboard.py                 # build docs/index.html and open it
    python dashboard.py --no-open       # just build the file
    python dashboard.py --assets        # also (re)write assets/*.svg

Re-run whenever you change anything in ``data/`` or ``photos/``.
"""

from __future__ import annotations

import sys
import html
import shutil
import argparse
import datetime as dt
import webbrowser
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

import analytics as A

ROOT = Path(__file__).parent
DOCS = ROOT / "docs"
ASSETS = ROOT / "assets"
PHOTOS = ROOT / "photos"

MODE_LABEL = {
    "train": "Train", "bus": "Bus", "flight": "Flight", "ferry": "Ferry",
    "tram": "Tram", "metro": "Metro", "car": "Car", "bike": "Bike",
    "walk": "Walk", "other": "Other",
}

# concrete palettes — the HTML page flips between them with a media query, the
# standalone SVG assets get one baked in.
PALETTE = {
    "light": {
        "bg": "#faf9f6", "card": "#ffffff", "ink": "#1d1c1a", "muted": "#726d64",
        "line": "#e4e0d8", "accent": "#2f6f4f", "track": "#efece5",
        "m-train": "#2f6f4f", "m-bus": "#c17d3c", "m-flight": "#4f63a8",
        "m-ferry": "#3c8ba0", "m-tram": "#7f8f45", "m-metro": "#8f6394",
        "m-car": "#9a5a4a", "m-bike": "#5f8a6a", "m-walk": "#8a8276", "m-other": "#aea79b",
        "cat-lodging": "#3f6fa5", "cat-food": "#c17d3c", "cat-transport": "#2f6f4f",
        "cat-activities": "#8f5a9a", "cat-shopping": "#c05a5a", "cat-other": "#8a8276",
    },
    "dark": {
        "bg": "#14140f", "card": "#1e1e18", "ink": "#ece7dc", "muted": "#9a9488",
        "line": "#33322b", "accent": "#5faa80", "track": "#26261f",
        "m-train": "#5faa80", "m-bus": "#e0a061", "m-flight": "#8a9ae0",
        "m-ferry": "#5fb6cc", "m-tram": "#b6c66f", "m-metro": "#c08fc6",
        "m-car": "#d08a78", "m-bike": "#8fc09c", "m-walk": "#b6afa0", "m-other": "#7d766a",
        "cat-lodging": "#78a6d8", "cat-food": "#e0a061", "cat-transport": "#5faa80",
        "cat-activities": "#c08fc6", "cat-shopping": "#e08a8a", "cat-other": "#b6afa0",
    },
}


def esc(x) -> str:
    return html.escape(str(x), quote=True)


def fmt(n, nd=0) -> str:
    if n is None or (isinstance(n, float) and (np.isnan(n))):
        return "–"
    return f"{n:,.{nd}f}" if nd else f"{round(n):,}"


# --------------------------------------------------------------------------- #
# generic horizontal bar chart  (label | bar | value)
# --------------------------------------------------------------------------- #
def bar_h(rows: list[tuple[str, float, str]], *, unit: str = "", vfmt=lambda v: fmt(v),
          width: int = 640, row_h: int = 30, pad_l: int = 132, title: str = "") -> str:
    """rows = [(label, value, css_var_for_colour), ...]"""
    rows = [r for r in rows if r[1] and r[1] == r[1]]
    if not rows:
        return ""
    vmax = max(v for _, v, _ in rows) or 1
    pad_t = 26 if title else 8
    pad_r, bar_max = 88, 0
    h = pad_t + len(rows) * row_h + 8
    bar_w = width - pad_l - pad_r
    out = [f'<svg viewBox="0 0 {width} {h}" width="100%" role="img" '
           f'aria-label="{esc(title or "bar chart")}">']
    if title:
        out.append(f'<text x="0" y="16" class="ct">{esc(title)}</text>')
    for i, (label, val, cvar) in enumerate(rows):
        y = pad_t + i * row_h
        w = max(2, bar_w * val / vmax)
        out.append(
            f'<text x="{pad_l-10}" y="{y+row_h/2+4}" class="cl" text-anchor="end">{esc(label)}</text>'
            f'<rect x="{pad_l}" y="{y+4}" width="{bar_w}" height="{row_h-12}" rx="3" fill="var(--track)"/>'
            f'<rect x="{pad_l}" y="{y+4}" width="{w:.1f}" height="{row_h-12}" rx="3" fill="var(--{cvar})"/>'
            f'<text x="{pad_l+w+8:.1f}" y="{y+row_h/2+4}" class="cv">{esc(vfmt(val))}{esc(unit)}</text>'
        )
    out.append("</svg>")
    return "".join(out)


# --------------------------------------------------------------------------- #
# route map — equirectangular scatter of cities in visit order
# --------------------------------------------------------------------------- #
def route_svg(d: dict, trip_id: str | None = None, width: int = 640, height: int = 420) -> str:
    cities = d["cities"]
    if cities.empty or cities["lat"].dropna().empty:
        return ""
    sub = cities if trip_id is None else cities[cities["trip"] == trip_id]
    sub = sub.dropna(subset=["lat", "lon"]).reset_index(drop=True)
    if sub.empty:
        return ""
    pad = 28
    la, lo = sub["lat"].to_numpy(), sub["lon"].to_numpy()
    la0, la1 = la.min() - 1.5, la.max() + 1.5
    lo0, lo1 = lo.min() - 1.5, lo.max() + 1.5
    sx = lambda v: pad + (width - 2 * pad) * (v - lo0) / (lo1 - lo0 or 1)
    sy = lambda v: pad + (height - 2 * pad) * (1 - (v - la0) / (la1 - la0 or 1))
    pts = list(zip([sx(v) for v in lo], [sy(v) for v in la]))
    trips_seq = sub["trip"].tolist()
    segs = []
    for i in range(len(pts) - 1):
        if trips_seq[i] != trips_seq[i + 1]:
            continue  # don't draw the hop between two separate trips
        (x1, y1), (x2, y2) = pts[i], pts[i + 1]
        segs.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                    f'stroke="var(--accent)" stroke-width="1.4" stroke-dasharray="4 3" opacity="0.7"/>')
    dots = []
    for (x, y), (_, r) in zip(pts, sub.iterrows()):
        dots.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="var(--accent)" stroke="var(--card)" stroke-width="1.5">'
            f'<title>{esc(r["city"])}, {esc(r["country"])} — {int(r["nights"])} nights</title></circle>'
            f'<text x="{x+7:.1f}" y="{y+3:.1f}" class="cl">{esc(r["city"])}</text>'
        )
    return (f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
            f'aria-label="Route map">{"".join(segs)}{"".join(dots)}</svg>')


# --------------------------------------------------------------------------- #
# cost per day — one bar per trip
# --------------------------------------------------------------------------- #
def costperday_svg(d: dict, width: int = 420, height: int = 240) -> str:
    sp = A.spend_summary(d)
    trips = d["trips"]
    rows = [(trips.loc[t, "name"], sp["cost_per_day"].get(t, 0.0), sp["complete"].get(t, False))
            for t in trips.index]
    rows = [r for r in rows if r[1] > 0]
    if not rows:
        return ""
    vmax = max(r[1] for r in rows) * 1.25 or 1
    n = len(rows)
    bw = (width - 80) / n * 0.5
    gap = (width - 80) / n
    out = [f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="Cost per day by trip">']
    base = height - 40
    for i, (name, v, complete) in enumerate(rows):
        x = 50 + gap * i + (gap - bw) / 2
        bh = (base - 20) * v / vmax
        out.append(
            f'<rect x="{x:.1f}" y="{base-bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="4" fill="var(--accent)"/>'
            f'<text x="{x+bw/2:.1f}" y="{base-bh-8:.1f}" class="cv" text-anchor="middle">${v:,.0f}{"" if complete else "*"}</text>'
            f'<text x="{x+bw/2:.1f}" y="{base+18:.1f}" class="cl" text-anchor="middle">{esc(name)}</text>'
        )
    out.append(f'<line x1="40" y1="{base}" x2="{width-20}" y2="{base}" stroke="var(--line)"/>')
    out.append("</svg>")
    return "".join(out)


# --------------------------------------------------------------------------- #
# section builders (HTML)
# --------------------------------------------------------------------------- #
def stat_tiles(d: dict) -> str:
    ov, sp, ts = A.overview(d), A.spend_summary(d), A.train_stats(d)
    tiles = [
        (fmt(ov["n_countries"]), "countries"),
        (fmt(ov["n_cities"]), "cities"),
        (fmt(ov["trip_days"]), "days on the road"),
        (fmt(ov["nights_logged"]), "nights logged"),
        (f"${fmt(sp['total'])}", "spend logged" + (" *" if sp["any_partial"] else "")),
    ]
    if ts.get("has_data"):
        tiles.append((f"{fmt(ts['rail_hours'])} h", "on trains"))
    cells = "".join(
        f'<div class="tile"><div class="tn">{v}</div><div class="tl">{esc(l)}</div></div>'
        for v, l in tiles
    )
    return f'<div class="tiles">{cells}</div>'


def trains_section(d: dict) -> str:
    ts = A.train_stats(d)
    if not ts.get("has_data"):
        return ""
    mb = A.mode_breakdown(d)
    hours_rows = [(MODE_LABEL.get(m, m.title()), r["hours"], f"m-{m}" if f"m-{m}" in PALETTE["light"] else "m-other")
                  for m, r in mb.iterrows() if r["hours"] > 0]
    chart = bar_h(hours_rows, unit=" h", vfmt=lambda v: fmt(v, 1), title="Hours by transport mode")
    lg = ts.get("longest")
    longest_line = (f'<li>Longest single ride <b>{esc(lg["from"])} → {esc(lg["to"])}</b>, '
                    f'{lg["hr"]:.1f} h</li>') if lg else ""
    return f"""
<section>
  <h2>🚆 Time on trains</h2>
  <div class="hero">
    <div class="hero-n">{fmt(ts['rail_hours'])}<span>hours</span></div>
    <div class="hero-sub">≈ {ts['full_days_equiv']:.1f} full days sitting on a train</div>
  </div>
  <ul class="facts">
    <li><b>{ts['rail_journeys']}</b> intercity train journeys</li>
    <li><b>{fmt(ts['rail_km'])}</b> km by rail</li>
    <li><b>{ts['rail_hour_share']*100:.0f}%</b> of all logged travel time</li>
    <li>Trains on <b>{ts['rail_days']}</b> separate days</li>
    {longest_line}
  </ul>
  {chart}
</section>"""


def mode_section(d: dict) -> str:
    mb = A.mode_breakdown(d)
    if mb.empty:
        return ""
    body = "".join(
        f"<tr><td>{esc(MODE_LABEL.get(m, m.title()))}</td>"
        f"<td class='r'>{int(r['journeys'])}</td>"
        f"<td class='r'>{fmt(r['hours'],1)}</td>"
        f"<td class='r'>{fmt(r['km'])}</td>"
        f"<td class='r'>${fmt(r['cost'])}</td></tr>"
        for m, r in mb.iterrows()
    )
    return f"""
<section>
  <h2>Transport by mode</h2>
  <table>
    <thead><tr><th>Mode</th><th class="r">Journeys</th><th class="r">Hours</th>
    <th class="r">km</th><th class="r">Cost</th></tr></thead>
    <tbody>{body}</tbody>
  </table>
</section>"""


def spend_section(d: dict) -> str:
    sp = A.spend_summary(d)
    if d["expenses"].empty:
        return ""
    cat_rows = [(c.title(), v, f"cat-{c}" if f"cat-{c}" in PALETTE["light"] else "cat-other")
                for c, v in sp["by_category"].items()]
    cat_chart = bar_h(cat_rows, vfmt=lambda v: f"${fmt(v)}", title="Spend by category")
    top_country = sp["by_country"].head(12)
    ctry_rows = [(c, v, "accent") for c, v in top_country.items()]
    ctry_chart = bar_h([(l, v, "m-train") for l, v, _ in ctry_rows],
                       vfmt=lambda v: f"${fmt(v)}", title="Spend by country (top 12)")
    note = ('<p class="note">* Summer 2025 expenses are only partially logged, so its '
            'totals and the combined total are a floor, not a final figure.</p>'
            if sp["any_partial"] else "")
    per_day = costperday_svg(d)
    return f"""
<section>
  <h2>Money</h2>
  <div class="grid2">
    <div>{cat_chart}</div>
    <div>{ctry_chart}</div>
  </div>
  <h3>Cost per day</h3>
  <div class="narrow">{per_day}</div>
  {note}
</section>"""


def route_section(d: dict) -> str:
    svg = route_svg(d)
    if not svg:
        return ""
    return f"""
<section>
  <h2>The route</h2>
  {svg}
  <p class="note">Cities in visit order across both trips. Hover a dot for nights spent.</p>
</section>"""


def cities_section(d: dict) -> str:
    c = d["cities"]
    if c.empty:
        return ""
    names = {t: r["name"] for t, r in d["trips"].iterrows()}
    body = "".join(
        f"<tr><td>{esc(r['city'])}</td><td>{esc(r['country'])}</td>"
        f"<td>{esc(names.get(r['trip'], r['trip']))}</td>"
        f"<td class='r'>{r['arrive']:%d %b %Y}</td>"
        f"<td class='r'>{int(r['nights'])}</td>"
        f"<td>{esc(r['lodging'])}</td><td>{esc(r['notes'])}</td></tr>"
        for _, r in c.iterrows()
    )
    return f"""
<section>
  <h2>Every stop ({len(c)})</h2>
  <div class="tablewrap"><table>
    <thead><tr><th>City</th><th>Country</th><th>Trip</th><th class="r">Arrived</th>
    <th class="r">Nights</th><th>Stay</th><th>Notes</th></tr></thead>
    <tbody>{body}</tbody>
  </table></div>
</section>"""


def gallery_section(d: dict) -> str:
    cap_file = PHOTOS / "captions.yml"
    entries = yaml.safe_load(cap_file.read_text(encoding="utf-8")) if cap_file.is_file() else None
    entries = [e for e in (entries or []) if isinstance(e, dict) and e.get("file")]
    entries = [e for e in entries if (PHOTOS / e["file"]).is_file()]
    if not entries:
        return """
<section>
  <h2>Photos</h2>
  <p class="note">No photos yet. Drop web-sized JPGs into <code>photos/</code>, list them in
  <code>photos/captions.yml</code>, and re-run the build.</p>
</section>"""
    cells = "".join(
        f'<figure><img loading="lazy" src="photos/{esc(e["file"])}" alt="{esc(e.get("caption",""))}">'
        f'<figcaption>{esc(e.get("caption",""))}'
        f'{" · " + esc(e["city"]) if e.get("city") else ""}</figcaption></figure>'
        for e in entries
    )
    return f'<section><h2>Photos ({len(entries)})</h2><div class="gallery">{cells}</div></section>'


# --------------------------------------------------------------------------- #
# page assembly
# --------------------------------------------------------------------------- #
def _css() -> str:
    def block(theme: str, sel: str) -> str:
        p = PALETTE[theme]
        return sel + "{" + ";".join(f"--{k}:{v}" for k, v in p.items()) + "}"
    return f"""
{block('light', ':root')}
@media (prefers-color-scheme: dark) {{ {block('dark', ':root')} }}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}}
.wrap{{max-width:860px;margin:0 auto;padding:40px 20px 80px}}
header h1{{font-size:28px;margin:0 0 4px}}
header p{{color:var(--muted);margin:0 0 8px}}
section{{margin:44px 0;padding-top:8px;border-top:1px solid var(--line)}}
h2{{font-size:20px;margin:20px 0 14px}}
h3{{font-size:14px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin:0 0 8px}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:12px;margin-top:20px}}
.tile{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}}
.tn{{font-size:22px;font-weight:650}}
.tl{{color:var(--muted);font-size:12.5px;margin-top:2px}}
.hero{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:22px;margin:8px 0 14px}}
.hero-n{{font-size:52px;font-weight:700;line-height:1;color:var(--accent)}}
.hero-n span{{font-size:18px;font-weight:500;color:var(--muted);margin-left:8px}}
.hero-sub{{color:var(--muted);margin-top:6px}}
ul.facts{{list-style:none;padding:0;margin:0 0 16px;display:grid;
  grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:4px 18px}}
ul.facts li{{padding:3px 0;border-bottom:1px dotted var(--line)}}
table{{border-collapse:collapse;width:100%;font-size:13.5px}}
th,td{{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line)}}
th{{color:var(--muted);font-weight:600}}
td.r,th.r{{text-align:right;font-variant-numeric:tabular-nums}}
.tablewrap{{overflow-x:auto}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:24px}}
@media (max-width:640px){{.grid2{{grid-template-columns:1fr}}}}
.narrow{{max-width:420px}}
.gallery{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px}}
figure{{margin:0}}
figure img{{width:100%;border-radius:8px;display:block;background:var(--track)}}
figcaption{{color:var(--muted);font-size:12.5px;margin-top:5px}}
.note{{color:var(--muted);font-size:12.5px}}
.ct{{fill:var(--muted);font-size:12px;font-weight:600}}
.cl{{fill:var(--ink);font-size:12px}}
.cv{{fill:var(--muted);font-size:11.5px;font-variant-numeric:tabular-nums}}
footer{{color:var(--muted);font-size:12px;margin-top:60px}}
a{{color:var(--accent)}}
"""


def build_html(d: dict) -> str:
    ov = A.overview(d)
    gen = d["generated"].strftime("%d %b %Y")
    sections = "".join([
        trains_section(d), mode_section(d), route_section(d),
        spend_section(d), cities_section(d), gallery_section(d),
    ])
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Two months + three months around Europe</title>
<style>{_css()}</style>
</head><body><div class="wrap">
<header>
  <h1>Two months + three months around Europe</h1>
  <p>A gap year in numbers — {ov['first_day']:%b %Y} to {ov['last_day']:%b %Y}.
     {ov['n_countries']} countries, {ov['n_cities']} cities, a lot of trains.</p>
</header>
{stat_tiles(d)}
{sections}
<footer>Built from flat files in
<a href="https://github.com/jimmysieja/eubackpacking">jimmysieja/eubackpacking</a>.
Last generated {gen}. Sample data until the real numbers land.</footer>
</div></body></html>"""


# --------------------------------------------------------------------------- #
# standalone SVG assets for the README
# --------------------------------------------------------------------------- #
def _standalone(inner_svg: str, theme: str) -> str:
    p = PALETTE[theme]
    vars_css = ";".join(f"--{k}:{v}" for k, v in p.items())
    style = (f'<style>svg{{background:{p["card"]};border-radius:10px}}'
             f':root{{{vars_css}}} text{{font-family:-apple-system,Segoe UI,Roboto,sans-serif}}'
             f'.ct{{fill:{p["muted"]};font-size:12px;font-weight:600}}'
             f'.cl{{fill:{p["ink"]};font-size:12px}}'
             f'.cv{{fill:{p["muted"]};font-size:11.5px}}</style>')
    return inner_svg.replace(">", ">" + style, 1)


def _chart_set(d: dict) -> dict:
    mb = A.mode_breakdown(d)
    sp = A.spend_summary(d)
    charts = {}
    if not mb.empty:
        rows = [(MODE_LABEL.get(m, m.title()), r["hours"],
                 f"m-{m}" if f"m-{m}" in PALETTE["light"] else "m-other")
                for m, r in mb.iterrows() if r["hours"] > 0]
        charts["trains"] = bar_h(rows, unit=" h", vfmt=lambda v: fmt(v, 1),
                                 title="Hours by transport mode")
    if not d["expenses"].empty:
        charts["spend-category"] = bar_h(
            [(c.title(), v, f"cat-{c}" if f"cat-{c}" in PALETTE["light"] else "cat-other")
             for c, v in sp["by_category"].items()],
            vfmt=lambda v: f"${fmt(v)}", title="Spend by category")
        charts["spend-country"] = bar_h(
            [(c, v, "m-train") for c, v in sp["by_country"].head(12).items()],
            vfmt=lambda v: f"${fmt(v)}", title="Spend by country (top 12)")
    route = route_svg(d)
    if route:
        charts["route"] = route
    return charts


def export_assets(d: dict, out: Path = ASSETS) -> list[str]:
    out.mkdir(exist_ok=True)
    written = []
    for name, svg in _chart_set(d).items():
        for theme in ("light", "dark"):
            f = out / f"{name}-{theme}.svg"
            f.write_text(_standalone(svg, theme), encoding="utf-8")
            written.append(f.name)
    return written


def write_docs(d: dict) -> None:
    """Regenerate docs/ — the folder GitHub Pages serves."""
    DOCS.mkdir(exist_ok=True)
    (DOCS / "index.html").write_text(build_html(d), encoding="utf-8")
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")

    dst = DOCS / "photos"
    if dst.exists():
        shutil.rmtree(dst)
    imgs = [p for p in PHOTOS.glob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}]
    if imgs:
        dst.mkdir()
        for p in imgs:
            shutil.copy2(p, dst / p.name)


# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--assets", action="store_true", help="also rewrite assets/*.svg")
    args = ap.parse_args()

    d = A.load_all()
    write_docs(d)
    print(f"wrote {DOCS/'index.html'} (+ photos)")

    if args.assets:
        w = export_assets(d)
        print(f"wrote {len(w)} svgs to assets/")

    if not args.no_open:
        webbrowser.open((DOCS / "index.html").as_uri())


if __name__ == "__main__":
    main()
