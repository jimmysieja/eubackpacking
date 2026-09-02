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

import html
import shutil
import argparse
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

MODE_LABEL = {"train": "Train", "bus": "Bus", "ferry": "Ferry", "flight": "Flight",
              "car": "Car", "bike": "Bike", "walk": "Walk"}

PALETTE = {
    "light": {
        "bg": "#faf9f6", "card": "#ffffff", "ink": "#1d1c1a", "muted": "#726d64",
        "line": "#e4e0d8", "accent": "#2f6f4f", "track": "#efece5",
        "m-train": "#2f6f4f", "m-bus": "#c17d3c", "m-ferry": "#3c8ba0",
        "m-flight": "#4f63a8", "m-car": "#9a5a4a", "m-bike": "#5f8a6a", "m-walk": "#8a8276",
        "cat-lodging": "#3f6fa5", "cat-food": "#c17d3c", "cat-transport": "#2f6f4f",
        "cat-shopping": "#8f5a9a", "cat-activities": "#c05a5a", "cat-gifts": "#3c8ba0",
        "cat-misc": "#8a8276",
    },
    "dark": {
        "bg": "#14140f", "card": "#1e1e18", "ink": "#ece7dc", "muted": "#9a9488",
        "line": "#33322b", "accent": "#5faa80", "track": "#26261f",
        "m-train": "#5faa80", "m-bus": "#e0a061", "m-ferry": "#5fb6cc",
        "m-flight": "#8a9ae0", "m-car": "#d08a78", "m-bike": "#8fc09c", "m-walk": "#b6afa0",
        "cat-lodging": "#78a6d8", "cat-food": "#e0a061", "cat-transport": "#5faa80",
        "cat-shopping": "#c08fc6", "cat-activities": "#e08a8a", "cat-gifts": "#5fb6cc",
        "cat-misc": "#b6afa0",
    },
}


def esc(x) -> str:
    return html.escape(str(x), quote=True)


def fmt(n, nd=0) -> str:
    if n is None or (isinstance(n, float) and np.isnan(n)):
        return "–"
    return f"{n:,.{nd}f}" if nd else f"{round(n):,}"


def cvar(prefix: str, key: str) -> str:
    name = f"{prefix}-{key}"
    return name if name in PALETTE["light"] else f"{prefix}-misc" if prefix == "cat" else "accent"


# --------------------------------------------------------------------------- #
# generic horizontal bar chart
# --------------------------------------------------------------------------- #
def bar_h(rows, *, unit="", vfmt=lambda v: fmt(v), width=640, row_h=30,
          pad_l=140, title="") -> str:
    rows = [r for r in rows if r[1] and r[1] == r[1]]
    if not rows:
        return ""
    vmax = max(v for _, v, _ in rows) or 1
    pad_t = 26 if title else 8
    pad_r = 92
    h = pad_t + len(rows) * row_h + 8
    bar_w = width - pad_l - pad_r
    out = [f'<svg viewBox="0 0 {width} {h}" width="100%" role="img" '
           f'aria-label="{esc(title or "bar chart")}">']
    if title:
        out.append(f'<text x="0" y="15" class="ct">{esc(title)}</text>')
    for i, (label, val, col) in enumerate(rows):
        y = pad_t + i * row_h
        w = max(2, bar_w * val / vmax)
        out.append(
            f'<text x="{pad_l-10}" y="{y+row_h/2+4}" class="cl" text-anchor="end">{esc(label)}</text>'
            f'<rect x="{pad_l}" y="{y+4}" width="{bar_w}" height="{row_h-12}" rx="3" fill="var(--track)"/>'
            f'<rect x="{pad_l}" y="{y+4}" width="{w:.1f}" height="{row_h-12}" rx="3" fill="var(--{col})"/>'
            f'<text x="{pad_l+w+8:.1f}" y="{y+row_h/2+4}" class="cv">{esc(vfmt(val))}{esc(unit)}</text>'
        )
    out.append("</svg>")
    return "".join(out)


