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
# same blue/purple means "2025"/"2026" everywhere: the route lines (via PAL
# below, light and dark alike), every heading that groups content by year
# (Stops, Too Good To Go) via the .trip1-tag / .trip2-tag CSS utility, and
# the Transit chart's train bars. Deepened from the light a0c4ff/e7bfff-ish
# family requested to stay readable as thin lines and small text.
TRIP_COLOR = {"trip1": "#4a7fe8", "trip2": "#a873d9"}

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

# --- flags -------------------------------------------------------------- #
# Real flag artwork, not hand-drawn approximations. Every entry except
# ES/HR/ME is the *unmodified* inner markup from lipis/flag-icons (MIT
# licensed, github.com/lipis/flag-icons/tree/main/flags/4x3), fetched
# 2026-09-14 and pasted in verbatim -- so proportions, colours and charges
# match the real flag exactly, not from memory. All share that library's
# native viewBox="0 0 640 480" (4:3), which is also the sprite's own
# viewBox (see _flag_defs) so nothing gets rescaled or reinterpreted.
#
# ES, HR and ME are the exception: their real coats of arms run to 500+
# tiny paths (individual heraldic charges, feather-by-feather shading) that
# would render as an illegible smudge at 20-30px and bloat the page for
# nothing. Those three are hand-built instead -- correct shield/crown/charge
# *placement*, proportions and colour, at a level of detail that actually
# survives being shrunk to icon size -- rather than omitted, which is what
# they were before and exactly the complaint.
def _checkerboard(x0, y0, w, h, cols, rows, c1, c2):
    """cols x rows grid, c1 at the top-left cell -- Croatia's šahovnica."""
    cw, ch = w / cols, h / rows
    return "".join(
        f'<rect x="{x0 + c * cw:.1f}" y="{y0 + r * ch:.1f}" width="{cw + 0.6:.1f}" height="{ch + 0.6:.1f}" '
        f'fill="{c1 if (r + c) % 2 == 0 else c2}"/>'
        for r in range(rows) for c in range(cols)
    )


# a double-headed eagle displayed (wings spread, both heads outward, gold on
# Montenegro's flag) -- drawn once in a -8.2..8.2 x -9.2..6.2 local box and
# placed via a translate+scale transform.
_EAGLE_D = (
    "M0,6.2 L2.6,3.0 L2.0,0.6 L3.2,-1.0 L5.6,-1.4 L3.2,-3.0 L8.2,-3.8 L4.2,-5.2 L6.6,-7.6 "
    "L2.6,-6.0 L5.2,-9.2 L7.6,-8.0 L4.6,-7.4 L1.2,-5.0 L0,-2.6 L-1.2,-5.0 L-4.6,-7.4 "
    "L-7.6,-8.0 L-5.2,-9.2 L-2.6,-6.0 L-6.6,-7.6 L-4.2,-5.2 L-8.2,-3.8 L-3.2,-3.0 "
    "L-5.6,-1.4 L-3.2,-1.0 L-2.0,0.6 L-2.6,3.0 Z"
)


def _eagle(color, cx, cy, scale):
    return f'<path d="{_EAGLE_D}" fill="{color}" transform="translate({cx},{cy}) scale({scale})"/>'


# Spain's shield -- quartered Castile (castle, red) / León (lion, silver),
# crowned, flanked by the Pillars of Hercules -- was entirely missing
# before; the real achievement is a ~80KB / 540-path illustration, so this
# keeps the correct shape, quartering and colour instead of that detail.
_ES_SHIELD = "M140,175 H250 V300 Q250,336 195,351 Q140,336 140,300 Z"
_ES_EMBLEM = (
    '<rect x="106" y="145" width="13" height="205" rx="2" fill="#C9A961"/>'
    '<rect x="98" y="130" width="29" height="17" rx="3" fill="#D4AF37"/>'
    '<rect x="271" y="145" width="13" height="205" rx="2" fill="#C9A961"/>'
    '<rect x="263" y="130" width="29" height="17" rx="3" fill="#D4AF37"/>'
    f'<clipPath id="es-shield"><path d="{_ES_SHIELD}"/></clipPath>'
    '<g clip-path="url(#es-shield)">'
    '<rect x="140" y="175" width="55" height="62.5" fill="#AD1519"/>'
    '<rect x="195" y="175" width="55" height="62.5" fill="#F2F2F2"/>'
    '<rect x="140" y="237.5" width="55" height="113.5" fill="#F2F2F2"/>'
    '<rect x="195" y="237.5" width="55" height="113.5" fill="#AD1519"/>'
    '<rect x="155" y="193" width="26" height="19" fill="#D4AF37"/>'
    '<rect x="157" y="184" width="4" height="11" fill="#D4AF37"/>'
    '<rect x="166" y="184" width="4" height="11" fill="#D4AF37"/>'
    '<rect x="175" y="184" width="4" height="11" fill="#D4AF37"/>'
    '<ellipse cx="222" cy="207" rx="14" ry="10" fill="#4B2E83"/>'
    '<ellipse cx="167" cy="269" rx="14" ry="10" fill="#4B2E83"/>'
    '<rect x="209" y="255" width="26" height="19" fill="#D4AF37"/>'
    '<rect x="211" y="246" width="4" height="11" fill="#D4AF37"/>'
    '<rect x="220" y="246" width="4" height="11" fill="#D4AF37"/>'
    '<rect x="229" y="246" width="4" height="11" fill="#D4AF37"/>'
    '<circle cx="195" cy="341" r="8" fill="#7A8C3F"/>'
    "</g>"
    f'<path d="{_ES_SHIELD}" fill="none" stroke="#D4AF37" stroke-width="4"/>'
    '<path d="M155,158 Q195,128 235,158 L228,176 Q195,156 162,176 Z" fill="#D4AF37"/>'
    '<circle cx="165" cy="151" r="7" fill="#D4AF37"/><circle cx="195" cy="144" r="8" fill="#D4AF37"/>'
    '<circle cx="225" cy="151" r="7" fill="#D4AF37"/>'
)

# Croatia's šahovnica -- a real 5x5 red/white checkerboard shield (red at
# dexter chief, per the constitution), topped with a simplified band
# standing in for the crown of 5 historical shields (Croatia, Dubrovnik,
# Dalmatia, Istria, Slavonia) -- present and correctly coloured/placed
# rather than the plain tricolour this used to fall back to.
_HR_SHIELD = "M227,165 H413 V300 Q413,345 320,364 Q227,345 227,300 Z"
_HR_EMBLEM = (
    f'<clipPath id="hr-shield"><path d="{_HR_SHIELD}"/></clipPath>'
    '<g clip-path="url(#hr-shield)">' + _checkerboard(227, 163, 187, 202, 5, 5, "#FF0000", "#FFFFFF") + "</g>"
    f'<path d="{_HR_SHIELD}" fill="none" stroke="#FFF" stroke-width="3"/>'
    + "".join(
        f'<rect x="{cx - 17}" y="98" width="34" height="46" rx="4" fill="#F0E4C8" stroke="#FFF" stroke-width="3"/>'
        for cx in (248, 284, 320, 356, 392)
    )
)

