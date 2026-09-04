"""
eubackpacking — page renderer.

Reads the numbers from ``analytics.py`` and lays them out as one self-contained
editorial page (``docs/index.html``): hand-built SVG, inline CSS, one webfont
request. Also writes the light/dark ``assets/*.svg`` used on the repo page.

    python dashboard.py                 # build docs/index.html and open it
    python dashboard.py --no-open
    python dashboard.py --assets        # also rewrite assets/*.svg
"""

from __future__ import annotations

import os
import math
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
PHOTOS = ROOT / "photos"                 # captions.yml lives here and is committed

# Full-res originals are gitignored and can live outside the repo (e.g. a
# cloud-synced folder). Point EUBP_PHOTO_SRC at them per machine. Without it the
# build looks in photos/, and failing that falls back to the already-published
# copies in docs/photos/ — so caption/date edits still build on a clone that has
# no originals at all.
PHOTO_SRC = (Path(os.environ["EUBP_PHOTO_SRC"]).expanduser()
             if os.environ.get("EUBP_PHOTO_SRC") else PHOTOS)

MODE_LABEL = {"train": "train", "bus": "bus", "ferry": "ferry", "flight": "flight",
              "car": "car", "bike": "bike", "walk": "walk"}
# per-mode line style: (svg-dasharray, relative-weight, opacity, bow-factor)
# kept deliberately distinct so the modes read apart at a glance.
MODE_STYLE = {
    "train":  ("",           1.9, 0.95, 0.10),
    "bus":    ("9 6",        1.4, 0.85, 0.14),
    "ferry":  ("0.1 6",      1.9, 0.80, 0.22),   # round-cap dots
    "flight": ("2 7",        1.3, 0.62, 0.55),   # sparse + big arc
    "car":    ("1 4 7 4",    1.3, 0.85, 0.10),   # dash-dot
    "bike":   ("2 4",        1.2, 0.80, 0.10),
    "walk":   ("0.1 5",      1.4, 0.70, 0.06),
}
MODE_DASH = {m: s[0] for m, s in MODE_STYLE.items()}

# "Field atlas" palette. Single source of truth — the map page reads this too
# (docs/map/palette.json). Change colours here, rerun build, both pages update.
PAL = {
    "light": {
        "paper": "#f3efe6", "ink": "#211d17", "dim": "#6f6a5c", "rule": "#d7d0be",
        "accent": "#7c3b2c", "gold": "#9a7636", "faint": "#c9c1ac", "far": "#e2dbc9",
        # per-trip line/pin colours. trip2 = a light teal, trip1 = a warm cream
        # (a deeper wheat in light mode so it still reads on the cream paper).
        # warm/cool split stays legible for colour-blind eyes. tweak freely.
        "trip1": "#bf9856", "trip2": "#4e9ca2",
        "c0": "#2f5d54", "c1": "#9a7636", "c2": "#7c3b2c", "c3": "#5b4a6f",
        "c4": "#3a6079", "c5": "#7a7d3c", "c6": "#8a8172",
    },
    "dark": {
        "paper": "#17150f", "ink": "#ece5d5", "dim": "#948c7a", "rule": "#332f26",
        "accent": "#cf7359", "gold": "#c8a55f", "faint": "#3d3a2f", "far": "#2c281f",
        "trip1": "#ecdcb1", "trip2": "#8ad2cb",
        "c0": "#5fa093", "c1": "#c8a55f", "c2": "#cf7359", "c3": "#a08fba",
        "c4": "#7ba7c4", "c5": "#b7bb6e", "c6": "#b3aa96",
    },
}
CAT_COLOR = {"lodging": "c0", "food": "c1", "transport": "c2", "shopping": "c3",
             "activities": "c4", "gifts": "c5", "misc": "c6"}

# which palette colour each trip draws in (route trace + interactive map).
TRIP_INK = {"trip1": "trip1", "trip2": "trip2"}
DEFAULT_INK = "accent"

# --- static route-trace map (assets/route-*.svg + the homepage figure) --------
# Non-overnight stops that still earn a label, with the sub-line to show under
# the name. Overnight stops are always labelled (name only).
ROUTE_EXTRA = {
    "Vatican City":    "day trip · 25 Jul",
    "Santa Marinella": "day trip · 27 Jul",
    "Kandersteg":      "day hike · 15 Jul",
    "Mürren":          "day hike · 17 Jul",
    "Monaco-Ville":    "day trip · 6 Jul",
    "Lyon":            "overnight bus · Nice 6 Jul → Annecy 7 Jul",
    "Břeclav":         "passing through · 5 Aug",
    "Ostrava":         "passing through · 6 Aug",
    "Oxford":          "on the way to Liverpool",
    "Galway":          "gateway to Connemara",
    "Naples":          "off the bus, on to Ercolano",
    "Theth":           "day trip from Shkodër",
    "Virpazar":        "Lake Skadar day trip",
}
# hand nudges for labels that would otherwise collide. (dx, dy, anchor);
# anchor is "start" (label right of dot), "end" (left) or "middle".
ROUTE_LABEL_POS = {
    "Liverpool":    (0, -10, "middle"),
    "Manchester":   (7, 12, "start"),
    "Abergavenny":  (-10, 13, "end"),
    "Betws-y-Coed": (-9, -6, "end"),
    "Belfast":      (-8, -4, "end"),
    "Oxford":       (9, 6, "start"),
    "Ercolano":     (10, 11, "start"),
    "Naples":       (-9, 1, "end"),
    "Bari":         (9, 3, "start"),
    "Rome":         (9, 2, "start"),
    "Chamonix":     (9, -2, "start"),
    "Annecy":       (-9, -3, "end"),
    "Zermatt":      (-9, 7, "end"),
    "Interlaken":   (9, -3, "start"),
    "Milan":        (8, 9, "start"),
    "Nice":         (9, 8, "start"),
    "Monaco-Ville": (10, -3, "start"),
    "Marseille":    (-9, 6, "end"),
    "Bled":         (-9, -3, "end"),
    "Ljubljana":    (8, 9, "start"),
    "Vienna":       (8, -3, "start"),
    "Bratislava":   (8, 10, "start"),
    "Zagreb":       (8, 6, "start"),
    "Sarajevo":     (9, 6, "start"),
    "Mostar":       (-9, 4, "end"),
}


