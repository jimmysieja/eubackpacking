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
# per-mode line style: (svg-dasharray, relative-weight, opacity, bow-factor, wave)
# wave = amplitude in px of a sine traced along the leg (0 = plain line); one
# period is 4x the amplitude. kept deliberately distinct so the modes read
# apart at a glance.
MODE_STYLE = {
    "train":  ("",           1.9, 0.95, 0.10, 0),
    "bus":    ("9 6",        1.4, 0.85, 0.14, 0),
    "ferry":  ("",           1.4, 0.85, 0.22, 2),   # a wave
    "flight": ("4 5",        1.9, 0.88, 0.55, 0),   # bold dashes + big arc
    "car":    ("6 2 1 2 1 2", 1.3, 0.85, 0.10, 0),  # dash-dot-dot, a road marking
    "bike":   ("2 4",        1.2, 0.80, 0.10, 0),
}
MODE_DASH = {m: s[0] for m, s in MODE_STYLE.items()}

# legs that happened but aren't worth drawing on the map — e.g. a quick
# pre-flight-home hop that just redraws over an earlier leg between the same
# two cities. (trip, from city, to city, mode). The stop itself, its nights
# and its stats are untouched; only the drawn line disappears.
HIDDEN_LEGS = {
    ("trip2", "Paris", "London", "flight"),
}

# fixed per-trip identity colours — deliberately NOT theme-dependent, so the
# same gold/blue means "2025"/"2026" everywhere: the route lines (via PAL
# below, light and dark alike), and every heading that groups content by
# year (Stops, Too Good To Go) via the .trip1-tag / .trip2-tag CSS utility.
TRIP_COLOR = {"trip1": "#fddc5c", "trip2": "#4169e1"}

# "Cotton candy" palette. Single source of truth — the map page reads this too
# (docs/map/palette.json). Change colours here, rerun build, both pages update.
# The Transit and Featured sections locally override `accent` (see .movement-
# transit / .movement-featured in _css()) — everything else, including the
# interactive map, reads these values directly.
PAL = {
    "light": {
        "paper": "#f6f2f0", "ink": "#211d17", "dim": "#6f6a5c", "rule": "#d7d0be",
        "accent": "#c93f8a", "gold": "#9b6fc9", "faint": "#c9c1ac", "far": "#e2dbc9",
        "trip1": TRIP_COLOR["trip1"], "trip2": TRIP_COLOR["trip2"],
        "c0": "#2f5d54", "c1": "#9a7636", "c2": "#7c3b2c", "c3": "#5b4a6f",
        "c4": "#3a6079", "c5": "#7a7d3c", "c6": "#8a8172",
    },
    "dark": {
        "paper": "#17150f", "ink": "#ece5d5", "dim": "#948c7a", "rule": "#332f26",
        "accent": "#ff8fc4", "gold": "#b990e0", "faint": "#3d3a2f", "far": "#2c281f",
        "trip1": TRIP_COLOR["trip1"], "trip2": TRIP_COLOR["trip2"],
        "c0": "#5fa093", "c1": "#c8a55f", "c2": "#cf7359", "c3": "#a08fba",
        "c4": "#7ba7c4", "c5": "#b7bb6e", "c6": "#b3aa96",
    },
}

# which palette colour each trip draws in (route trace + interactive map).
TRIP_INK = {"trip1": "trip1", "trip2": "trip2"}
DEFAULT_INK = "accent"