FLAG_SHAPES = {
    "FR": '<path fill="#000091" d="M0 0h213.3v480H0z"/><path fill="#fff" d="M213.3 0h213.4v480H213.3z"/><path fill="#e1000f" d="M426.7 0H640v480H426.7z"/>',
    "ES": '<path fill="#AA151B" d="M0 0h640v480H0z"/><path fill="#F1BF00" d="M0 120h640v240H0z"/>' + _ES_EMBLEM,
    "CH": '<g fill-rule="evenodd" stroke-width="1pt"><path fill="red" d="M0 0h640v480H0z"/><g fill="#fff"><path d="M170 195h300v90H170z"/><path d="M275 90h90v300h-90z"/></g></g>',
    "IT": '<g fill-rule="evenodd" stroke-width="1pt"><path fill="#fff" d="M0 0h640v480H0z"/><path fill="#009246" d="M0 0h213.3v480H0z"/><path fill="#ce2b37" d="M426.7 0H640v480H426.7z"/></g>',
    "AL": '<path fill="red" d="M0 0h640v480H0z"/><path id="al-a" fill="#000001" d="M272 93.3c-4.6 0-12.3 1.5-12.2 5-13-2.1-14.3 3.2-13.5 8q2-2.9 3.9-3.1 2.5-.3 5.4 1.4a22 22 0 0 1 4.8 4.1c-4.6 1.1-8.2.4-11.8-.2a17 17 0 0 1-5.7-2.4c-1.5-1-2-2-4.3-4.3-2.7-2.8-5.6-2-4.7 2.3 2.1 4 5.6 5.8 10 6.6 2.1.3 5.3 1 8.9 1s7.6-.5 9.8 0c-1.3.8-2.8 2.3-5.8 2.8s-7.5-1.8-10.3-2.4c.3 2.3 3.3 4.5 9.1 5.7 9.6 2 17.5 3.6 22.8 6.5a37 37 0 0 1 10.9 9.2c4.7 5.5 5 9.8 5.2 10.8 1 8.8-2.1 13.8-7.9 15.4-2.8.7-8-.7-9.8-2.9-2-2.2-3.7-6-3.2-12 .5-2.2 3.1-8.3.9-9.5a274 274 0 0 0-32.3-15.1c-2.5-1-4.5 2.4-5.3 3.8a50 50 0 0 1-36-23.7c-4.2-7.6-11.3 0-10.1 7.3 1.9 8 8 13.8 15.4 18s17 8.2 26.5 8c5.2 1 5.1 7.6-1 8.9-12.1 0-21.8-.2-30.9-9-6.9-6.3-10.7 1.2-8.8 5.4 3.4 13.1 22.1 16.8 41 12.6 7.4-1.2 3 6.6 1 6.7-8 5.7-22.1 11.2-34.6 0-5.7-4.4-9.6-.8-7.4 5.5 5.5 16.5 26.7 13 41.2 5 3.7-2.1 7.1 2.7 2.6 6.4-18.1 12.6-27.1 12.8-35.3 8-10.2-4.1-11 7.2-5 11 6.7 4 23.8 1 36.4-7 5.4-4 5.6 2.3 2.2 4.8-14.9 12.9-20.8 16.3-36.3 14.2-7.7-.6-7.6 8.9-1.6 12.6 8.3 5.1 24.5-3.3 37-13.8 5.3-2.8 6.2 1.8 3.6 7.3a54 54 0 0 1-21.8 18c-7 2.7-13.6 2.3-18.3.7-5.8-2-6.5 4-3.3 9.4 1.9 3.3 9.8 4.3 18.4 1.3s17.8-10.2 24.1-18.5c5.5-4.9 4.9 1.6 2.3 6.2-12.6 20-24.2 27.4-39.5 26.2-6.7-1.2-8.3 4-4 9 7.6 6.2 17 6 25.4-.2 7.3-7 21.4-22.4 28.8-30.6 5.2-4.1 6.9 0 5.3 8.4-1.4 4.8-4.8 10-14.3 13.6-6.5 3.7-1.6 8.8 3.2 9 2.7 0 8.1-3.2 12.3-7.8 5.4-6.2 5.8-10.3 8.8-19.9 2.8-4.6 7.9-2.4 7.9 2.4-2.5 9.6-4.5 11.3-9.5 15.2-4.7 4.5 3.3 6 6 4.1 7.8-5.2 10.6-12 13.2-18.2 2-4.4 7.4-2.3 4.8 5-6 17.4-16 24.2-33.3 27.8-1.7.3-2.8 1.3-2.2 3.3l7 7c-10.7 3.2-19.4 5-30.2 8l-14.8-9.8c-1.3-3.2-2-8.2-9.8-4.7-5.2-2.4-7.7-1.5-10.6 1 4.2 0 6 1.2 7.7 3.1 2.2 5.7 7.2 6.3 12.3 4.7 3.3 2.7 5 4.9 8.4 7.7l-16.7-.5c-6-6.3-10.6-6-14.8-1-3.3.5-4.6.5-6.8 4.4 3.4-1.4 5.6-1.8 7.1-.3 6.3 3.7 10.4 2.9 13.5 0l17.5 1.1c-2.2 2-5.2 3-7.5 4.8-9-2.6-13.8 1-15.4 8.3a17 17 0 0 0-1.2 9.3q1.1-4.6 4.9-7c8 2 11-1.3 11.5-6.1 4-3.2 9.8-3.9 13.7-7.1 4.6 1.4 6.8 2.3 11.4 3.8q2.4 7.5 11.3 5.6c7 .2 5.8 3.2 6.4 5.5 2-3.3 1.9-6.6-2.5-9.6-1.6-4.3-5.2-6.3-9.8-3.8-4.4-1.2-5.5-3-9.9-4.3 11-3.5 18.8-4.3 29.8-7.8l7.7 6.8q2.3 1.5 3.8 0c6.9-10 10-18.7 16.3-25.3 2.5-2.8 5.6-6.4 9-7.3 1.7-.5 3.8-.2 5.2 1.3 1.3 1.4 2.4 4.1 2 8.2-.7 5.7-2.1 7.6-3.7 11s-3.6 5.6-5.7 8.3c-4 5.3-9.4 8.4-12.6 10.5-6.4 4.1-9 2.3-14 2-6.4.7-8 3.8-2.8 8.1 4.8 2.6 9.2 2.9 12.8 2.2 3-.6 6.6-4.5 9.2-6.6 2.8-3.3 7.6.6 4.3 4.5-5.9 7-11.7 11.6-19 11.5-7.7 1-6.2 5.3-1.2 7.4 9.2 3.7 17.4-3.3 21.6-8 3.2-3.5 5.5-3.6 5 1.9-3.3 9.9-7.6 13.7-14.8 14.2-5.8-.6-5.9 4-1.6 7 9.6 6.6 16.6-4.8 19.9-11.6 2.3-6.2 5.9-3.3 6.3 1.8 0 6.9-3 12.4-11.3 19.4 6.3 10.1 13.7 20.4 20 30.5l19.2-214L320 139c-2-1.8-8.8-9.8-10.5-11-.7-.6-1-1-.1-1.4s3-.8 4.5-1c-4-4.1-7.6-5.4-15.3-7.6 1.9-.8 3.7-.4 9.3-.6a30 30 0 0 0-13.5-10.2c4.2-3 5-3.2 9.2-6.7a86 86 0 0 1-19.5-3.8 37 37 0 0 0-12-3.4zm.8 8.4c3.8 0 6.1 1.3 6.1 2.9s-2.3 2.9-6.1 2.9-6.2-1.5-6.2-3c0-1.6 2.4-2.8 6.2-2.8"/><use href="#al-a" width="100%" height="100%" transform="matrix(-1 0 0 1 640 0)"/>',
    "HU": '<g fill-rule="evenodd"><path fill="#d43516" d="M0 0h640v160H0z"/><path fill="#fff" d="M0 160h640v160H0z"/><path fill="#388d00" d="M0 320h640v160H0z"/></g>',
    "CZ": '<path fill="#fff" d="M0 0h640v240H0z"/><path fill="#d7141a" d="M0 240h640v240H0z"/><path fill="#11457e" d="M360 240 0 0v480z"/>',
    "PL": '<g fill-rule="evenodd"><path fill="#fff" d="M0 0h640v240H0z"/><path fill="#dc143c" d="M0 240h640v240H0z"/></g>',
    "DE": '<path fill="#fc0" d="M0 320h640v160H0z"/><path fill="#000001" d="M0 0h640v160H0z"/><path fill="red" d="M0 160h640v160H0z"/>',
    "NL": '<path fill="#ae1c28" d="M0 0h640v160H0z"/><path fill="#fff" d="M0 160h640v160H0z"/><path fill="#21468b" d="M0 320h640v160H0z"/>',
    "IE": '<g fill-rule="evenodd" stroke-width="1pt"><path fill="#fff" d="M0 0h640v480H0z"/><path fill="#009A49" d="M0 0h213.3v480H0z"/><path fill="#FF7900" d="M426.7 0H640v480H426.7z"/></g>',
    "DK": '<path fill="#c8102e" d="M0 0h640.1v480H0z"/><path fill="#fff" d="M205.7 0h68.6v480h-68.6z"/><path fill="#fff" d="M0 205.7h640.1v68.6H0z"/>',
    "SE": '<path fill="#005293" d="M0 0h640v480H0z"/><path fill="#fecb00" d="M176 0v192H0v96h176v192h96V288h368v-96H272V0z"/>',
    "FI": '<path fill="#fff" d="M0 0h640v480H0z"/><path fill="#002f6c" d="M0 174.5h640v131H0z"/><path fill="#002f6c" d="M175.5 0h130.9v480h-131z"/>',
    "EE": '<path fill="#1791ff" d="M0 0h640v160H0z"/><path fill="#000001" d="M0 160h640v160H0z"/><path fill="#fff" d="M0 320h640v160H0z"/>',
    "LV": '<g fill-rule="evenodd"><path fill="#981e32" d="M0 0h640v192H0z"/><path fill="#fff" d="M0 192h640v96H0z"/><path fill="#981e32" d="M0 288h640v192H0z"/></g>',
    "LT": '<g fill-rule="evenodd" stroke-width="1pt" transform="scale(.64143 .96773)"><rect width="1063" height="708.7" fill="#006a44" rx="0" ry="0" transform="scale(.93865 .69686)"/><rect width="1063" height="236.2" y="475.6" fill="#c1272d" rx="0" ry="0" transform="scale(.93865 .69686)"/><path fill="#fdb913" d="M0 0h997.8v164.6H0z"/></g>',
    "AT": '<path fill="#fff" d="M0 160h640v160H0z"/><path fill="#c8102e" d="M0 0h640v160H0zm0 320h640v160H0z"/>',
    "SK": '<path fill="#ee1c25" d="M0 0h640v480H0z"/><path fill="#0b4ea2" d="M0 0h640v320H0z"/><path fill="#fff" d="M0 0h640v160H0z"/><path fill="#fff" d="M233 370.8c-43-20.7-104.6-61.9-104.6-143.2 0-81.4 4-118.4 4-118.4h201.3s3.9 37 3.9 118.4S276 350 233 370.8"/><path fill="#ee1c25" d="M233 360c-39.5-19-96-56.8-96-131.4s3.6-108.6 3.6-108.6h184.8s3.5 34 3.5 108.6C329 303.3 272.5 341 233 360"/><path fill="#fff" d="M241.4 209c10.7.2 31.6.6 50.1-5.6 0 0-.4 6.7-.4 14.4s.5 14.4.5 14.4c-17-5.7-38.1-5.8-50.2-5.7v41.2h-16.8v-41.2c-12-.1-33.1 0-50.1 5.7 0 0 .5-6.7.5-14.4s-.5-14.4-.5-14.4c18.5 6.2 39.4 5.8 50 5.6v-25.9c-9.7 0-23.7.4-39.6 5.7 0 0 .5-6.6.5-14.4 0-7.7-.5-14.4-.5-14.4 15.9 5.3 29.9 5.8 39.6 5.7-.5-16.4-5.3-37-5.3-37s9.9.7 13.8.7 13.8-.7 13.8-.7-4.8 20.6-5.3 37c9.7.1 23.7-.4 39.6-5.7 0 0-.5 6.7-.5 14.4s.5 14.4.5 14.4a119 119 0 0 0-39.7-5.7v26z"/><path fill="#0b4ea2" d="M233 263.3c-19.9 0-30.5 27.5-30.5 27.5s-6-13-22.2-13c-11 0-19 9.7-24.2 18.8 20 31.7 51.9 51.3 76.9 63.4 25-12 57-31.7 76.9-63.4-5.2-9-13.2-18.8-24.2-18.8-16.2 0-22.2 13-22.2 13S253 263.3 233 263.3"/>',
    "SI": '<defs><clipPath id="si-a"><path fill-opacity=".7" d="M-15 0h682.6v512H-15.1z"/></clipPath></defs><g fill-rule="evenodd" stroke-width="1pt" clip-path="url(#si-a)" transform="translate(14.1)scale(.9375)"><path fill="#fff" d="M-62 0H962v512H-62z"/><path fill="#d50000" d="M-62 341.3H962V512H-62z"/><path fill="#0000bf" d="M-62 170.7H962v170.6H-62z"/><path fill="#d50000" d="M228.4 93c-4 61.6-6.4 95.4-15.7 111-10.2 16.8-20 29.1-59.7 44-39.6-14.9-49.4-27.2-59.6-44-9.4-15.6-11.7-49.4-15.7-111l5.8-2c11.8-3.6 20.6-6.5 27.1-7.8 9.3-2 17.3-4.2 42.3-4.7 25 .4 33 2.8 42.3 4.8q9.7 2.1 27.3 7.7z"/><path fill="#0000bf" d="M222.6 91c-3.8 61.5-7 89.7-12 103.2-9.6 23.2-24.8 35.9-57.6 48-32.8-12.1-48-24.8-57.7-48-5-13.6-8-41.7-11.8-103.3q17.4-5.6 27.1-7.7c9.3-2 17.3-4.3 42.3-4.7 25 .4 33 2.7 42.3 4.7a284 284 0 0 1 27.4 7.7z"/><path fill="#ffdf00" d="m153 109.8 1.5 3.7 7 1-4.5 2.7 4.3 2.9-6.3 1-2 3.4-2-3.5-6-.8 4-3-4.2-2.7 6.7-1z"/><path fill="#fff" d="m208.3 179.6-3.9-3-2.7-4.6-5.4-4.7-2.9-4.7-5.4-4.9-2.6-4.7-3-2.3-1.8-1.9-5 4.3-2.6 4.7-3.3 3-3.7-2.9-2.7-4.8-10.3-18.3-10.3 18.3-2.7 4.8-3.7 2.9-3.3-3-2.7-4.7-4.9-4.3-1.9 1.8-2.9 2.4-2.6 4.7-5.4 4.9-2.9 4.7-5.4 4.7-2.7 4.6-3.9 3a66 66 0 0 0 18.6 36.3 107 107 0 0 0 36.6 20.5 104 104 0 0 0 36.8-20.5c5.8-6 16.6-19.3 18.6-36.3"/><path fill="#ffdf00" d="m169.4 83.9 1.6 3.7 7 1-4.6 2.7 4.4 2.9-6.3 1-2 3.4-2-3.5-6-.8 4-3-4.2-2.7 6.6-1zm-33 0 1.6 3.7 7 .9-4.5 2.7 4.3 2.9-6.3 1-2 3.4-2-3.4-6-.9 4-3-4.2-2.7 6.7-1z"/><path fill="#0000bf" d="M199.7 203h-7.4l-7-.5-8.3-4h-9.4l-8.1 4-6.5.6-6.4-.6-8.1-4H129l-8.4 4-6.9.6-7.6-.1-3.6-6.2.1-.2 11.2 1.9 6.9-.5 8.3-4.1h9.4l8.2 4 6.4.6 6.5-.6 8.1-4h9.4l8.4 4 6.9.6 10.8-2 .2.4zm-86.4 9.5 7.4-.5 8.3-4h9.4l8.2 4 6.4.5 6.4-.5 8.2-4h9.4l8.3 4 7.5.5 4.8-6h-.1l-5.2 1.4-6.9-.5-8.3-4h-9.4l-8.2 4-6.4.6-6.5-.6-8.1-4H129l-8.4 4-6.9.6-5-1.3v.2l4.5 5.6z"/></g>',
    "HR": '<path fill="#FF0000" d="M0 0h640v160H0z"/><path fill="#FFFFFF" d="M0 160h640v160H0z"/><path fill="#171796" d="M0 320h640v160H0z"/>' + _HR_EMBLEM,
    "BA": '<defs><clipPath id="ba-a"><path fill-opacity=".7" d="M-85.3 0h682.6v512H-85.3z"/></clipPath></defs><g fill-rule="evenodd" clip-path="url(#ba-a)" transform="translate(80)scale(.9375)"><path fill="#009" d="M-85.3 0h682.6v512H-85.3z"/><path fill="#FC0" d="m56.5 0 511 512.3V.3z"/><path fill="#FFF" d="M439.9 481.5 412 461.2l-28.6 20.2 10.8-33.2-28.2-20.5h35l10.8-33.2 10.7 33.3h35l-28 20.7zm81.3 10.4-35-.1-10.7-33.3-10.8 33.2h-35l28.2 20.5-10.8 33.2 28.6-20.2 28 20.3-10.5-33zM365.6 384.7l28-20.7-35-.1-10.7-33.2-10.8 33.2-35-.1 28.2 20.5-10.8 33.3 28.6-20.3 28 20.4zm-64.3-64.5 28-20.6-35-.1-10.7-33.3-10.9 33.2h-34.9l28.2 20.5-10.8 33.2 28.6-20.2 27.9 20.3zm-63.7-63.6 28-20.7h-35L220 202.5l-10.8 33.2h-35l28.2 20.4-10.8 33.3 28.6-20.3 28 20.4-10.5-33zm-64.4-64.3 28-20.6-35-.1-10.7-33.3-10.9 33.2h-34.9L138 192l-10.8 33.2 28.6-20.2 27.9 20.3-10.4-33zm-63.6-63.9 27.9-20.7h-35L91.9 74.3 81 107.6H46L74.4 128l-10.9 33.2L92.1 141l27.8 20.4zm-64-64 27.9-20.7h-35L27.9 10.3 17 43.6h-35L10.4 64l-11 33.3L28.1 77l27.8 20.4zm-64-64L9.4-20.3h-35l-10.7-33.3L-47-20.4h-35L-53.7 0l-10.8 33.2L-35.9 13l27.8 20.4z"/></g>',
    "ME": ('<rect width="640" height="480" fill="#C40308"/>'
           '<rect x="21" y="21" width="598" height="438" fill="none" stroke="#D4AF37" stroke-width="30"/>'
           '<path d="M270,100 Q320,75 370,100 L362,118 Q320,100 278,118 Z" fill="#D4AF37"/>'
           '<circle cx="285" cy="112" r="6" fill="#D4AF37"/><circle cx="355" cy="112" r="6" fill="#D4AF37"/>'
           + _eagle("#D4AF37", 320, 240, 14)
           + '<rect x="304" y="235" width="32" height="42" rx="4" fill="#2F5233"/>'
             '<ellipse cx="320" cy="256" rx="10" ry="12" fill="#D4AF37"/>'),
    "GB-ENG": '<path fill="#fff" d="M0 0h640v480H0z"/><path fill="#ce1124" d="M281.6 0h76.8v480h-76.8z"/><path fill="#ce1124" d="M0 201.6h640v76.8H0z"/>',
    "GB-WLS": '<path fill="#00ab39" d="M0 240h640v240H0z"/><path fill="#fff" d="M0 0h640v240H0z"/><g stroke="#000" stroke-width="1.4"><path fill="#d21034" d="M419 70.8h-.1zm-.1 0a694 694 0 0 0-111.8 75c-17 14.9-12.2 26.7-12.9 40 .6 9-1.9 17.4-7.4 22.4l-37.8 7.6-3.6-10.4c1.1-5.4 5.5-8 14.9-4.7.7-6.8-4.9-9.6-11.3-12-2.3-1.8-5-3-4.7-9-1-13.5 20.6 1 20.8 1s-.8-13.7-10.7-16.4c-5.4-1.9-7.7-7.6-5.6-11.8 4.3-8.7 12.5.6 18.7 1-.2-5.7-1.8-9.7-6.7-14.2-2.6-1.7-9-2.9-9.2-5.6-.1-3.6 6-5.2 14.5-4.2-1.8-5.1-7.5-8.4-15.3-10.8l-4.6-8.1c-2.2-4-3.2-4.2 1.9-11.8 4.5-3 10.6-7.2 15.2-10.1l-5-.6c.6-5.5.7-7.4 2-16.5-5 6.7-11 5.5-16.6 8.2 0 0-15.6 2.8-20.7 9.5l-39.4-2c-8.4 1.1-15.5 3.5-16.9 11.6-19.1 2-39.1.3-53.7 18.5 10-.4 18.6-2.8 29.8-1.4 0 0 9.5.2 11.4 10.3.2.4 3.3.4 3.3.4l3.6 2.8 1.4-3.8 3.2 2.2 1-4.2 3.2 2.2.2-5 4.2 3v-6.7s15.6 0 20.4 10c.2.1-43.7 8-86.1 4.3l12.2-6c-15.4-3.2-30-6-43.6-16.7 5.1 19.4 31.7 42.1 37.2 42l-5.2-9.4 46 2c1.7 5.1 1 10.8 5 15.3 0 0-2.5 8.4 3.2 11.8.2.4 6.7-17 6.7-17s2 4.7 4 7.8c3-15 19.4-17.5 19.4-17.5l3.4 8c-5.1.8-11.5 11.2-8 17-3.5 0-9.6 10.1-7.7 15.6-2.9 2.9-10 6.7-8.3 18.8-5.6 1.2-9 11.5-7.2 22.5-8.8 8.1-6.6 23 1.2 29.1-3.2 3-5.2 5.1-5.2 8.7-3.1-1.1-6-.2-7.3 1.8-3.8-3.9-9.2-7.2-13-3.6-1-4.6-7-9.6-13.5-9a12 12 0 0 0-9-13s-1.5-22.6-8.3-30c-.7-4 .4-6.8 6-10.2 5.7-3 6.9-5.3 6.4-13.9 2.3-5.7 4-11.5-3-15.4.2 6.8-1.8 10-4.6 13-3.3-.4-4.4 3.4-6.6 5-3.1-4.1 6.5-10.6-.6-19.9-.4-.4-5-12-16.3-11.8 5.3 3.1 7.6 8.4 7.6 13.9a41 41 0 0 0-1.8 29.3c-4.7-7-7.4-20.4-11.3-22.7-3.4-.7-5-8.7-18.3-6.4 5.7 1.5 7.6 5.9 9 9.8-3.4 1.8-1.7 6.6.9 9.9-.5 7.7 4.1 12.2 11 15L85.6 237c-2.7-.3-7 10.4-8.6 10.7-2.7 1.7-7.4 6.2-2 7.5-1.6 5.7-3.1 9.2-11.7 10.4 0 0 9 5.4 16.6-3.8 8-.2 5.4-9.8 9.3-14 0-.3 2.3-1.7 5.5-10.2 1.4 7.6 9.2 30.8 26.7 42.3 15.3 16.4 28 31.9 27.8 53.7a54 54 0 0 0 12.3-22.7 89 89 0 0 1 30.8-3.6c-1.8 3.9-3.9 7.6-1.3 10-7.4 2.6-9 8-6 13.3-7.8 5.3-8.3 8.7-8.4 17.5-14.5 18.5-23.4 17.9-37.7 13-4.6-2.7-12-6.6-15.3-4.5-6.1-4.2-15-4.8-16.5 4.6 4.7-3.9 7.4-3.1 11.1.6-.7 1.9-1.3 3.7 1.4 4.8l-3.6 4c-6.6-1-15.6-1-17.9 8.7 3.4-2.9 11-3.5 17-.8l3.5 1.2.4 4.6s-9-1.4-11.4 13.3c8.4-9 14.4-6.7 14.4-6.7 3.3 4.8 15.3 4.1 24-3.8 12.1-6.8 15.7 3 23.5-3.4 6.5-4.8 14.2-1.6 19.5 4 6.1 2.3 12.5 4.2 17.5 0 0 0 6.2-3.9 12.3 2.4 0-7-5-10.9-11.8-11l-2-2c-6.5-1.4-13.7-.8-19.4-4a58 58 0 0 1 14.1-27c9.3-10 16.2-14.6 28-29.9-.5 8.7 6.1 18.3 9.6 27 0 0 7-11.1 8-20.3.3 0 8.9-4.4 12.5-8.3 7.8 4.9 20.4-3.8 28.6-11 5 2 8.9 1.8 14.7 0-4.7 9.6 2.7 18.5 14.5 22.2 1 8.4 9.6 10.2 22.5 10.2.6 5 8.3 5.7 8.3 5.7-5 2.2-7.4 4.5-7.3 9.6-5 0-8.7 1.3-10 7-6.9.2-13.9.7-19.8 4-6.3-.9-14-3.5-18.9-8.6-2.5-2.1-3.2-5.2-7.6-6.4-2.8-3.3-6.2-2.6-7.3.6-2.9-2.3-13.8-3.3-15.7 7 5.2-3.7 9.7-5.1 13-.5-1.8 3.1 4.2 5 9.4 6.2 3.7.2 10.2 3.6 12.2 9.2a20 20 0 0 1-16.7-2.6 11 11 0 0 0-13-.8c-4.4-2.8-14.7 2.5-15.1 10.9 4.3-4 8.3-6 12.3-3.4-2 .4-1.3.6-1 1.8l10 5.8c-5 1.3-9.6 3.3-7.4 12.5 0 0 4-8 13-5 .2-.3 1.3 2.8 3.9.7 3.9-4.4 12.8-6.4 20.7-7.2 6.3-.7 12.6-2.6 18 1 5-2.5 10.4-4.2 16-.2 6.6 2 11.4 9.8 19.7 6.3 4.2-3 9.3-3 14.5 2.8 0-7.4-5.5-9.9-13.3-11.5l-5.4-3.2c-5-.8-10 .1-15.1-2.3a92 92 0 0 0 57.7-42.4l12.5 4.4c3 .2 3.2 1.2 9.3 3 .2-8.9-3.7-18.1-19.8-19l-21-8c-4.6-4.8-6.6-14.9-.9-20.8 5.6-5 6.6-4.4 10.3-10.5 4.5-.4 8.7 4.2 12.8 4.2 2 5.9 13.4 11 20.6 9.3 4.5 4 13 6.2 22.5 3a18 18 0 0 0 20.5 3c2.2 2.2 6.8 4 12 2.8.5 0 2.8 5.8 8.5 7.9-2.5 2.4-1 13 1.7 16.9a17 17 0 0 0-.9 12.7c-5.8 3.7-7 6.5-4.4 12.8-7.6 12.3-16.7 13.7-25.3 10l-9.3-6-9.8-9.6c-1.7-1.6-5.2-2-5.9 1.4 0 0-12.6-2.8-13.7 7.9 5.3-5.1 12.7-.6 12.7-.4s-1.8 1.4-.4 3.4c.3-.3 9.3 3.3 17.2 6.7 4.3 1.7 5.3 2.2 7.2 3.2l-7.2-3.2a33 33 0 0 0-11-2.9c-4.4-.4-9.2-1-11.4 2.4-4.8 2-12.4 3.7-12 12.7 3.2-5.4 7.7-5.1 13.4-4.6l-.4 1.2c6.2 2.8 5-.8 10.8-1.3a44 44 0 0 1 15.3 2.5c-4.5 1.3-10.7.7-13.6 4-.6 1-2.5.6-1.6 3.2 0 0-9-.2-11.3 12 9-5.7 15.9-5.5 16-5.5l2.9.6 11-7.3c.3 0 10.6-4.6 15.3.6 4.2 2 8.6 2.2 13-.4 8.4-3.7 16.3-4 24 1.2l7.1 4.2 3-2s8-2.2 13.8 4.9c-2.4-12.3-11.2-12.7-11.2-12.7l-2-1.8-12.4-4.9c-1.9-4.5-6.4-8-1.9-13.4 4.7-23.1 10.2-40.4 1.2-63.8 8.4 3.6 14.7 14.8 25.2 10.9 0-9.4-34.6-27.3-61-41.6C508 264 560 232.1 540 191.5l9.4-29.4c4.5 9 13.5 15.8 21.6 18.7-6.7-12.7-10.5-51.6-6.7-78.4a627 627 0 0 1-57.1 60c10 2.4 18.9.7 28.6-.5l-8.2 17c-26.6-15.7-57.8-4-58 16.8.9 24.2 30.8 27.7 48.1 19.2-3.4 22.1-54.2 14-54.2 14-18-6.2-35.1-5.2-54-5 3.9-12.1 25.7-22.9 42.4-18.1-23.3-26.2 3.3-58.7 35.4-68.6-35-11.6-4.9-38.3 21.3-57.4 0 0-75.3 31.7-82.2 31.6-21.4-1.6-15.6-27-7.4-40.6zm-236.4 30.4q2.8 0 5.5.6c3.4.9 7.5 1.3 7.5 2.4-1.6 2.6-5.5 5.7-9.3 5.6s-6-2.5-7.2-8.2q.8-.4 3.5-.4zm317 89.4c5 0 10.9 2 16.6 8.2-2.7 8-26.8 12-28.4.2-.5-3.6 4.6-8.3 11.8-8.4z"/><path fill="none" stroke-linejoin="round" d="m207.4 171.2 3.7 5.3m-.2.1s0 7.2 1.5 7.3m-3.3 3.9 3.8 6.3m-10.5 1.6c.2 0 4.7 5.2 4.7 5.2m3.9-4c0 .2 4.2 8.1 4.5 8.1m-10-2.6s1.4 9.6 2.7 9.3m-9 8.3 4.2 6.5m3.7-13.3s2.3 9.1 4.1 8.3m1.9-13.8c.1.2 4.3 6.1 5.4 5.3m-1 2.3 4 8m-10.6-1.8 3.3 9.4m-11-4.6s3 10.1 5.7 8.5m-6.8 5s.2 5.3 2.8 5.6m1.8-8.3c0 .2 2.7 3.8 2.7 3.8m5-10.1 2.1 3.5m4.9-10 3.3 4.1M206 176.7c.1 4.5 7.2-1.6 10-5.4m-13 21s7.7-5.5 13.7-13.8m-16.3 26.9c5.5-1.5 15.6-13.7 17.6-20.2m-18.7 32.3c1.5.7 20.3-13 20.8-22.9M198.8 228c0-.1 17.2-4.4 24.3-23.3M198 242.3s27.5-16.5 29-28.6M412.4 270s-1.8 14.2-16 16.4m20.5 9c.1-.2 13.6-15 10.1-19.5m21.1 5.2s-.2 10.3-8.6 17.4m25.4-14.4s.3 12.4-5 17.4m20.4-10s-6 11.7-8.1 12.9m7.9 7.8s7.8 2 10.3-3.2m-8.3 20.1s7.2 1.3 10.6-5.6m-11.4 18.7s5.9 5 9.9-1.6m-94-94.4s-.7 25.3 34.8 30.4c39.7 11 58.5 5.2 60.8 49.7-1.5 17-3.6 36-16 28.7m-117.4-85.5s5.7 10.1 12.5 9.4c9-2.6 12.3 2.9 12.3 2.9m-49-2.2s15 7.3 27.7-4.5m-26-6c1.3 17.5-20.1 27.5-28.6 25.8m29.6 41c.1 0 11.6-6.8 9.3-11.6m-32.1 1.5c.3-.4 19.3-2.2 22.8-9m-31.6-19s26.9.2 28.7 5.1m7-21s-26.2 44.9 22.2 44.9m-50-45.5s-5.6 16.7-13.6 22.4m-14.2-28.2s9.7 18.8 0 28.1M261 280.8c.1.3 3.1 26.7-3.5 34.2m-9.2-33.4s1 16.8-4 22.8 1.2 18.4 1.2 18.4m-60.5 8s3.6 6.3 8.5 4.1m-2.5-17.8s8 3.5 10.7 2.2m-2-30.4s-11.8 3.3-7.3 17.3c6.8 5.5 13.4 4.6 13.4 4.6m-29.4 37.4c-.1 0 1.4 11 9 2.7 5.3-11.2 22-42.6 25.9-53.4m7.8-5.1s-8.1-6.3-7.8 2.5c-.2 5.5 2.5 6.8 2.5 6.8.3 4 3.8 9.6 6.6 4.5 1.2-5-.8-7.2-.8-7.2m4.7-9c-7.3-.4-11.3 15.7 2.8 5.6m4.8-11s-1.8 2.5-4.7-.2c-1.5-2.6-6.8 12 2.5 12.5 1.7-4.3 6.8-5.5 6.8-5.5m4.4-13.8s-4.2 2-5.7 1.7c-5 1.1-4 12.8 2.3 12.1 2.2-2.5 4.5-6 4.5-6m-40.3-23c-.2 0-16.5 25.7 9.1 32.5m198-71s-10 8.4-.7 22c-31-.5-47.5 13.8-48.8 23.4-39.4-2.8-32.2 8.8-45 12.6-17.1-14.3-42.2-6.3-40.6 8-11.4-16.1-29-8.3-31.2-4.3s-1.3-19.8-1.3-19.8-11.5 5.2-19.4 14.6v-19.9c-9.6 2-18.9 2-28.8 1.8m-25.9-7.3s14.3 8 32-2.8M166 226.3s11 10 32 6.8m-25-29.7s2.4 8.1 26.3 8.6M181 184.6s9 11 21.2 9.3m-13.5-25s3.5 6 16.8 7m-9-24.5s7 7.6 15 6.3M238 89.3s3.1-3 8.3-1.5m-10.5 17.8s-9.6-.3-9-4c.8-4.4 10.2-7.5 10.2-7.5s12.5-8 14.4-10.8m-56.6 44 12.2 23.3 5.8-8.8 3 6 5-8.7 8.6 5.5-3.2-10.7 7.2-.5s-2-5.1-8.4-6.2c1.7-1.3 7.7-5.3 7.7-5.3s-3.4-4-8.8-4.1c1.8-1.9 4.2-6.5 4-6.5l-5.3-1.2s12.2 4 21.6-1.6M221 89.7c.1.1-.7 4.8-3.3 7.5m-43.7 5.3s7.5-2 13.1-.9 13.1 3.2 13.1 3.2 9-1.2 11.9-3.3m-56.8 6s-1 3.6-1.4 6c0 1.7-5.5 4-5.5 4m10.3-17.4s4.8 6 5 9.5c.1 3.4-3.6 6-3.6 6M109 141l-5-8 4.5-1.6m90.5 121c-4-5.2 3-84.2 17.7-104.8-5.1 37.2 12 75.2 16.3 75m-79-97s6.8 2.5 20.7-8.6m18.9 26.8 10 .1m300.3-62s-166.7 77.8-169.1 82c28.1-8.6 147.5-28.5 150.4-26.8-7 1.7-151.9 35-158.7 43 36.2-1.2 111.9 11.6 123.8 24C424.5 198.3 347.6 187 324 192c17.2 4.1 83.2 46.8 83.2 53.6-10-9.5-89.3-42.2-92.4-39 18.2 10.9 43.9 51.4 43.9 61.3-5.3-8.4-51.2-57.7-53.9-54.5 4.9 6.7 14.5 64.9 9.6 67.6 0-7-17.8-58-19.3-59.4-3.6 1-26.3 62-21.8 67.8-3-20.4.5-63 6-61.3-10 1.5-41.7 43.4-38.3 50 1-10.5 2.4-17.4 20.4-52.1-20 1.2-61.2 27.1-68.2 36.4 5.6-16.5 40.5-44.4 55.8-46.4m72-60.7c17.6-9.8 72-29.7 108.4-44.4m-142.6 97s12-.2 24-32.8c11.8-44.6 105.7-94.3 107.6-103.6M128 252.8s-2.8 6-6.2 7.6m19.7 1.4s-3.7 7.2-4.6 10.6m17.5-7s3 9.8.5 14.4m-36.4-40.1c-9.4 5.3 5.4 39 50.1 42.2m-7.2-18.2s-1.2 6 7.2 18c-2.4 13.4 10.2 23.9 15.2 25.6m-26-164.2 1.4-3.6 1.5 4 2.5-.1 1.6-4 1.4 4h2.4l1.5-4.4 2.3 4.2h2l1.5-5 3 3.6 1.2-.4 1-5.2 3.1 3.6 1-.5 1.4-5 2.5 3.7 1.3-.4 1.2-4.3 2.4 4m-39 6.2 18.8-.3c6 0 15.8-8.3 26.7-5.7m-84.9 46s3.1 6.8 7.4 3m-14.6 1.5s-6 16.2 1.2 20m-9.8-37.8s0 3.8 8-2m-32.5 86.7s6.3 2 5.3 6.7m-3-80.8s4 1.9 7.8-4m34.2 189.7c6.1-.4 7.5 2.4 13 2.4 6.6.2 12.9-2.4 21-4.7m53.1 15c-.2 0-3 5.8-.5 8.7m-87.5-8.2s9.8-8 15-3.1c4.9 1.7 7.6 1.4 7.6 1.4m-17.5-21.3s2.4 6.2-5.6 5.3m-2.4 9s5.1 3.2-.7 7.5m3.8 5.8s7 1 2.9 6.7M346 341.6s19 2 20 3.4c2.2-2.3 19.2-16.2-1.7-18.1a19 19 0 0 1-18.3 14.7zm-6.8 9.5c7.1 5.7 4.2 9.1 26.6-5.9m-36.8 13s10.5 11.4 18.2-2.4m-38.3 6.5-14.3 7.5M269 380.3s8.7-7.4 12.7-3.5 21.3-3.4 21.3-3.4M275.5 348s3 6-2.8 6.7m-8.5 11.9s3 5.6-2.8 7m9.5 8.1s9 .5 5.8 7.3m78.4-8.5s-5 4.2-1.3 9m73-39s5.7 2.8-1.1 7.5m-5.7 9.9s4.3 4.5 1.4 8.2m10.6 9s5.9 1.7 5.2 6.6m77.8-11s-5 3.7-2.3 8.4M427 236.3c11.8-1.4 28.8 25 37.5 30.1m51.9-67.4s6 5.3.7 18m10.4-38.2c1.7 1.3 8.1 4.8 12.4 12.8m4.1-52.2-8.3 22.5m17.6-23.6s-1.6 20-4 24M516 198.8c-2.7 8-26.8 12-28.4.2-.9-6 14.2-15.3 28.4-.2z"/><path stroke-linejoin="round" d="m182.3 101.3 9.3 1.7s-6.5 8.8-9.3-1.7z"/></g>',
    # the red St Patrick's saltire is genuinely counter-changed against the
    # white St Andrew's saltire, not one symmetric X -- real flag-icons GB
    # construction, verified against the "red always follows white
    # clockwise" rule (Flag Institute / jdawiseman.com/papers/union-jack).
    "GB": '<path fill="#012169" d="M0 0h640v480H0z"/><path fill="#FFF" d="m75 0 244 181L562 0h78v62L400 241l240 178v61h-80L320 301 81 480H0v-60l239-178L0 64V0z"/><path fill="#C8102E" d="m424 281 216 159v40L369 281zm-184 20 6 35L54 480H0zM640 0v3L391 191l2-44L590 0zM0 0l239 176h-60L0 42z"/><path fill="#FFF" d="M241 0v480h160V0zM0 160v160h640V160z"/><path fill="#C8102E" d="M0 193v96h640v-96zM273 0v480h96V0z"/>',
}