def esc(x) -> str:
    return html.escape(str(x), quote=True)


def money(v) -> str:
    v = float(v)
    if v >= 10000:
        return f"${v/1000:.0f}k"
    if v >= 1000:
        return f"${v/1000:.1f}k"
    return f"${v:,.0f}"


def fmt(n, nd=0) -> str:
    if n is None or (isinstance(n, float) and np.isnan(n)):
        return "–"
    return f"{n:,.{nd}f}" if nd else f"{round(n):,}"


def hm(hours: float) -> str:
    h = int(hours)
    m = round((hours - h) * 60)
    return f"{h}h{m:02d}m" if m else f"{h}h"


def layover_window(a, b) -> tuple[str, str]:
    """(display window, layover length) for a transit stop, from raw arrive/leave
    timestamps. Same day -> '13:20 – 16:05, 26 Apr'; across midnight ->
    '06 Apr 22:01 – 07 Apr 02:14'."""
    a, b = pd.to_datetime(a), pd.to_datetime(b)
    if a.date() == b.date():
        win = f"{a:%H:%M} – {b:%H:%M}, {a:%d %b}"
    else:
        win = f"{a:%d %b %H:%M} – {b:%d %b %H:%M}"
    return win, hm((b - a).total_seconds() / 3600).rstrip("m")


# --------------------------------------------------------------------------- #
# svg building blocks
# --------------------------------------------------------------------------- #
def _geo_project(lats, lons, w, h, pad, margin=1.4):
    """Equal-scale lon/lat projection with a cos(lat) longitude squeeze, so the
    trace keeps roughly true proportions and letterboxes inside w x h. Returns
    (sx, sy, bbox) with bbox = (lo0, la0, lo1, la1) actually shown."""
    la0, la1 = min(lats) - margin, max(lats) + margin
    lo0, lo1 = min(lons) - margin, max(lons) + margin
    kx = math.cos(math.radians((la0 + la1) / 2))
    gw, gh = (lo1 - lo0) * kx or 1, (la1 - la0) or 1
    scale = min((w - 2 * pad) / gw, (h - 2 * pad) / gh)
    ox = (w - gw * scale) / 2
    oy = (h - gh * scale) / 2
    sx = lambda lon: ox + (lon - lo0) * kx * scale
    sy = lambda lat: oy + (la1 - lat) * scale
    return sx, sy, (lo0, la0, lo1, la1)


def _country_paths(sx, sy, bbox, w, h) -> str:
    """Simplified country outlines from docs/map/europe.geojson, projected and
    clamped to the frame — one thin <path> per ring that touches the view."""
    p = DOCS / "map" / "europe.geojson"
    if not p.is_file():
        return ""
    lo0, la0, lo1, la1 = bbox
    try:
        import json
        gj = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return ""

    def rings(geom):
        t, cs = geom.get("type"), geom.get("coordinates", [])
        if t == "Polygon":
            return cs
        if t == "MultiPolygon":
            return [r for poly in cs for r in poly]
        return []

    m = 6                                     # let borders run just off-frame
    cl = lambda v, hi: min(max(v, -m), hi + m)
    out = []
    for feat in gj.get("features", []):
        for ring in rings(feat.get("geometry", {})):
            if not any(lo0 - 3 <= lon <= lo1 + 3 and la0 - 3 <= lat <= la1 + 3
                       for lon, lat in ring):
                continue
            dd = "".join(f"{'M' if i == 0 else 'L'}{cl(sx(lon), w):.1f} {cl(sy(lat), h):.1f}"
                         for i, (lon, lat) in enumerate(ring))
            out.append(f'<path d="{dd}Z" fill="none" stroke="var(--rule)" '
                       f'stroke-width="0.7" opacity="0.8"/>')
    return "".join(out)