# flag shown next to each country in the Stops list. UK stops use the
# constituent-nation flag since England, Wales and Northern Ireland are all
# visited on this trip; Northern Ireland has no standardised flag emoji, so
# Belfast falls back to the union flag.
COUNTRY_FLAG = {
    "France": "🇫🇷", "Spain": "🇪🇸", "Switzerland": "🇨🇭", "Italy": "🇮🇹",
    "Albania": "🇦🇱", "Hungary": "🇭🇺", "Czechia": "🇨🇿", "Poland": "🇵🇱",
    "Germany": "🇩🇪", "Netherlands": "🇳🇱", "Ireland": "🇮🇪", "Denmark": "🇩🇰",
    "Sweden": "🇸🇪", "Finland": "🇫🇮", "Estonia": "🇪🇪", "Latvia": "🇱🇻",
    "Lithuania": "🇱🇹", "Austria": "🇦🇹", "Slovakia": "🇸🇰", "Slovenia": "🇸🇮",
    "Croatia": "🇭🇷", "Bosnia and Herzegovina": "🇧🇦", "Montenegro": "🇲🇪",
}
UK_CITY_FLAG = {
    "London": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "Oxford": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "Liverpool": "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
    "Manchester": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "Chinley": "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
    "Betws-y-Coed": "🏴󠁧󠁢󠁷󠁬󠁳󠁿", "Abergavenny": "🏴󠁧󠁢󠁷󠁬󠁳󠁿",
    "Belfast": "🇬🇧",
}


def flag_for(city: str, country: str) -> str:
    if country == "United Kingdom":
        return UK_CITY_FLAG.get(city, "🇬🇧")
    return COUNTRY_FLAG.get(country, "")

# both trips begin and end here — ringed on the static map so it reads as
# the shared home base rather than just another overnight stop.
START_CITY = "Paris"

# --- static route-trace map (assets/route-*.svg + the homepage figure) --------
# Non-overnight stops that still earn a label (name only). Overnight stops are
# always labelled.
#
# Kandersteg, Mürren, Ostrava, Břeclav, Theth, Virpazar, Santa Marinella,
# Vatican City and Lyon are deliberately left out for now (2026-09) — too
# cramped alongside their neighbours. Their ROUTE_LABEL_POS entries below are
# kept (not deleted) since a few other labels were repositioned "to where X
# used to be"; restore a name here to bring its label back.
ROUTE_EXTRA = {
    "Monaco-Ville", "Oxford", "Naples",
}
# display text for a city label, where it differs from the data's city name
ROUTE_DISPLAY = {"Monaco-Ville": "Monaco"}
# hand nudges for labels that would otherwise collide. (dx, dy, anchor);
# anchor is "start" (label right of dot), "end" (left) or "middle".
ROUTE_LABEL_POS = {
    "Paris":        (9, 3, "start"),   # clears the start/end ring
    "Liverpool":    (0, -10, "middle"),
    "Manchester":   (7, 12, "start"),
    "Abergavenny":  (-10, 13, "end"),
    "Betws-y-Coed": (0, 16, "middle"),
    "Belfast":      (-8, -4, "end"),
    "Clifden":      (-6, 3, "end"),
    "Galway":       (-8, 14, "middle"),
    "Dublin":       (0, 13, "middle"),
    "Oxford":       (10, -4, "start"),
    "Ercolano":     (10, 11, "start"),
    "Naples":       (-9, 1, "end"),
    "Bari":         (9, 3, "start"),
    "Rome":         (4, -3, "start"),
    "Vatican City": (-2, 20, "middle"),
    "Santa Marinella": (-10, -10, "end"),
    "Lyon":         (-10, 26, "end"),
    "Chamonix":     (0, 16, "middle"),
    "Annecy":       (0, -14, "middle"),
    "Zermatt":      (9, -2, "start"),
    "Kandersteg":   (-6, -30, "end"),
    "Interlaken":   (0, -10, "middle"),
    "Mürren":       (0, -13, "middle"),
    "Milan":        (8, 9, "start"),
    "Nice":         (0, 13, "middle"),
    "Monaco-Ville": (5, -3, "start"),
    "Marseille":    (-9, 6, "end"),
    "Florence":     (5, 4, "start"),
    "Bled":         (-9, -3, "end"),
    "Ljubljana":    (8, 9, "start"),
    "Vienna":       (-8, -3, "end"),
    "Bratislava":   (2, -4, "start"),
    "Zagreb":       (8, 6, "start"),
    "Kraków":       (8, -3, "start"),
    "Budapest":     (0, 13, "middle"),
    "Sarajevo":     (0, -11, "middle"),
    "Split":        (0, -16, "middle"),
    "Mostar":       (-4, 14, "middle"),
    "Žabljak":      (4, 2, "start"),
    "Podgorica":    (2, 8, "end"),
    "Virpazar":     (-2, 20, "middle"),
    "Shkodër":      (2, -2, "start"),
    "Theth":        (22, -4, "start"),
    "Tirana":       (0, 13, "middle"),
}