COUNTRY_FLAG_CODE = {
    "France": "FR", "Spain": "ES", "Switzerland": "CH", "Italy": "IT",
    "Albania": "AL", "Hungary": "HU", "Czechia": "CZ", "Poland": "PL",
    "Germany": "DE", "Netherlands": "NL", "Ireland": "IE", "Denmark": "DK",
    "Sweden": "SE", "Finland": "FI", "Estonia": "EE", "Latvia": "LV",
    "Lithuania": "LT", "Austria": "AT", "Slovakia": "SK", "Slovenia": "SI",
    "Croatia": "HR", "Bosnia and Herzegovina": "BA", "Montenegro": "ME",
}
UK_CITY_FLAG_CODE = {
    "London": "GB-ENG", "Oxford": "GB-ENG", "Liverpool": "GB-ENG",
    "Manchester": "GB-ENG", "Chinley": "GB-ENG",
    "Betws-y-Coed": "GB-WLS", "Abergavenny": "GB-WLS",
    "Belfast": "GB",
}


def _flag_code(city: str, country: str) -> str:
    if country == "United Kingdom":
        return UK_CITY_FLAG_CODE.get(city, "GB")
    return COUNTRY_FLAG_CODE.get(country, "")


def _flag_defs() -> str:
    """One hidden sprite sheet of <symbol>s, meant to be emitted once. Each
    flag's path data lives here exactly once regardless of how many stops
    use it; every occurrence after is a cheap <use>. viewBox is 640x480 (4:3)
    to match the real flag artwork natively -- nothing gets rescaled."""
    symbols = "".join(
        f'<symbol id="flag-{code}" viewBox="0 0 640 480">'
        f'<clipPath id="clip-{code}"><rect width="640" height="480" rx="46"/></clipPath>'
        f'<g clip-path="url(#clip-{code})">{shape}</g>'
        f'<rect x="13" y="13" width="614" height="454" rx="36" fill="none" '
        f'stroke="currentColor" stroke-width="26"/>'
        f'</symbol>'
        for code, shape in FLAG_SHAPES.items())
    return f'<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>{symbols}</defs></svg>'