# --------------------------------------------------------------------------- #
# route map — equirectangular scatter of stops in order (home excluded)
# --------------------------------------------------------------------------- #
def route_svg(d: dict, width: int = 640, height: int = 460) -> str:
    s = d["stops"]
    if s.empty:
        return ""
    s = s[(~s["is_home"]) & s["arrival_date"].notna() & s["lat"].notna()]
    s = s.sort_values(["trip", "stop_number"])
    if s.empty:
        return ""
    pad = 30
    la, lo = s["lat"].to_numpy(), s["lon"].to_numpy()
    la0, la1 = la.min() - 1.5, la.max() + 1.5
    lo0, lo1 = lo.min() - 1.5, lo.max() + 1.5
    sx = lambda v: pad + (width - 2 * pad) * (v - lo0) / (lo1 - lo0 or 1)
    sy = lambda v: pad + (height - 2 * pad) * (1 - (v - la0) / (la1 - la0 or 1))
    recs = s.to_dict("records")
    pts = [(sx(r["lon"]), sy(r["lat"])) for r in recs]

    segs = []
    for i in range(len(recs) - 1):
        if recs[i]["trip"] != recs[i + 1]["trip"]:
            continue
        (x1, y1), (x2, y2) = pts[i], pts[i + 1]
        segs.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                    f'stroke="var(--accent)" stroke-width="1.3" stroke-dasharray="4 3" opacity="0.65"/>')
    dots, labelled = [], set()
    for (x, y), r in zip(pts, recs):
        slept = (r["nights"] or 0) > 0
        rad = 4.5 if slept else 2.6
        tip = f" — {int(r['nights'])} nights" if slept else " — day trip"
        dots.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{rad}" fill="var(--accent)" '
            f'stroke="var(--card)" stroke-width="1.3">'
            f'<title>{esc(r["city"])}, {esc(r["country"])}{tip}</title></circle>'
        )
        if slept and r["city"] not in labelled:
            labelled.add(r["city"])
            dots.append(f'<text x="{x+7:.1f}" y="{y+3:.1f}" class="cs">{esc(r["city"])}</text>')
    return (f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
            f'aria-label="Route map">{"".join(segs)}{"".join(dots)}</svg>')