def esc(x) -> str:
    return html.escape(str(x), quote=True)


def fmt(n, nd=0) -> str:
    if n is None or (isinstance(n, float) and np.isnan(n)):
        return "–"
    return f"{n:,.{nd}f}" if nd else f"{round(n):,}"


def hm(hours: float) -> str:
    h = int(hours)
    m = round((hours - h) * 60)
    return f"{h}h{m:02d}m" if m else f"{h}h"


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
            out.append(f'<path d="{dd}Z" fill="none" stroke="var(--dim)" '
                       f'stroke-width="0.9" opacity="0.6"/>')
    return "".join(out)


def _wave_path(p0, c, p1, amp, samples=64) -> str:
    """SVG path of a sine (amplitude `amp`) traced along the quadratic curve
    p0 -> p1 with control point c, fitted to a whole number of periods so it
    starts and ends on the pins. Mirrors wavy() on the map page."""
    pts = [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * c[0] + t * t * p1[0],
            (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * c[1] + t * t * p1[1])
           for t in (i / samples for i in range(samples + 1))]
    cum = [0.0]
    for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
        cum.append(cum[-1] + math.hypot(xb - xa, yb - ya))
    total = cum[-1]
    if total < amp * 2:
        return f"M{p0[0]:.1f} {p0[1]:.1f} L{p1[0]:.1f} {p1[1]:.1f}"
    periods = max(1, round(total / (amp * 4)))
    n, out, j = periods * 12, [], 0
    for i in range(n + 1):
        s = total * i / n
        while j < samples - 1 and cum[j + 1] < s:
            j += 1
        (xa, ya), (xb, yb) = pts[j], pts[j + 1]
        seg = (cum[j + 1] - cum[j]) or 1
        t, o = (s - cum[j]) / seg, amp * math.sin(2 * math.pi * periods * i / n)
        out.append((xa + (xb - xa) * t - (yb - ya) / seg * o,
                    ya + (yb - ya) * t + (xb - xa) / seg * o))
    return "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in out)


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
            mode = b["transport"] or "train"
            if a["city"] == b["city"] or mode in A.ON_FOOT:
                continue
            if (tid, a["city"], b["city"], mode) in HIDDEN_LEGS:
                continue
            dash, wt, op, bow, wave = MODE_STYLE.get(mode, MODE_STYLE["train"])
            x1, y1, x2, y2 = sx(a["lon"]), sy(a["lat"]), sx(b["lon"]), sy(b["lat"])
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            nx, ny = -(y2 - y1), (x2 - x1)
            nl = (nx * nx + ny * ny) ** 0.5 or 1
            k = min(60, ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5 * bow)
            cx, cy = mx + nx / nl * k, my + ny / nl * k
            cap = ' stroke-linecap="round"' if dash.startswith("0.1") else ""
            dd = (_wave_path((x1, y1), (cx, cy), (x2, y2), wave) if wave else
                  f"M{x1:.1f} {y1:.1f} Q{cx:.1f} {cy:.1f} {x2:.1f} {y2:.1f}")
            seg.append(f'<path d="{dd}" '
                       f'fill="none" stroke="var(--{ink})" stroke-width="{wt:.2f}"{cap} '
                       f'stroke-dasharray="{dash}" opacity="{op}"/>')

    dots, labels, seen, ringed = [], [], set(), set()
    for tid, grp in s.groupby("trip"):
        ink = trip_ink.get(tid, "accent")
        for r in grp.to_dict("records"):
            city = r["city"]
            x, y = sx(r["lon"]), sy(r["lat"])
            big = city in slept_cities
            dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{3.0 if big else 1.7}" '
                        f'fill="var(--{ink})" stroke="var(--paper)" stroke-width="0.8">'
                        f'<title>{esc(city)}</title></circle>')
            if city == START_CITY and city not in ringed:
                ringed.add(city)
                dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6.5" fill="none" '
                            f'stroke="var(--ink)" stroke-width="0.9" opacity="0.55">'
                            f'<title>Start / end of both trips</title></circle>')
            if city in seen:
                continue
            if not (big or city in ROUTE_EXTRA):
                continue
            seen.add(city)
            dx, dy, anchor = ROUTE_LABEL_POS.get(
                city, (6, 3, "start") if x < w * 0.62 else (-6, 3, "end"))
            tx, ty = x + dx, y + dy
            lead = (f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{tx:.1f}" y2="{ty - 3:.1f}" '
                    f'stroke="var(--rule)" stroke-width="0.7"/>') if abs(dx) > 11 or abs(dy) > 11 else ""
            labels.append(f'{lead}<text x="{tx:.1f}" y="{ty:.1f}" text-anchor="{anchor}" '
                          f'class="tr-city">{esc(ROUTE_DISPLAY.get(city, city))}</text>')

    return (f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="Route trace">'
            f'<rect x="0.5" y="0.5" width="{w-1}" height="{h-1}" fill="none" '
            f'stroke="var(--rule)" stroke-width="1"/>'
            f'{outlines}{"".join(seg)}{"".join(dots)}{"".join(labels)}</svg>')


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