def flag_html(city: str, country: str, cls: str = "flag") -> str:
    code = _flag_code(city, country)
    if not code:
        return ""
    return (f'<svg class="{cls}" viewBox="0 0 640 480" role="img" aria-label="{esc(country)}">'
            f'<title>{esc(country)}</title><use href="#flag-{code}"/></svg>')

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


def _home_free_legs(d: dict):
    """Legs with neither endpoint in the home country. The transit chart
    leaves the transatlantic bookend flights out -- they're not really
    "exploring Europe" -- matching what the map already shows, since
    home-country stops are filtered before it ever draws a leg. Train stats
    and the flights/km counts elsewhere are unaffected (they use the full,
    unfiltered legs)."""
    legs = d["legs"]
    if legs.empty:
        return legs
    home = (legs["from_country"] == A.HOME_COUNTRY) | (legs["to_country"] == A.HOME_COUNTRY)
    return legs[~home]


def _trip_for_day(day, trips):
    for tid, row in trips.iterrows():
        if row["start"].date() <= day <= row["end"].date():
            return tid
    return None


def _transit_columns(d: dict):
    """(span, columns) for the transit day_strip, train bars colour-coded
    per trip (trip1/trip2 are far enough apart on the calendar that this
    never reads ambiguously) -- shared by the homepage chart and the
    README's exported svg so both stay in sync."""
    span = A.active_span(d)
    tl = A.transit_by_day(d, _home_free_legs(d))
    cols = []
    if span and not tl.empty:
        trips = d["trips"]
        for day, r in tl.iterrows():
            stack = []
            tr = float(r.get("train", 0))
            if tr > 0:
                stack.append((tr, _trip_for_day(day, trips) or "accent", 0.9))
            other = float(sum(v for m, v in r.items() if m != "train"))
            if other > 0:
                stack.append((other, "ink", 0.28))
            if stack:
                cols.append((day, stack))
    return span, cols