def costperday_svg(d: dict, width: int = 420, height: int = 230) -> str:
    sp, trips = A.spend_summary(d), d["trips"]
    rows = [(trips.loc[t, "name"], sp["cost_per_day"].get(t, 0.0), sp["complete"].get(t, False))
            for t in trips.index if sp["by_trip"].get(t, 0) > 0]
    if not rows:
        return ""
    vmax = max(r[1] for r in rows) * 1.3 or 1
    gap = (width - 80) / len(rows)
    bw = gap * 0.5
    base = height - 40
    out = [f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="Cost per day">']
    for i, (name, v, complete) in enumerate(rows):
        x = 50 + gap * i + (gap - bw) / 2
        bh = (base - 20) * v / vmax
        out.append(
            f'<rect x="{x:.1f}" y="{base-bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="4" fill="var(--accent)"/>'
            f'<text x="{x+bw/2:.1f}" y="{base-bh-8:.1f}" class="cv" text-anchor="middle">${v:,.0f}{"" if complete else "*"}</text>'
            f'<text x="{x+bw/2:.1f}" y="{base+18:.1f}" class="cl" text-anchor="middle">{esc(name)}</text>'
        )
    out.append(f'<line x1="40" y1="{base}" x2="{width-20}" y2="{base}" stroke="var(--line)"/></svg>')
    return "".join(out)


# --------------------------------------------------------------------------- #
# sections
# --------------------------------------------------------------------------- #
def stat_tiles(d: dict) -> str:
    ov, sp, ts = A.overview(d), A.spend_summary(d), A.train_stats(d)
    tiles = [
        (fmt(ov["n_countries"]), "countries"),
        (fmt(ov["n_cities"]), "cities slept in"),
        (fmt(ov["nights_logged"]), "nights"),
    ]
    if ts.get("has_data"):
        approx = "" if not ts.get("estimated", True) else "~"
        tiles.append((f"{approx}{fmt(ts['rail_hours'])} h", "on trains"))
        tiles.append((fmt(ts["rail_legs"]), "trains" if not ts.get("estimated", True) else "train legs"))
    if sp["total"] > 0:
        tiles.append((f"${fmt(sp['total'])}", "logged spend" + (" *" if sp["any_partial"] else "")))
    cells = "".join(f'<div class="tile"><div class="tn">{v}</div><div class="tl">{esc(l)}</div></div>'
                    for v, l in tiles)
    return f'<div class="tiles">{cells}</div>'


def trains_section(d: dict) -> str:
    ts = A.train_stats(d)
    if not ts.get("has_data"):
        return ""
    mb = A.mode_breakdown(d)
    rows = [(MODE_LABEL.get(m, m.title()), r["hours"], cvar("m", m))
            for m, r in mb.iterrows() if r["hours"] > 0]
    chart = bar_h(rows, unit=" h", vfmt=lambda v: fmt(v, 1), title="Hours by transport mode")
    real = not ts.get("estimated", True)
    approx = "" if real else "~"
    lg = ts.get("longest")
    if lg:
        km = f' ({fmt(lg["km"])} km)' if lg.get("km") else ""
        longest = (f'<li>Longest ride <b>{esc(lg["from"])} → {esc(lg["to"])}</b> '
                   f'{approx}{lg["hr"]:.1f} h{km}</li>')
    else:
        longest = ""
    sub = (f"that's <b>{ts['full_days_equiv']:.1f} full days</b> sitting on a train — "
           f"straight from the Eurail app's trip stats"
           if real else
           f"roughly <b>{ts['full_days_equiv']:.1f} full days</b> on a train — "
           f"estimated from the distance of each route, not a stopwatch")
    return f"""
<section>
  <h2>🚆 Time on trains</h2>
  <div class="hero">
    <div class="hero-n">{approx}{fmt(ts['rail_hours'])}<span>hours</span></div>
    <div class="hero-sub">{sub}</div>
  </div>
  <ul class="facts">
    <li><b>{ts['rail_legs']}</b> {"separate trains" if real else "train legs"}</li>
    <li><b>{fmt(ts['rail_km'])}</b> km by rail</li>
    <li><b>{ts['rail_hour_share']*100:.0f}%</b> of all travel time</li>
    <li><b>{ts['countries_by_train']}</b> countries by rail</li>
    {longest}
  </ul>
  {chart}
</section>"""


def mode_section(d: dict) -> str:
    mb = A.mode_breakdown(d)
    if mb.empty:
        return ""
    body = "".join(
        f"<tr><td>{esc(MODE_LABEL.get(m, m.title()))}</td>"
        f"<td class='r'>{int(r['legs'])}</td>"
        f"<td class='r'>{'' if not r['estimated'] else '~'}{fmt(r['hours'],1)}</td>"
        f"<td class='r'>{fmt(r['km'])}</td></tr>"
        for m, r in mb.iterrows()
    )
    any_est = mb["estimated"].any()
    note = ("<p class=\"note\">Train row is from the Eurail app. Other modes: hours and "
            "distances estimated from great-circle route length.</p>" if any_est else "")
    return f"""
<section>
  <h2>Every leg, by mode</h2>
  <table>
    <thead><tr><th>Mode</th><th class="r">Legs</th><th class="r">Hours</th>
    <th class="r">km</th></tr></thead>
    <tbody>{body}</tbody>
  </table>
  {note}
</section>"""


def spend_section(d: dict) -> str:
    sp = A.spend_summary(d)
    if d["expenses"].empty:
        return ""
    cat_chart = bar_h([(c.title(), v, cvar("cat", c)) for c, v in sp["by_category"].items()],
                      vfmt=lambda v: f"${fmt(v)}", title="Spend by category")
    ctry_chart = bar_h([(c, v, "m-train") for c, v in sp["by_country"].head(12).items()],
                       vfmt=lambda v: f"${fmt(v)}", title="Spend by country (top 12)")
    facts = []
    if sp.get("priciest_day"):
        facts.append(f"<li>Priciest day <b>${fmt(sp['priciest_day'][1])}</b> "
                     f"({sp['priciest_day'][0]:%d %b})</li>")
    if sp.get("cheapest_day"):
        facts.append(f"<li>Cheapest day <b>${fmt(sp['cheapest_day'][1])}</b> "
                     f"({sp['cheapest_day'][0]:%d %b})</li>")
    if sp.get("mean_day"):
        facts.append(f"<li>Average <b>${fmt(sp['mean_day'])}</b> / day spent</li>")
    facts.append(f"<li><b>{sp['tgtg_count']}</b> Too Good To Go bags</li>")
    note = ('<p class="note">* Summer 2025 expenses are only partly logged — that trip and the '
            'combined total are a floor, not a final number.</p>' if sp["any_partial"] else "")
    return f"""
<section>
  <h2>Money</h2>
  <div class="grid2"><div>{cat_chart}</div><div>{ctry_chart}</div></div>
  <div class="grid2">
    <div><h3>Cost per day</h3>{costperday_svg(d)}</div>
    <div><h3>Odds &amp; ends</h3><ul class="facts">{"".join(facts)}</ul></div>
  </div>
  {note}
</section>"""


def route_section(d: dict) -> str:
    svg = route_svg(d)
    if not svg:
        return ""
    dt_ = A.day_trips(d)
    extra = ""
    if not dt_.empty:
        names = ", ".join(sorted(dt_["city"].unique()))
        extra = f'<p class="note">Day trips (no overnight): {esc(names)}.</p>'
    return f"""
<section>
  <h2>The route</h2>
  {svg}
  <p class="note">Every stop in order. Big dots = slept there; small dots = passed through.
  The two trips aren't joined.</p>
  {extra}
</section>"""


def stops_section(d: dict) -> str:
    sl = A.sleeps(d)
    if sl.empty:
        return ""
    names = {t: r["name"] for t, r in d["trips"].iterrows()}
    body = "".join(
        f"<tr><td>{esc(r['city'])}</td><td>{esc(r['country'])}</td>"
        f"<td>{esc(names.get(r['trip'], r['trip']))}</td>"
        f"<td class='r'>{r['arrival_date']:%d %b %Y}</td>"
        f"<td class='r'>{int(r['nights'])}</td>"
        f"<td>{esc(MODE_LABEL.get(r['transport'], r['transport'] or '—'))}</td></tr>"
        for _, r in sl.sort_values(["trip", "arrival_date"]).iterrows()
    )
    return f"""
<section>
  <h2>Every place I slept ({len(sl)})</h2>
  <div class="tablewrap"><table>
    <thead><tr><th>City</th><th>Country</th><th>Trip</th><th class="r">Arrived</th>
    <th class="r">Nights</th><th>Arrived by</th></tr></thead>
    <tbody>{body}</tbody>
  </table></div>
</section>"""


def gallery_section(d: dict) -> str:
    cap = PHOTOS / "captions.yml"
    entries = yaml.safe_load(cap.read_text(encoding="utf-8")) if cap.is_file() else None
    entries = [e for e in (entries or []) if isinstance(e, dict) and e.get("file")
               and (PHOTOS / e["file"]).is_file()]
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
        for e in entries)
    return f'<section><h2>Photos ({len(entries)})</h2><div class="gallery">{cells}</div></section>'