def route_trace(d: dict, w: int = 920, h: int = 760) -> str:
    s = d["stops"]
    if s.empty:
        return ""
    s = s[(~s["is_home"]) & s["arrival_date"].notna() & s["lat"].notna()]
    s = s.sort_values(["trip", "stop_number"])
    if s.empty:
        return ""
    sx, sy, bbox = _geo_project(s["lat"].tolist(), s["lon"].tolist(), w, h, 28)
    trip_ink = {t: TRIP_INK.get(t, DEFAULT_INK) for t in d["trips"].index}
    nights_by_city = s.groupby("city")["nights"].max().to_dict()
    slept_cities = {c for c, n in nights_by_city.items() if pd.notna(n) and n > 0}

    outlines = _country_paths(sx, sy, bbox, w, h)

    seg = []
    for tid, grp in s.groupby("trip"):
        recs = grp.to_dict("records")
        ink = trip_ink.get(tid, "accent")
        for a, b in zip(recs, recs[1:]):
            if a["city"] == b["city"]:
                continue
            mode = b["transport"] or "train"
            dash, wt, op, bow = MODE_STYLE.get(mode, MODE_STYLE["train"])
            x1, y1, x2, y2 = sx(a["lon"]), sy(a["lat"]), sx(b["lon"]), sy(b["lat"])
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            nx, ny = -(y2 - y1), (x2 - x1)
            nl = (nx * nx + ny * ny) ** 0.5 or 1
            k = min(60, ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5 * bow)
            cx, cy = mx + nx / nl * k, my + ny / nl * k
            cap = ' stroke-linecap="round"' if dash.startswith("0.1") else ""
            seg.append(f'<path d="M{x1:.1f} {y1:.1f} Q{cx:.1f} {cy:.1f} {x2:.1f} {y2:.1f}" '
                       f'fill="none" stroke="var(--{ink})" stroke-width="{wt:.2f}"{cap} '
                       f'stroke-dasharray="{dash}" opacity="{op}"/>')

    dots, labels, seen = [], [], set()
    for tid, grp in s.groupby("trip"):
        ink = trip_ink.get(tid, "accent")
        for r in grp.to_dict("records"):
            city = r["city"]
            x, y = sx(r["lon"]), sy(r["lat"])
            big = city in slept_cities
            dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{3.0 if big else 1.7}" '
                        f'fill="var(--{ink})" stroke="var(--paper)" stroke-width="0.8">'
                        f'<title>{esc(city)}</title></circle>')
            if city in seen:
                continue
            note = ROUTE_EXTRA.get(city)
            if not (big or note is not None):
                continue
            seen.add(city)
            dx, dy, anchor = ROUTE_LABEL_POS.get(
                city, (6, 3, "start") if x < w * 0.62 else (-6, 3, "end"))
            tx, ty = x + dx, y + dy
            lead = (f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{tx:.1f}" y2="{ty - 3:.1f}" '
                    f'stroke="var(--rule)" stroke-width="0.7"/>') if abs(dx) > 11 or abs(dy) > 11 else ""
            sub = (f'<tspan x="{tx:.1f}" dy="10" class="tr-sub">{esc(note)}</tspan>'
                   if note else "")
            labels.append(f'{lead}<text x="{tx:.1f}" y="{ty:.1f}" text-anchor="{anchor}" '
                          f'class="tr-city">{esc(city)}{sub}</text>')

    # annotate the longest ride
    ts = A.train_stats(d)
    note = ""
    lg = ts.get("longest")
    if lg:
        row = s[s["city"] == lg["to"]]
        if not row.empty:
            r = row.iloc[0]
            x, y = sx(r["lon"]), sy(r["lat"])
            note = (f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x-60:.1f}" y2="{y+36:.1f}" '
                    f'stroke="var(--dim)" stroke-width="0.8"/>'
                    f'<text x="{x-64:.1f}" y="{y+40:.1f}" text-anchor="end" class="tr-note">'
                    f'{esc(lg["from"])}&#8202;&#8594;&#8202;{esc(lg["to"])} · {hm(lg["hr"])}</text>')

    return (f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="Route trace">'
            f'<rect x="0.5" y="0.5" width="{w-1}" height="{h-1}" fill="none" '
            f'stroke="var(--rule)" stroke-width="1"/>'
            f'{outlines}{"".join(seg)}{"".join(dots)}{"".join(labels)}{note}</svg>')


def _month_ticks(span, sx, y):
    d0, d1 = span
    out = []
    cur = dt.date(d0.year, d0.month, 1)
    while cur <= d1:
        if cur >= d0:
            x = sx(cur)
            out.append(f'<line x1="{x:.1f}" y1="{y-6:.1f}" x2="{x:.1f}" y2="{y:.1f}" '
                       f'stroke="var(--rule)"/>'
                       f'<text x="{x+3:.1f}" y="{y-9:.1f}" class="ax">{cur:%b}</text>')
        m = cur.month % 12 + 1
        cur = dt.date(cur.year + (cur.month == 12), m, 1)
    return "".join(out)


def day_strip(span, columns, *, w=900, h=150, pad_l=8, annos=None, baseline_label="") -> str:
    """columns: list of (date, [(value, colorvar, opacity), ...]) stacked bottom-up."""
    d0, d1 = span
    ndays = (d1 - d0).days + 1
    plot_h = h - 34
    base_y = plot_h + 6
    sx = lambda day: pad_l + (w - pad_l - 8) * ((day - d0).days) / max(1, ndays - 1)
    cw = max(1.4, (w - pad_l - 8) / ndays * 0.7)
    vmax = max((sum(v for v, _, _ in stack) for _, stack in columns), default=1) or 1
    bars = []
    for day, stack in columns:
        x = sx(day) - cw / 2
        yb = base_y
        for val, col, op in stack:
            bh = (plot_h) * val / vmax
            yb -= bh
            bars.append(f'<rect x="{x:.1f}" y="{yb:.1f}" width="{cw:.1f}" height="{bh:.2f}" '
                        f'fill="var(--{col})" opacity="{op}"/>')
    ann = []
    for day, text in (annos or []):
        x = sx(day)
        ann.append(f'<line x1="{x:.1f}" y1="6" x2="{x:.1f}" y2="{base_y:.1f}" '
                   f'stroke="var(--ink)" stroke-width="0.5" stroke-dasharray="1 3"/>'
                   f'<text x="{x+3:.1f}" y="14" class="ax-note">{esc(text)}</text>')
    lbl = (f'<text x="{pad_l}" y="{h-6}" class="ax">{esc(baseline_label)}</text>'
           if baseline_label else "")
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="daily strip">'
            f'{"".join(bars)}'
            f'<line x1="{pad_l}" y1="{base_y:.1f}" x2="{w-8}" y2="{base_y:.1f}" stroke="var(--rule)"/>'
            f'{_month_ticks(span, sx, base_y)}{"".join(ann)}{lbl}</svg>')