def transit_movement(d: dict) -> str:
    ts = A.train_stats(d)
    if not ts.get("has_data"):
        return ""
    span, cols = _transit_columns(d)
    strip = day_strip(span, cols, baseline_label="hours in transit, by day") if cols else ""
    legend = ('<div class="key">'
              '<span class="k"><i class="split" style="background:'
              'linear-gradient(90deg,var(--trip1) 50%,var(--trip2) 50%);opacity:.9"></i>trains</span>'
              '<span class="k"><i style="background:var(--ink);opacity:.28"></i>other transit</span>'
              '</div>') if cols else ""
    ov = [f'{ts["rail_legs"]} trains']
    mb = A.mode_breakdown(d)
    if not mb.empty:
        for mode, label in (("bus", "buses"), ("flight", "flights"), ("ferry", "ferries")):
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
            f'<span class="co">{flag_html(r["city"], r["country"])}</span>'
            f'<span class="nn">{r["nights"]}&#8202;n</span></li>'
            for r in stints)
        blocks.append(f'<div class="itin-trip"><p class="tag {tid}-tag">{esc(names.get(tid, tid))}</p>'
                      f'<ol class="itin">{rows}</ol></div>')
    divider = '<div class="year-fade" aria-hidden="true"></div>'
    return (f'<section class="movement">{_flag_defs()}<p class="tag">Stops</p>'
            f'{divider.join(blocks)}</section>')