def _nice_step(vmax: float, target: int = 3) -> float:
    """A 'round' gridline step (1/2/2.5/5 x a power of ten) giving ~`target` ticks."""
    if vmax <= 0:
        return 1.0
    raw = vmax / target
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def _fmt_tick(v: float) -> str:
    return f"{v:g}"


def day_strip(span, columns, *, w=900, h=150, pad_l=26, annos=None, baseline_label="",
             y_unit="") -> str:
    """columns: list of (date, [(value, colorvar, opacity), ...]) stacked bottom-up."""
    d0, d1 = span
    ndays = (d1 - d0).days + 1
    plot_h = h - 34
    base_y = plot_h + 6
    sx = lambda day: pad_l + (w - pad_l - 8) * ((day - d0).days) / max(1, ndays - 1)
    cw = max(1.4, (w - pad_l - 8) / ndays * 0.7)
    vmax = max((sum(v for v, _, _ in stack) for _, stack in columns), default=1) or 1
    step = _nice_step(vmax)
    grid, y = [], step
    while y <= vmax * 1.001:
        gy = base_y - plot_h * y / vmax
        grid.append(f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{w-8}" y2="{gy:.1f}" '
                    f'stroke="var(--rule)" stroke-width="0.6"/>'
                    f'<text x="0" y="{gy-3:.1f}" class="ax">{_fmt_tick(y)}{y_unit}</text>')
        y += step
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
            f'{"".join(grid)}'
            f'{"".join(bars)}'
            f'<line x1="{pad_l}" y1="{base_y:.1f}" x2="{w-8}" y2="{base_y:.1f}" stroke="var(--rule)"/>'
            f'{_month_ticks(span, sx, base_y)}{"".join(ann)}{lbl}</svg>')


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
  the stops, and the time spent in transit. {ov['n_countries_visited']} countries,
  {ov['n_cities']} cities.</p>
</header>"""


def trace_movement(d: dict) -> str:
    svg = route_trace(d)
    if not svg:
        return ""
    return f"""
<section class="movement">
  <p class="tag">Route</p>
  <p class="map-link"><a href="map/">Interactive map w/ pictures &rarr;</a></p>
  <figure class="trace">{svg}</figure>
</section>"""


def transit_movement(d: dict) -> str:
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
    strip = day_strip(span, cols, baseline_label="hours in transit, by day") if cols else ""
    legend = ('<div class="key">'
              '<span class="k"><i style="background:var(--accent);opacity:.9"></i>train</span>'
              '<span class="k"><i style="background:var(--ink);opacity:.28"></i>other transit (bus, ferry, flight, car)</span>'
              '</div>') if cols else ""
    ov = [f'{ts["rail_legs"]} trains']
    mb = A.mode_breakdown(d)
    if not mb.empty:
        for mode, label in (("bus", "buses"), ("flight", "flights")):
            n = int(mb.loc[mode, "legs"]) if mode in mb.index else 0
            if n:
                ov.append(f'{n} {label}')
    ov.append(f'{fmt(ts["rail_km"])} km')
    return f"""