def band(rows, *, w=900, h=30) -> str:
    """rows: [(label, value, colorvar, opacity)] -> one proportional bar."""
    rows = [r for r in rows if r[1] and r[1] == r[1]]
    tot = sum(v for _, v, _, _ in rows) or 1
    x = 0
    out = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="proportional band">']
    for label, val, col, op in rows:
        seg = w * val / tot
        out.append(f'<rect x="{x:.1f}" y="0" width="{max(0,seg-1.4):.1f}" height="{h}" '
                   f'fill="var(--{col})" opacity="{op}"><title>{esc(label)}: {esc(money(val))}'
                   f' ({val/tot*100:.0f}%)</title></rect>')
        x += seg
    out.append("</svg>")
    return "".join(out)


# --------------------------------------------------------------------------- #
# page movements
# --------------------------------------------------------------------------- #
def masthead(d: dict) -> str:
    ov = A.overview(d)
    yr = f"{ov['first_day']:%Y}–{ov['last_day']:%y}"
    return f"""
<header>
  <p class="dateline">A gap year &middot; Europe &middot; {yr}</p>
  <h1>A gap year around Europe</h1>
  <p class="dek">Two backpacking trips, Summer 2025 and Spring 2026 &mdash; the route,
  the spending, and the time spent on trains. {ov['n_countries_visited']} countries,
  {ov['n_cities']} cities.</p>
</header>"""


def ledger(d: dict) -> str:
    ov, sp, ts = A.overview(d), A.spend_summary(d), A.train_stats(d)
    sl = A.sleeps(d)
    top_ctry = sl.groupby("country")["nights"].sum().idxmax() if not sl.empty else ""
    perday = sp["total"] / d["trips"].loc["trip2", "days"] if sp["total"] else 0
    items = [
        (fmt(ov["trip_days"]), "days away", "across two trips"),
        (fmt(ov["n_countries_visited"]), "countries", f"most nights in {top_ctry}"),
        (fmt(ts["rail_legs"]), "trains boarded", f"{fmt(ts['rail_km'])} km of track"),
        (f"{ts['rail_hours']:.0f}", "hours in a seat", f"{ts['full_days_equiv']:.1f} full days"),
        (money(sp["total"]), "spent" + (" *" if sp["any_partial"] else ""),
         f"{money(perday)}/day on the road"),
        (fmt(ov["nights_logged"]), "nights logged", "hostels, mostly"),
    ]
    cells = "".join(f'<div class="lg"><div class="lg-n">{v}</div>'
                    f'<div class="lg-l">{esc(l)}</div>'
                    f'<div class="lg-a">{esc(a)}</div></div>' for v, l, a in items)
    return f'<section class="ledger">{cells}</section>'


def trace_movement(d: dict) -> str:
    svg = route_trace(d)
    if not svg:
        return ""
    dt_ = A.day_trips(d)
    extra = (f' Off the line, no bed: {esc(", ".join(sorted(dt_["city"].unique())))}.'
             if not dt_.empty else "")
    return f"""
<section class="movement">
  <p class="tag">Route</p>
  <figure class="trace">{svg}</figure>
  <p class="caption">Every stop in order. Solid = rail, dashed = bus, dotted = ferry,
  hairline = flight. The two trips aren't connected.{extra}
  &nbsp;<a href="map/">Interactive map &rarr;</a></p>
</section>"""


def trains_movement(d: dict) -> str:
    ts = A.train_stats(d)
    if not ts.get("has_data"):
        return ""
    span = A.active_span(d)
    tl = A.transit_by_day(d)
    cols = []
    if span and not tl.empty:
        for day, r in tl.iterrows():
            stack = []
            tr = float(r.get("train", 0))
            if tr > 0:
                stack.append((tr, "accent", 0.9))
            other = float(sum(v for m, v in r.items() if m != "train"))
            if other > 0:
                stack.append((other, "ink", 0.28))
            if stack:
                cols.append((day, stack))
    annos = []
    for o in d.get("rail", {}).values():
        top = sorted(o.get("notable", []), key=lambda j: -j["hours"])[:3]
        for j in top:
            annos.append((pd.to_datetime(j["date"]).date(),
                          f'{j["from"]}→{j["to"]} {hm(j["hours"])}'))
    strip = day_strip(span, cols, annos=annos,
                      baseline_label="hours in transit, by day") if cols else ""
    lg = ts.get("longest")
    longest = (f' Longest single ride: <b>{esc(lg["from"])}&#8202;&#8594;&#8202;{esc(lg["to"])}</b>, '
               f'{hm(lg["hr"])}.') if lg else ""
    ov = [f'{ts["rail_legs"]} trains', f'{fmt(ts["rail_km"])} km',
          f'{ts["countries_by_train"]} countries', f'{ts["rail_hour_share"]*100:.0f}% of all transit']
    if d.get("rail"):
        onn = sum(o.get("overnight", 0) for o in d["rail"].values())
        if onn:
            ov.append(f'{onn} overnight')
    return f"""
<section class="movement">
  <p class="tag">Trains</p>
  <p class="statement"><b>{hm(ts['rail_hours'])} on trains</b> &mdash; about
  {ts['full_days_equiv']:.1f} days.{longest}</p>
  <figure class="strip">{strip}</figure>
  <p class="micro">{' &nbsp;&middot;&nbsp; '.join(esc(x) for x in ov)}</p>
</section>"""