# --------------------------------------------------------------------------- #
# page
# --------------------------------------------------------------------------- #
def _css() -> str:
    def block(theme, sel):
        return sel + "{" + ";".join(f"--{k}:{v}" for k, v in PALETTE[theme].items()) + "}"
    return f"""
{block('light', ':root')}
@media (prefers-color-scheme: dark) {{ {block('dark', ':root')} }}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}}
.wrap{{max-width:860px;margin:0 auto;padding:40px 20px 80px}}
header h1{{font-size:27px;margin:0 0 4px}}
header p{{color:var(--muted);margin:0 0 8px}}
section{{margin:44px 0;padding-top:8px;border-top:1px solid var(--line)}}
h2{{font-size:20px;margin:20px 0 14px}}
h3{{font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin:0 0 8px}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:12px;margin-top:20px}}
.tile{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}}
.tn{{font-size:21px;font-weight:650}}
.tl{{color:var(--muted);font-size:12.5px;margin-top:2px}}
.hero{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:22px;margin:8px 0 14px}}
.hero-n{{font-size:50px;font-weight:700;line-height:1;color:var(--accent)}}
.hero-n span{{font-size:18px;font-weight:500;color:var(--muted);margin-left:8px}}
.hero-sub{{color:var(--muted);margin-top:8px;max-width:52ch}}
ul.facts{{list-style:none;padding:0;margin:0 0 16px;display:grid;
  grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:2px 18px}}
ul.facts li{{padding:4px 0;border-bottom:1px dotted var(--line)}}
table{{border-collapse:collapse;width:100%;font-size:13.5px}}
th,td{{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line)}}
th{{color:var(--muted);font-weight:600}}
td.r,th.r{{text-align:right;font-variant-numeric:tabular-nums}}
.tablewrap{{overflow-x:auto;max-height:520px;overflow-y:auto}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:24px}}
@media (max-width:640px){{.grid2{{grid-template-columns:1fr}}}}
.gallery{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px}}
figure{{margin:0}} figure img{{width:100%;border-radius:8px;display:block;background:var(--track)}}
figcaption{{color:var(--muted);font-size:12.5px;margin-top:5px}}
.note{{color:var(--muted);font-size:12.5px}}
.ct{{fill:var(--muted);font-size:12px;font-weight:600}}
.cl{{fill:var(--ink);font-size:12px}}
.cs{{fill:var(--muted);font-size:10.5px}}
.cv{{fill:var(--muted);font-size:11.5px;font-variant-numeric:tabular-nums}}
footer{{color:var(--muted);font-size:12px;margin-top:60px}}
a{{color:var(--accent)}}
"""