<section class="movement movement-transit">
  <p class="tag">Transit</p>
  <p class="statement"><b>{hm(ts['rail_hours'])} on trains</b> &mdash; about
  {ts['full_days_equiv']:.1f} days.</p>
  <figure class="strip">{strip}</figure>
  {legend}
  <p class="micro">{' &nbsp;&middot;&nbsp; '.join(esc(x) for x in ov)}</p>
</section>"""


def itinerary_movement(d: dict) -> str:
    sl = A.sleeps(d)
    if sl.empty:
        return ""
    names = {t: r["name"] for t, r in d["trips"].iterrows()}
    blocks = []
    for tid, grp in sl.groupby("trip"):
        stints = []
        for city, g in grp.groupby("city", sort=False):
            country = g["country"].iloc[0]
            for a, b in _stay_runs(list(zip(g["arrival_date"], g["departure_date"]))):
                stints.append({"city": city, "country": country, "arrival_date": a,
                               "nights": (b - a).days})
        stints.sort(key=lambda r: r["arrival_date"])
        rows = "".join(
            f'<li><span class="c">{esc(r["city"])}</span>'
            f'<span class="co" title="{esc(r["country"])}">{flag_for(r["city"], r["country"])}</span>'
            f'<span class="nn">{r["nights"]}&#8202;n</span></li>'
            for r in stints)
        blocks.append(f'<div class="itin-trip"><p class="tag {tid}-tag">{esc(names.get(tid, tid))}</p>'
                      f'<ol class="itin">{rows}</ol></div>')
    divider = '<div class="year-fade" aria-hidden="true"></div>'
    return f'<section class="movement"><p class="tag">Stops</p>{divider.join(blocks)}</section>'


def tgtg_movement(d: dict) -> str:
    tg = A.tgtg_summary(d)
    if not tg.get("count"):
        return ""
    facts = [f'{tg["count"]} bags', f'{tg["cities"]} cities']
    if tg.get("stores"):
        facts.append(f'{tg["stores"]} different stores')

    trip_blocks = "".join(
        f'<div class="tgtg-trip"><p class="tag {t["trip"]}-tag">{esc(t["name"])}</p>'
        f'<p class="micro">{t["count"]} bags</p></div>'
        for t in tg.get("by_trip", []))

    countries = tg.get("by_country")
    country_line = ""
    if countries is not None and not countries.empty:
        line = ' &nbsp;&middot;&nbsp; '.join(f'{esc(c)} {n}' for c, n in countries.items())
        country_line = f'<p class="micro">by country &nbsp;&middot;&nbsp; {line}</p>'

    paul = tg.get("paul_count") or 0
    shoutout = (f'<p class="caption">&#129360; <b>Paul&rsquo;s, {paul}&times;</b> '
                f'&mdash; the run-away favorite.</p>') if paul else ""

    return f"""
<section class="movement">
  <p class="tag">Too Good To Go</p>
  <p class="statement"><b>{tg['count']} bags</b> rescued across {tg['cities']} cities.</p>
  <div class="tgtg-trips">{trip_blocks}</div>
  {country_line}
  {shoutout}
  <p class="micro">{' &nbsp;&middot;&nbsp; '.join(esc(x) for x in facts)}</p>
</section>"""


def _photo_cell(e: dict) -> str:
    file = esc(_pub_name(e["file"]))
    cap = esc(e.get("caption", ""))
    city = e.get("city", "")
    city_p = f'<p class="ph-city">{esc(city)}</p>' if city else ""
    return (f'<figure class="ph"><a href="photos/large/{file}" data-lightbox '
            f'data-caption="{cap}" data-city="{esc(city)}">'
            f'<img loading="lazy" src="photos/thumb/{file}" alt="{cap}"></a>'
            f'<figcaption>{cap}</figcaption>{city_p}</figure>')


def gallery_movement(d: dict) -> str:
    # the editorial page shows only the hand-picked few; the map holds them all.
    entries = [e for e in _photo_entries() if e.get("featured")]
    if not entries:
        return ""
    cells = "".join(_photo_cell(e) for e in entries)
    return f"""