def money_movement(d: dict) -> str:
    sp = A.spend_summary(d)
    if d["expenses"].empty:
        return ""
    cats = list(sp["by_category"].items())
    cat_band = band([(c, v, CAT_COLOR.get(c, "c6"), 0.9) for c, v in cats])
    cat_key = " &nbsp; ".join(
        f'<span class="k"><i style="background:var(--{CAT_COLOR.get(c,"c6")})"></i>'
        f'{esc(c)} {esc(money(v))}</span>' for c, v in cats)

    ctry = sp["by_country"].head(9)
    rest = sp["by_country"].iloc[9:].sum()
    crows = [(c, v, "accent", op) for (c, v), op in
             zip(ctry.items(), np.linspace(0.95, 0.4, len(ctry)))]
    if rest > 0:
        crows.append(("elsewhere", rest, "ink", 0.22))
    ctry_band = band(crows)
    ctry_key = " &nbsp; ".join(f'<span class="k">{esc(c)} {esc(money(v))}</span>'
                               for c, v in list(ctry.items())[:6])

    span = A.active_span(d)
    sbd = A.spend_by_day(d)
    cols, annos = [], []
    if span and not sbd.empty:
        cnames = list(sp["by_country"].head(7).index)
        cmap = {c: f"c{i}" for i, c in enumerate(cnames)}
        for day, r in sbd.iterrows():
            if r["total"] and r["total"] > 0:
                col = cmap.get(r.get("country", ""), "c6")
                cols.append((day, [(float(r["total"]), col, 0.85)]))
        if sp.get("priciest_day"):
            annos.append((sp["priciest_day"][0], f'${sp["priciest_day"][1]:.0f}'))
    strip = day_strip(span, cols, annos=annos, h=136,
                      baseline_label="spend per day, tinted by country") if cols else ""

    top2 = cats[:2]
    lead = (f"{money(sum(v for _, v in top2))}" if top2 else money(sp["total"]))
    lead_txt = " and ".join(c for c, _ in top2) if top2 else "everything"
    perday = sp["total"] / d["trips"].loc["trip2", "days"]
    facts = [f'{money(perday)}/day', f'{sp["tgtg_count"]} Too Good To Go bags']
    if sp.get("priciest_day"):
        facts.append(f'most expensive day {money(sp["priciest_day"][1])} ({sp["priciest_day"][0]:%d %b})')
    if sp.get("cheapest_day"):
        facts.append(f'cheapest {money(sp["cheapest_day"][1])} ({sp["cheapest_day"][0]:%d %b})')
    star = ('<p class="caption">* Summer 2025 isn\'t fully logged yet, so the total is a floor.</p>'
            if sp["any_partial"] else "")
    return f"""
<section class="movement">
  <p class="tag">Money</p>
  <p class="statement"><b>{esc(money(sp['total']))}</b> on the Spring 2026 trip &mdash; {esc(lead)}
  of it {esc(lead_txt)}.</p>
  <figure class="bandfig">{cat_band}<div class="key">{cat_key}</div></figure>
  <figure class="bandfig">{ctry_band}<div class="key">{ctry_key} &nbsp; &hellip;</div></figure>
  <figure class="strip">{strip}</figure>
  <p class="micro">{' &nbsp;&middot;&nbsp; '.join(esc(x) for x in facts)}</p>
  {star}
</section>"""


def countries_movement(d: dict) -> str:
    sl = A.sleeps(d)
    if sl.empty:
        return ""
    by = sl.groupby("country")["nights"].sum().sort_values(ascending=False)
    rows = [(c, v, "gold" if t1 else "accent", op) for (c, v), op, t1 in
            zip(by.items(), np.linspace(0.9, 0.4, len(by)), [False] * len(by))]
    b = band(rows, h=34)
    key = " &nbsp; ".join(f'<span class="k">{esc(c)} <b>{int(v)}</b></span>' for c, v in by.items())
    top = by.index[0]
    return f"""
<section class="movement">
  <p class="tag">Countries</p>
  <figure class="bandfig">{b}<div class="key">{key}</div></figure>
  <p class="caption">{int(by.sum())} nights across {len(by)} countries. Most &mdash;
  {int(by.iloc[0])} &mdash; in {esc(top)}.</p>
</section>"""


def itinerary_movement(d: dict) -> str:
    sl = A.sleeps(d)
    if sl.empty:
        return ""
    names = {t: r["name"] for t, r in d["trips"].iterrows()}
    blocks = []
    for tid, grp in sl.groupby("trip"):
        rows = "".join(
            f'<li><span class="c">{esc(r["city"])}</span>'
            f'<span class="co">{esc(r["country"])}</span>'
            f'<span class="nn">{int(r["nights"])}&#8202;n</span></li>'
            for _, r in grp.sort_values("arrival_date").iterrows())
        blocks.append(f'<div class="itin-trip"><p class="tag">{esc(names.get(tid, tid))}</p>'
                      f'<ol class="itin">{rows}</ol></div>')
    return f'<section class="movement"><p class="tag">Stops</p>{"".join(blocks)}</section>'


def gallery_movement(d: dict) -> str:
    # the editorial page shows only the hand-picked few; the map holds them all.
    entries = [e for e in _photo_entries() if e.get("featured")]
    if not entries:
        return ""
    cells = "".join(
        f'<figure class="ph"><a href="photos/large/{esc(e["file"])}">'
        f'<img loading="lazy" src="photos/thumb/{esc(e["file"])}" alt="{esc(e.get("caption",""))}"></a>'
        f'<figcaption>{esc(e.get("caption",""))}'
        f'{" &mdash; " + esc(e["city"]) if e.get("city") else ""}</figcaption></figure>'
        for e in entries)
    return f'<section class="movement"><p class="tag">Favorites</p><div class="mosaic">{cells}</div></section>'