def build_html(d: dict) -> str:
    ov = A.overview(d)
    gen = d["generated"].strftime("%d %b %Y")
    body = "".join([trains_section(d), mode_section(d), route_section(d),
                    spend_section(d), stops_section(d), gallery_section(d)])
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>A gap year around Europe, in numbers</title>
<style>{_css()}</style>
</head><body><div class="wrap">
<header>
  <h1>A gap year around Europe, in numbers</h1>
  <p>Two backpacking trips — {ov['first_day']:%b %Y} and {ov['last_day']:%b %Y}.
     {ov['n_countries']} countries, {ov['n_cities']} cities, a great deal of rail.</p>
</header>
{stat_tiles(d)}
{body}
<footer>Built from flat files in
<a href="https://github.com/jimmysieja/eubackpacking">jimmysieja/eubackpacking</a>.
Generated {gen}. Trip-1 data still being entered.</footer>
</div></body></html>"""


# --------------------------------------------------------------------------- #
# README assets
# --------------------------------------------------------------------------- #
def _standalone(inner_svg: str, theme: str) -> str:
    p = PALETTE[theme]
    vars_css = ";".join(f"--{k}:{v}" for k, v in p.items())
    style = (f'<style>svg{{background:{p["card"]};border-radius:10px}}'
             f':root{{{vars_css}}} text{{font-family:-apple-system,Segoe UI,Roboto,sans-serif}}'
             f'.ct{{fill:{p["muted"]};font-size:12px;font-weight:600}}'
             f'.cl{{fill:{p["ink"]};font-size:12px}} .cs{{fill:{p["muted"]};font-size:10.5px}}'
             f'.cv{{fill:{p["muted"]};font-size:11.5px}}</style>')
    return inner_svg.replace(">", ">" + style, 1)


def _chart_set(d: dict) -> dict:
    mb, sp = A.mode_breakdown(d), A.spend_summary(d)
    charts = {}
    if not mb.empty:
        charts["trains"] = bar_h(
            [(MODE_LABEL.get(m, m.title()), r["hours"], cvar("m", m))
             for m, r in mb.iterrows() if r["hours"] > 0],
            unit=" h", vfmt=lambda v: fmt(v, 1), title="Estimated hours by transport mode")
    if not d["expenses"].empty:
        charts["spend-category"] = bar_h(
            [(c.title(), v, cvar("cat", c)) for c, v in sp["by_category"].items()],
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
            (out / f"{name}-{theme}.svg").write_text(_standalone(svg, theme), encoding="utf-8")
            written.append(f"{name}-{theme}.svg")
    return written


def write_docs(d: dict) -> None:
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--assets", action="store_true", help="also rewrite assets/*.svg")
    args = ap.parse_args()

    d = A.load_all()
    write_docs(d)
    print(f"wrote {DOCS/'index.html'}")
    if args.assets:
        print(f"wrote {len(export_assets(d))} svgs to assets/")
    if not args.no_open:
        webbrowser.open((DOCS / "index.html").as_uri())


if __name__ == "__main__":
    main()