<section class="movement movement-featured">
  <p class="tag">Favorites</p>
  <div class="mosaic">{cells}</div>
</section>
<div id="lightbox" aria-hidden="true">
  <figure>
    <img alt="">
    <figcaption></figcaption>
  </figure>
</div>
<script>
(function(){{
  var lb = document.getElementById('lightbox');
  var img = lb.querySelector('img');
  var cap = lb.querySelector('figcaption');
  var fig = lb.querySelector('figure');
  document.querySelectorAll('.mosaic a[data-lightbox]').forEach(function(a){{
    a.addEventListener('click', function(e){{
      e.preventDefault();
      img.src = a.getAttribute('href');
      var caption = a.dataset.caption || '', city = a.dataset.city || '';
      img.alt = caption;
      cap.textContent = city ? caption + ' \\u2014 ' + city : caption;
      lb.classList.add('open');
    }});
  }});
  fig.addEventListener('click', function(e){{ e.stopPropagation(); }});
  lb.addEventListener('click', function(){{ lb.classList.remove('open'); }});
}})();
</script>"""


# --------------------------------------------------------------------------- #
def _css() -> str:
    def vars_(theme):
        return ";".join(f"--{k}:{v}" for k, v in PAL[theme].items())
    return f"""
:root{{{vars_('light')};
  --serif:"Fraunces","Iowan Old Style",Georgia,serif;
  --sans:"Instrument Sans",system-ui,-apple-system,sans-serif;
  --mono:"Spline Sans Mono",ui-monospace,SFMono-Regular,Menlo,monospace}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{{vars_('dark')}}}}}