def colophon(d: dict) -> str:
    return (f'<footer class="colophon">Rail figures from the Interrail app &middot; '
            f'other distances estimated &middot; {d["generated"]:%d %b %Y}</footer>')


# --------------------------------------------------------------------------- #
def _css() -> str:
    def vars_(theme):
        return ";".join(f"--{k}:{v}" for k, v in PAL[theme].items())
    return f"""
:root{{{vars_('light')};
  --serif:"Fraunces","Iowan Old Style",Georgia,serif;
  --sans:"Inter",system-ui,-apple-system,sans-serif;
  --mono:"Spline Sans Mono",ui-monospace,SFMono-Regular,Menlo,monospace}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{{vars_('dark')}}}}}
:root[data-theme=dark]{{{vars_('dark')}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);
  font-size:16px;line-height:1.62;-webkit-font-smoothing:antialiased}}
.page{{max-width:940px;margin:0 auto;padding:clamp(28px,6vw,72px) clamp(20px,5vw,52px) 120px}}
em{{font-style:italic}}
b{{font-weight:500}}
.dateline,.tag,.micro,.ax,.ax-note,.tr-note,.key,.lg-l,.colophon{{
  font-family:var(--mono);text-transform:uppercase;letter-spacing:.14em}}
header{{margin-bottom:clamp(40px,8vw,88px)}}
.dateline{{font-size:11px;color:var(--dim);margin:0 0 22px}}
h1{{font-family:var(--serif);font-weight:400;font-optical-sizing:auto;
  font-size:clamp(38px,7.4vw,72px);line-height:1.03;letter-spacing:-.015em;margin:0 0 24px}}
h1 em{{color:var(--accent)}}
.dek{{font-family:var(--serif);font-size:clamp(17px,2.3vw,21px);line-height:1.5;
  color:var(--dim);max-width:44ch;margin:0}}
.ledger{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
  gap:0 34px;margin:0 0 clamp(50px,9vw,96px)}}
.lg{{border-top:1.5px solid var(--ink);padding:14px 0 20px}}
.lg-n{{font-family:var(--serif);font-size:clamp(28px,4.4vw,44px);line-height:1;letter-spacing:-.02em}}
.lg-l{{font-size:10.5px;color:var(--dim);margin-top:9px}}
.lg-a{{font-family:var(--serif);font-style:italic;font-size:13px;color:var(--dim);margin-top:4px}}
.movement{{margin:clamp(48px,9vw,104px) 0 0;border-top:1px solid var(--rule);padding-top:26px}}
.tag{{font-size:10.5px;color:var(--accent);margin:0 0 20px}}
.statement{{font-family:var(--serif);font-size:clamp(20px,3vw,28px);line-height:1.4;
  font-weight:400;max-width:32ch;margin:0 0 30px}}
.statement b{{color:var(--accent);font-weight:500}}
.caption{{font-family:var(--serif);font-style:italic;font-size:14.5px;color:var(--dim);
  max-width:60ch;margin:18px 0 0}}
.micro{{font-size:11px;color:var(--dim);margin:20px 0 0;line-height:2}}
figure{{margin:0}}
.trace{{margin:8px 0}}
.trace svg{{display:block}}
.strip{{margin:26px 0 4px}}
.bandfig{{margin:0 0 26px}}
.bandfig svg{{display:block;border-radius:2px}}
.key{{font-size:10px;color:var(--dim);margin-top:11px;line-height:2.1}}
.key .k{{white-space:nowrap;margin-right:2px}}
.key i{{display:inline-block;width:8px;height:8px;margin-right:5px;vertical-align:baseline}}
.key b{{color:var(--ink)}}
.ax{{font-size:9px;fill:var(--dim);letter-spacing:.1em}}
.ax-note{{font-size:9px;fill:var(--ink);letter-spacing:.06em}}
.tr-city{{font-family:var(--mono);font-size:10px;fill:var(--ink);letter-spacing:.01em;
  paint-order:stroke;stroke:var(--paper);stroke-width:2.8px;stroke-linejoin:round}}
.tr-sub{{font-family:var(--mono);font-size:8px;fill:var(--dim);letter-spacing:.01em;
  paint-order:stroke;stroke:var(--paper);stroke-width:2.4px;stroke-linejoin:round}}
.tr-note{{font-size:9.5px;fill:var(--ink);letter-spacing:.05em;
  paint-order:stroke;stroke:var(--paper);stroke-width:2.6px;stroke-linejoin:round}}
.itin-trip{{margin-bottom:34px}}
.itin{{list-style:none;margin:0;padding:0;columns:2;column-gap:44px}}
.itin li{{break-inside:avoid;display:flex;align-items:baseline;gap:8px;padding:6px 0;
  border-bottom:1px dotted var(--rule)}}
.itin .c{{font-family:var(--serif);font-size:15px;font-variant:all-small-caps;letter-spacing:.06em;
  flex:1 1 auto;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.itin .co{{font-family:var(--serif);font-style:italic;font-size:12.5px;color:var(--dim)}}
.itin .nn{{font-family:var(--mono);font-size:9.5px;color:var(--dim);letter-spacing:.08em}}
.mosaic{{columns:3;column-gap:14px}}
@media(max-width:680px){{.mosaic{{columns:2}}.itin{{columns:1}}}}
.mosaic .ph{{break-inside:avoid;margin:0 0 14px}}
.mosaic img{{width:100%;display:block;border-radius:2px}}
.mosaic figcaption{{font-family:var(--serif);font-style:italic;font-size:12px;color:var(--dim);margin-top:5px}}
.colophon{{font-size:9.5px;color:var(--dim);margin-top:110px;padding-top:20px;
  border-top:1px solid var(--rule)}}
a{{color:var(--accent)}}
"""