def tgtg_movement(d: dict) -> str:
    tg = A.tgtg_summary(d)
    if not tg.get("count"):
        return ""
    countries = tg.get("by_country")
    country_grid = ""
    if countries is not None and not countries.empty:
        # all UK entries here happen to be London -- flag it England rather
        # than the generic union flag, matching how Stops handles the UK.
        cells = "".join(
            '<div class="tgtg-country">'
            + flag_html("London" if c == "United Kingdom" else "", c, cls="flag tgtg-flag")
            + f'<p class="tgtg-count">{n}</p></div>'
            for c, n in countries.items())
        country_grid = f'<div class="tgtg-countries">{cells}</div>'

    paul = tg.get("paul_count") or 0
    shoutout = (f'<p class="caption">&#129360; <b>Special shoutout to Paul&rsquo;s in Nice</b></p>'
                f'<p class="paul-address">3 Bd Victor Hugo, 06000 Nice, France</p>') if paul else ""

    return f"""
<section class="movement">
  <p class="tag">Too Good To Go</p>
  <div class="tgtg-about">
    <img class="tgtg-logo" src="assets/togo-logo.png" alt="Too Good To Go logo">
    <p class="tgtg-blurb">Too Good To Go is an app that lets you buy unsold food nearing
    its sell-by date from nearby restaurants, bakeries and grocery stores at a steep
    discount, right before it would otherwise be thrown out.</p>
  </div>
  <p class="statement"><b>{tg['count']} bags</b> rescued across {tg['cities']} cities.</p>
  {country_grid}
  {shoutout}
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
.tag{{font-size:13px;font-weight:700;color:var(--ink);margin:0 0 20px}}
.trip1-tag{{color:{TRIP_COLOR['trip1']}}}
.trip2-tag{{color:{TRIP_COLOR['trip2']}}}
.map-link{{font-family:var(--serif);font-size:clamp(18px,2.6vw,22px);margin:0 0 18px}}
.map-link a{{color:#97ac89;text-decoration:underline;text-decoration-color:currentColor;
  text-underline-offset:4px}}
.map-link a:hover{{color:var(--ink)}}
.statement{{font-family:var(--serif);font-size:clamp(17px,2.2vw,19px);line-height:1.4;
  font-weight:400;max-width:32ch;margin:0 0 30px;color:#97ac89}}
.statement b{{font-weight:500}}
.tgtg-about{{display:flex;align-items:center;gap:16px;margin:0 0 26px}}
.tgtg-logo{{width:52px;height:52px;border-radius:11px;flex:none;object-fit:cover}}
.tgtg-blurb{{font-family:var(--serif);font-size:14.5px;line-height:1.5;color:var(--dim);
  max-width:52ch;margin:0}}
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
.itin .co{{line-height:1;display:flex}}
.flag{{width:20px;height:15px;flex:none;color:var(--rule)}}
.itin .nn{{font-family:var(--mono);font-size:9.5px;color:var(--dim);letter-spacing:.08em}}
.tgtg-countries{{display:flex;gap:14px;margin:24px 0 0;overflow-x:auto;padding-bottom:2px}}
.tgtg-country{{display:flex;flex:none;flex-direction:column;align-items:center;gap:6px}}
.tgtg-flag{{width:24px;height:18px}}
.tgtg-count{{font-family:var(--mono);font-size:12px;color:var(--ink);text-align:center;margin:0}}
.paul-address{{font-size:11px;color:var(--dim);margin:4px 0 0 23px}}
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
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,500;1,9..144,400&family=Instrument+Sans:wght@400;500&family=Spline+Sans+Mono:wght@400;500;700&display=swap">
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
    span, cols = _transit_columns(d)
    if cols:
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