:root[data-theme=dark]{{{vars_('dark')}}}
.movement-transit{{--accent:#1a94c4}}
.movement-featured{{--accent:#a9713f}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]) .movement-transit{{--accent:#5cd3f5}}
  :root:not([data-theme=light]) .movement-featured{{--accent:#d19a5e}}}}
:root[data-theme=dark] .movement-transit{{--accent:#5cd3f5}}
:root[data-theme=dark] .movement-featured{{--accent:#d19a5e}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);
  font-size:16px;line-height:1.62;-webkit-font-smoothing:antialiased}}
.page{{max-width:940px;margin:0 auto;padding:clamp(28px,6vw,72px) clamp(20px,5vw,52px) 120px}}
em{{font-style:italic}}
b{{font-weight:500}}
.dateline,.tag,.micro,.ax,.ax-note,.key{{
  font-family:var(--mono);text-transform:uppercase;letter-spacing:.14em}}
header{{margin-bottom:clamp(40px,8vw,88px)}}
.dateline{{font-size:11px;color:var(--dim);margin:0 0 22px}}
h1{{font-family:var(--serif);font-weight:400;font-optical-sizing:auto;
  font-size:clamp(38px,7.4vw,72px);line-height:1.03;letter-spacing:-.015em;margin:0 0 24px}}
h1 em{{color:var(--accent)}}
.dek{{font-family:var(--serif);font-size:clamp(17px,2.3vw,21px);line-height:1.5;
  color:var(--dim);max-width:44ch;margin:0}}
.movement{{margin:clamp(48px,9vw,104px) 0 0;border-top:1px solid var(--rule);padding-top:26px}}
.tag{{font-size:10.5px;color:var(--accent);margin:0 0 20px}}
.trip1-tag{{color:{TRIP_COLOR['trip1']}}}
.trip2-tag{{color:{TRIP_COLOR['trip2']}}}
.map-link{{font-family:var(--serif);font-size:clamp(18px,2.6vw,22px);margin:0 0 18px}}
.map-link a{{color:var(--accent);text-decoration:underline;text-decoration-color:currentColor;
  text-underline-offset:4px}}
.map-link a:hover{{color:var(--ink)}}
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
.key{{font-size:10px;color:var(--dim);margin-top:11px;line-height:2.1}}
.key .k{{white-space:nowrap;margin-right:2px}}
.key i{{display:inline-block;width:8px;height:8px;margin-right:5px;vertical-align:baseline}}
.key b{{color:var(--ink)}}
.ax{{font-size:9px;fill:var(--dim);letter-spacing:.1em}}
.ax-note{{font-size:9px;fill:var(--ink);letter-spacing:.06em}}
.tr-city{{font-family:var(--mono);font-size:9px;fill:var(--ink);letter-spacing:.01em;
  paint-order:stroke;stroke:var(--paper);stroke-width:2.8px;stroke-linejoin:round}}
.year-fade{{height:3px;margin:0 0 28px;border-radius:2px;
  background:linear-gradient(90deg,{TRIP_COLOR['trip1']},{TRIP_COLOR['trip2']})}}
.itin-trip{{margin-bottom:34px}}
.itin{{list-style:none;margin:0;padding:0;columns:2;column-gap:44px}}
.itin li{{break-inside:avoid;display:flex;align-items:baseline;gap:8px;padding:6px 0;
  border-bottom:1px dotted var(--rule)}}
.itin .c{{font-family:var(--serif);font-size:15px;font-variant:all-small-caps;letter-spacing:.06em;
  flex:1 1 auto;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.itin .co{{font-size:15px;line-height:1}}
.itin .nn{{font-family:var(--mono);font-size:9.5px;color:var(--dim);letter-spacing:.08em}}
.tgtg-trips{{display:flex;gap:36px;flex-wrap:wrap;margin:24px 0 0}}
.tgtg-trip .tag{{margin-bottom:6px}}
.tgtg-trip .micro{{margin-top:0}}
@media(max-width:680px){{.itin{{columns:1}}}}
.mosaic{{column-width:180px;column-gap:20px}}
.mosaic .ph{{break-inside:avoid;margin:0 0 28px}}
.mosaic a{{display:block}}
.mosaic img{{width:100%;display:block;border-radius:4px}}
.mosaic figcaption{{font-family:var(--serif);font-style:italic;font-size:13px;line-height:1.45;
  color:var(--dim);margin:8px 0 0}}
.mosaic .ph-city{{font-family:var(--mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;
  color:var(--accent);margin:4px 0 0}}
#lightbox{{position:fixed;inset:0;z-index:100;background:rgba(20,18,14,.92);display:none;
  align-items:center;justify-content:center;padding:32px;cursor:zoom-out}}
#lightbox.open{{display:flex}}
#lightbox figure{{max-width:100%;max-height:100%;cursor:default;text-align:center}}
#lightbox img{{max-width:100%;max-height:80vh;object-fit:contain;display:block;margin:0 auto}}
#lightbox figcaption{{font-family:var(--serif);font-style:italic;font-size:14px;
  color:#f3efe6;margin-top:16px;max-width:60ch}}
a{{color:var(--accent)}}
"""


def build_html(d: dict) -> str:
    body = "".join([
        masthead(d), trace_movement(d), transit_movement(d), itinerary_movement(d),
        tgtg_movement(d), gallery_movement(d),
    ])
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>A gap year around Europe</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,500;1,9..144,400&family=Instrument+Sans:wght@400;500&family=Spline+Sans+Mono:wght@400;500&display=swap">
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
             f'.tr-city{{fill:{p["ink"]};font-size:9px;paint-order:stroke;'
             f'stroke:{p["paper"]};stroke-width:2.8px;stroke-linejoin:round}}</style>')
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
        charts["trains"] = day_strip(span, cols, baseline_label="hours in transit / day")
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
    # the published copy is always a .jpg (see _pub_name) regardless of the
    # source extension, so the fallback check has to look for that name too.
    return [e for e in (raw or []) if isinstance(e, dict) and e.get("file")
            and ((PHOTO_SRC / e["file"]).is_file() or (pub / _pub_name(e["file"])).is_file())]


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
            mode = b["transport"] or "train"
            if a["city"] == b["city"] or mode in A.ON_FOOT:
                continue
            if (tid, a["city"], b["city"], mode) in HIDDEN_LEGS:
                continue
            legs.append({"trip": tid, "mode": mode,
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
        f = _pub_name(e["file"])
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


def _pub_name(file: str) -> str:
    """_publish_photos always writes JPEG named after the stem, whatever the
    source extension/case was — so links to the published copy must too."""
    return f"{Path(file).stem}.jpg"


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