def build_html(d: dict) -> str:
    body = "".join([
        masthead(d), ledger(d), trace_movement(d), trains_movement(d),
        money_movement(d), countries_movement(d), itinerary_movement(d),
        gallery_movement(d), colophon(d),
    ])
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>A gap year around Europe</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,500;1,9..144,400&family=Inter:wght@400;500&family=Spline+Sans+Mono:wght@400;500&display=swap">
<style>{_css()}</style>
</head><body><main class="page">
{body}
</main></body></html>"""


# --------------------------------------------------------------------------- #
# README assets (kept simple, one per theme)
# --------------------------------------------------------------------------- #
def _standalone(svg: str, theme: str) -> str:
    p = PAL[theme]
    css = ";".join(f"--{k}:{v}" for k, v in p.items())
    style = (f'<style>svg{{background:{p["paper"]}}}:root{{{css}}}'
             f'text{{font-family:"Spline Sans Mono",ui-monospace,monospace}}'
             f'.ax{{fill:{p["dim"]};font-size:9px}} .ax-note{{fill:{p["ink"]};font-size:9px}}'
             f'.tr-city{{fill:{p["ink"]};font-size:10px;paint-order:stroke;'
             f'stroke:{p["paper"]};stroke-width:2.8px;stroke-linejoin:round}}'
             f'.tr-sub{{fill:{p["dim"]};font-size:8px;paint-order:stroke;'
             f'stroke:{p["paper"]};stroke-width:2.4px;stroke-linejoin:round}}'
             f'.tr-note{{fill:{p["ink"]};font-size:9.5px;paint-order:stroke;'
             f'stroke:{p["paper"]};stroke-width:2.6px}}</style>')
    return svg.replace(">", ">" + style, 1)


def _chart_set(d: dict) -> dict:
    charts = {}
    tr = route_trace(d, 900, 720)
    if tr:
        charts["route"] = tr
    span = A.active_span(d)
    tl = A.transit_by_day(d)
    if span and not tl.empty:
        cols = []
        for day, r in tl.iterrows():
            tr_h = float(r.get("train", 0)); ot = float(sum(v for m, v in r.items() if m != "train"))
            st = []
            if tr_h > 0: st.append((tr_h, "accent", 0.9))
            if ot > 0: st.append((ot, "ink", 0.28))
            if st: cols.append((day, st))
        annos = []
        for o in d.get("rail", {}).values():
            for j in sorted(o.get("notable", []), key=lambda x: -x["hours"])[:3]:
                annos.append((pd.to_datetime(j["date"]).date(), f'{j["from"]}→{j["to"]}'))
        charts["trains"] = day_strip(span, cols, annos=annos, baseline_label="hours in transit / day")
    sp = A.spend_summary(d)
    if not d["expenses"].empty:
        charts["spend"] = band([(c, v, CAT_COLOR.get(c, "c6"), 0.9)
                                for c, v in sp["by_category"].items()], h=34)
    return charts


def export_assets(d: dict, out: Path = ASSETS) -> list[str]:
    out.mkdir(exist_ok=True)
    w = []
    for name, svg in _chart_set(d).items():
        for theme in ("light", "dark"):
            (out / f"{name}-{theme}.svg").write_text(_standalone(svg, theme), encoding="utf-8")
            w.append(f"{name}-{theme}.svg")
    return w


def _photo_entries():
    cap = PHOTOS / "captions.yml"
    raw = yaml.safe_load(cap.read_text(encoding="utf-8")) if cap.is_file() else None
    pub = DOCS / "photos" / "thumb"
    return [e for e in (raw or []) if isinstance(e, dict) and e.get("file")
            and ((PHOTO_SRC / e["file"]).is_file() or (pub / e["file"]).is_file())]


# cities visited in distinct stints — the map panel gives each its own dated
# header instead of one lumped range.
CITY_LEGS = {
    ("trip1", "Paris"): [
        {"label": "Paris — arrival", "start": "2025-06-25", "end": "2025-06-27"},
        {"label": "Paris — return", "start": "2025-08-18", "end": "2025-08-21"},
    ],
    ("trip2", "Paris"): [
        {"label": "Paris — 1st leg", "start": "2026-02-24", "end": "2026-03-10"},
        {"label": "Paris — 2nd leg", "start": "2026-03-31", "end": "2026-04-06"},
        {"label": "Paris — 3rd leg", "start": "2026-05-10", "end": "2026-05-26"},
    ],
}


def _stay_runs(spans):
    """Merge (arrival, departure) pairs into continuous runs. A gap of <= 1 day
    (a same-day hop out and back) does not start a new run."""
    out = []
    for a, b in sorted(spans):
        if out and (a - out[-1][1]).days <= 1:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def write_map_data(d: dict) -> None:
    """docs/map/data.json — stops, legs and photos for the interactive map."""
    import json
    annos = A.load_annotations()
    trips = d["trips"]
    tname = {t: trips.loc[t, "name"] for t in trips.index}
    s = d["stops"]
    s = s[(~s["is_home"]) & s["arrival_date"].notna() & s["lat"].notna()]
    s = s.sort_values(["trip", "stop_number"])
    legs = []
    for tid, grp in s.groupby("trip"):
        recs = grp.to_dict("records")
        for a, b in zip(recs, recs[1:]):
            if a["city"] == b["city"]:
                continue
            legs.append({"trip": tid, "mode": b["transport"] or "train",
                         "a": [round(a["lat"], 4), round(a["lon"], 4)],
                         "b": [round(b["lat"], 4), round(b["lon"], 4)]})

    # one "stint" per continuous visit; a city visited on both trips (or more
    # than once with a CITY_LEGS override) collects several. The map draws a
    # split-disc for a city seen on two trips and a per-stint panel.
    by_ct: dict = {}
    for _, r in s.iterrows():
        by_ct.setdefault((r["trip"], r["city"]), []).append(r)

    per_city: dict = {}
    for (tid, city), rows in by_ct.items():
        r0 = rows[0]
        nights = max((0 if pd.isna(rr["nights"]) else int(rr["nights"])) for rr in rows)
        an = annos.get(tid, {}).get(city) or {}
        transit = an.get("kind") == "transit"
        kind = "stay" if nights > 0 else ("transit" if transit else "daytrip")
        base = {"trip": tid, "tripName": tname.get(tid, tid),
                "ink": TRIP_INK.get(tid, DEFAULT_INK), "kind": kind,
                "nights": nights, "slept": nights > 0}
        lo = an.get("layover")
        if lo and len(lo) == 2:
            base["window"], base["ground"] = layover_window(lo[0], lo[1])
        elif an.get("window"):
            base["window"] = str(an["window"])

        stints = []
        override = CITY_LEGS.get((tid, city))
        if override:
            for lg in override:
                stints.append({**base, "label": lg["label"],
                               "start": lg["start"], "end": lg["end"]})
        else:
            a, b = max(_stay_runs([(rr["arrival_date"], rr["departure_date"]) for rr in rows]),
                       key=lambda ab: (ab[1] - ab[0]).days)
            stints.append({**base, "label": None,
                           "start": a.strftime("%Y-%m-%d"), "end": b.strftime("%Y-%m-%d")})

        e = per_city.setdefault(city, {
            "city": city, "country": r0["country"],
            "lat": round(r0["lat"], 4), "lon": round(r0["lon"], 4),
            "stints": [], "trips": []})
        e["stints"] += stints
        if tid not in e["trips"]:
            e["trips"].append(tid)

    cities = []
    for e in per_city.values():
        e["stints"].sort(key=lambda st: st["start"])
        e["trips"].sort()
        e["slept"] = any(st["slept"] for st in e["stints"])
        e["nights"] = max((st["nights"] for st in e["stints"]), default=0)
        e["dual"] = len(e["trips"]) > 1
        e["daytrip"] = not e["slept"]
        e["transit"] = (not e["slept"]) and all(st["kind"] == "transit" for st in e["stints"])
        e["trip"] = e["trips"][0] if len(e["trips"]) == 1 else None
        e["ink"] = TRIP_INK.get(e["trip"], DEFAULT_INK) if e["trip"] else None
        e["inks"] = [TRIP_INK.get(t, DEFAULT_INK) for t in e["trips"]]
        cities.append(e)

    photos = {}
    for e in _photo_entries():
        f = e["file"]
        photos.setdefault(e.get("city", ""), []).append(
            {"src": f"../photos/large/{f}", "thumb": f"../photos/thumb/{f}",
             "caption": e.get("caption", ""), "date": str(e.get("date", "") or "")})
    for lst in photos.values():
        lst.sort(key=lambda p: p["date"] or "9999-99-99")  # chronological; file order within a day
    (DOCS / "map").mkdir(parents=True, exist_ok=True)
    (DOCS / "map" / "data.json").write_text(
        json.dumps({"trips": [{"id": t, "name": r["name"], "ink": TRIP_INK.get(t, DEFAULT_INK)}
                              for t, r in d["trips"].iterrows()],
                    "cities": cities, "legs": legs, "photos": photos,
                    "annotations": annos,
                    "modeStyle": MODE_STYLE},
                   separators=(",", ":")), encoding="utf-8")
    (DOCS / "map" / "palette.json").write_text(json.dumps(PAL, separators=(",", ":")),
                                               encoding="utf-8")


# published sizes: 'thumb' for the grid/pins, 'large' for the lightbox.
# the full-res source in photos/ is never copied into docs/.
PHOTO_SIZES = {"thumb": (560, 74), "large": (1400, 82)}


def _publish_photos(imgs, dst):
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return False
    for name, (box, q) in PHOTO_SIZES.items():
        (dst / name).mkdir(parents=True, exist_ok=True)
    for p in imgs:
        try:
            base = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
        except Exception as exc:  # noqa: BLE001
            print(f"  photo skipped {p.name}: {exc}")
            continue
        for name, (box, q) in PHOTO_SIZES.items():
            im = base.copy()
            im.thumbnail((box, box))
            im.save(dst / name / f"{p.stem}.jpg", "JPEG", quality=q)
    return True


def write_docs(d: dict) -> None:
    DOCS.mkdir(exist_ok=True)
    (DOCS / "index.html").write_text(build_html(d), encoding="utf-8")
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")
    dst = DOCS / "photos"
    listed = {e["file"] for e in _photo_entries()}
    imgs = [p for p in PHOTO_SRC.glob("*")
            if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"} and p.name in listed]
    if imgs:
        # rebuild the published copies from the originals; anything no longer in
        # captions.yml is dropped by the rmtree and simply not re-published.
        if dst.exists():
            shutil.rmtree(dst)
        if not _publish_photos(imgs, dst):
            print("  (Pillow not installed — no photos published)")
    elif dst.exists():
        print(f"  (no originals under {PHOTO_SRC} — keeping the committed docs/photos/ as-is)")
    write_map_data(d)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--assets", action="store_true")
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
