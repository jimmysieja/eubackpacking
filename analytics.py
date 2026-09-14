"""
eubackpacking — analytics.

Loads the flat files in ``data/`` and computes every statistic the dashboard
shows. No network, no state — the numbers are a pure function of what's in
``data/``.

    python analytics.py            # print the full text report

Importable:

    from analytics import load_all, overview, train_stats
    d = load_all()
"""

from __future__ import annotations

import sys
import math
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent
DATA = ROOT / "data"

HOME_COUNTRY = "USA"          # bookend stops — excluded from "countries visited"

# Countries actually set foot in across both trips, by the traveller's own count
# (includes day trips, walk-ins like Vatican/Monaco, and countries only passed
# through by train — border hops and airport layovers the stop data doesn't
# fully capture). Hand-maintained; bump it when a trip is added.
COUNTRIES_VISITED = 28

# transport words accepted in the stops files (English or French)
MODE_ALIASES = {
    "": "", "train": "train", "bus": "bus", "flight": "flight", "plane": "flight",
    "ferry": "ferry", "boat": "ferry", "car": "car", "walk": "walk", "bike": "bike",
    "avion": "flight", "bateau": "ferry", "voiture": "car", "vélo": "bike",
}
RAIL_MODES = {"train"}
# hops made on foot (Rome <-> Vatican City) aren't journeys: not counted, drawn or keyed
ON_FOOT = {"walk"}

# rough effective speeds (km/h) and fixed per-journey overhead (h) used to
# ESTIMATE journey time from route distance — there are no stopwatch numbers in
# the data. Tune to taste; everything derived from these is labelled "estimated".
SPEED_KMH = {"train": 75, "bus": 55, "ferry": 32, "car": 70, "flight": 650, "bike": 15, "walk": 5}
OVERHEAD_H = {"train": 0.4, "bus": 0.35, "ferry": 1.0, "car": 0.15, "flight": 2.0, "bike": 0.0, "walk": 0.0}

MODE_ORDER = ["train", "bus", "ferry", "flight", "car", "bike", "walk"]


# --------------------------------------------------------------------------- #
# loaders
# --------------------------------------------------------------------------- #
def load_trips() -> pd.DataFrame:
    df = pd.DataFrame(yaml.safe_load((DATA / "trips.yml").read_text(encoding="utf-8")))
    df["start"] = pd.to_datetime(df["start"])
    df["end"] = pd.to_datetime(df["end"])
    df["days"] = (df["end"] - df["start"]).dt.days + 1
    return df.set_index("id")


def _parse_annotations(raw: dict) -> dict:
    # `layover:` timestamps in the yml are kept there as a record only
    out = {}
    for city, v in (raw or {}).items():
        if isinstance(v, str):
            out[city] = {"label": v, "kind": "stop"}
        elif isinstance(v, dict) and (v.get("label") or v.get("kind")):
            out[city] = {"label": v.get("label", ""), "kind": v.get("kind", "stop")}
    return out


def load_annotations() -> dict:
    """Per-trip stop call-outs from data/annotations_<trip>.yml, keyed
    {trip_id: {city: {label, kind, ...}}}. A bare data/annotations.yml (no trip
    suffix) is still read and treated as trip2's."""
    out = {}
    legacy = DATA / "annotations.yml"
    if legacy.is_file():
        out["trip2"] = _parse_annotations(yaml.safe_load(legacy.read_text(encoding="utf-8")))
    for p in sorted(DATA.glob("annotations_*.yml")):
        tid = p.stem.split("_", 1)[1]
        out[tid] = _parse_annotations(yaml.safe_load(p.read_text(encoding="utf-8")))
    return out


def load_coords() -> pd.DataFrame:
    c = pd.read_csv(DATA / "coords.csv")
    c["lat"] = pd.to_numeric(c["lat"], errors="coerce")
    c["lon"] = pd.to_numeric(c["lon"], errors="coerce")
    return c.drop_duplicates("city").set_index("city")


def load_stops(trips: pd.DataFrame | None = None) -> pd.DataFrame:
    trips = load_trips() if trips is None else trips
    coords = load_coords()
    frames = []
    for tid, row in trips.iterrows():
        path = DATA / row["stops"]
        if not path.is_file():
            continue
        s = pd.read_csv(path)
        s["trip"] = tid
        frames.append(s)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df["transport"] = (df["transport"].fillna("").astype(str).str.strip().str.lower()
                       .map(lambda m: MODE_ALIASES.get(m, m)))
    df["arrival_date"] = pd.to_datetime(df["arrival_date"], errors="coerce")
    df["departure_date"] = pd.to_datetime(df["departure_date"], errors="coerce")
    df["nights"] = (df["departure_date"] - df["arrival_date"]).dt.days
    df["lat"] = df["city"].map(coords["lat"])
    df["lon"] = df["city"].map(coords["lon"])
    df["is_home"] = df["country"] == HOME_COUNTRY
    return df


def _haversine(lat1, lon1, lat2, lon2) -> float:
    if any(pd.isna(v) for v in (lat1, lon1, lat2, lon2)):
        return float("nan")
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def load_legs(stops: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per city-to-city journey, with an ESTIMATED duration."""
    s = load_stops() if stops is None else stops
    if s.empty:
        return pd.DataFrame()
    s = s[s["arrival_date"].notna()].sort_values(["trip", "stop_number"])
    rows = []
    for tid, grp in s.groupby("trip"):
        recs = grp.to_dict("records")
        for prev, cur in zip(recs, recs[1:]):
            mode = cur["transport"] or "train"
            if prev["city"] == cur["city"] or mode in ON_FOOT:
                continue
            km = _haversine(prev["lat"], prev["lon"], cur["lat"], cur["lon"])
            hrs = float("nan")
            if not math.isnan(km):
                hrs = max(0.2, km / SPEED_KMH.get(mode, 60) + OVERHEAD_H.get(mode, 0.3))
            rows.append({
                "trip": tid, "date": cur["arrival_date"], "mode": mode,
                "from": prev["city"], "to": cur["city"],
                "from_country": prev["country"], "to_country": cur["country"],
                "km": km, "est_hr": hrs,
            })
    return pd.DataFrame(rows)


def load_tgtg() -> pd.DataFrame:
    """Too Good To Go pickups, one row per bag: data/tgtg_<trip>.csv with columns
    date, city, store, note (store/note optional — blank where not logged)."""
    frames = []
    for p in sorted(DATA.glob("tgtg_*.csv")):
        tid = p.stem.split("_", 1)[1]
        t = pd.read_csv(p)
        if t.empty:
            continue
        t["trip"] = tid
        frames.append(t)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df.columns = [c.strip().lower() for c in df.columns]
    df["date"] = pd.to_datetime(df.get("date"), errors="coerce")
    for col in ("city", "store", "note"):
        df[col] = df[col].fillna("").astype(str).str.strip() if col in df else ""
    return df.sort_values("date").reset_index(drop=True)


def load_rail_overrides() -> dict:
    """Real per-trip rail totals from data/rail_<trip>.yml (Eurail app), if any."""
    out = {}
    for p in sorted(DATA.glob("rail_*.yml")):
        tid = p.stem.split("_", 1)[1]
        out[tid] = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return out


def load_all() -> dict:
    trips = load_trips()
    stops = load_stops(trips)
    return {
        "trips": trips,
        "stops": stops,
        "legs": load_legs(stops),
        "tgtg": load_tgtg(),
        "rail": load_rail_overrides(),
        "generated": dt.datetime.now(dt.timezone.utc),
    }


# --------------------------------------------------------------------------- #
# derived views
# --------------------------------------------------------------------------- #
def sleeps(d: dict) -> pd.DataFrame:
    """Deduped 'places you actually slept' — the real itinerary, home excluded."""
    s = d["stops"]
    if s.empty:
        return s
    s = s[(~s["is_home"]) & (s["nights"] > 0)].copy()
    return s.drop_duplicates(["trip", "city", "arrival_date", "departure_date"])


def day_trips(d: dict) -> pd.DataFrame:
    """Stops with no overnight — and where you never slept on that trip either."""
    s = d["stops"]
    if s.empty:
        return s
    dt_ = s[(~s["is_home"]) & (s["nights"].fillna(0) == 0) & (s["arrival_date"].notna())]
    slept = set(zip(sleeps(d)["trip"], sleeps(d)["city"]))
    return dt_[~dt_.apply(lambda r: (r["trip"], r["city"]) in slept, axis=1)]


# --------------------------------------------------------------------------- #
# metrics
# --------------------------------------------------------------------------- #
def overview(d: dict) -> dict:
    trips = d["trips"]
    sl = sleeps(d)
    out = {
        "trip_days": int(trips["days"].sum()),
        "n_trips": len(trips),
        "first_day": trips["start"].min(),
        "last_day": trips["end"].max(),
        "n_countries_visited": COUNTRIES_VISITED,
    }
    if not sl.empty:
        out["n_cities"] = int(sl["city"].nunique())
        out["n_countries"] = int(sl["country"].nunique())
        out["nights_logged"] = int(sl["nights"].sum())
        out["countries"] = sorted(sl["country"].unique().tolist())
        out["cities_by_trip"] = sl.groupby("trip")["city"].nunique().to_dict()
    else:
        out.update(n_cities=0, n_countries=0, nights_logged=0, countries=[], cities_by_trip={})
    return out


def tgtg_summary(d: dict) -> dict:
    t = d["tgtg"]
    if t.empty:
        return {"count": 0}
    res = {"count": int(len(t)), "cities": int(t.loc[t["city"] != "", "city"].nunique())}
    stores = t.loc[t["store"] != "", "store"]
    if not stores.empty:
        res["stores"] = int(stores.nunique())
    res["by_city"] = t.groupby("city").size().sort_values(ascending=False)
    return res


def train_stats(d: dict) -> dict:
    """Rail summary. Uses the real Eurail-app totals in d['rail'] when present,
    otherwise falls back to the distance-based estimate from the legs."""
    legs = d["legs"]
    rail_ovr = d.get("rail", {})
    res = {"has_data": (not legs.empty) or bool(rail_ovr)}

    if rail_ovr:
        res["estimated"] = False
        res["rail_legs"] = int(sum(o.get("trains", 0) for o in rail_ovr.values()))
        res["rail_hours"] = float(sum(o.get("hours", 0) for o in rail_ovr.values()))
        res["rail_km"] = float(sum(o.get("distance_km", 0) for o in rail_ovr.values()))
        res["countries_by_train"] = max((o.get("countries", 0) for o in rail_ovr.values()), default=0)
        lg = next((o["longest"] for o in rail_ovr.values() if o.get("longest")), None)
        if lg:
            res["longest"] = {"from": lg["from"], "to": lg["to"], "hr": float(lg["hours"]),
                              "km": lg.get("km"), "date": lg.get("date")}
    elif not legs.empty:
        res["estimated"] = True
        rail = legs[legs["mode"].isin(RAIL_MODES)]
        res["rail_legs"] = int(len(rail))
        res["rail_hours"] = float(rail["est_hr"].sum(skipna=True))
        res["rail_km"] = float(rail["km"].sum(skipna=True))
        crossed = rail[rail["from_country"] != rail["to_country"]]
        res["countries_by_train"] = int(crossed["to_country"].nunique())
        if not rail["est_hr"].dropna().empty:
            lg = rail.loc[rail["est_hr"].idxmax()]
            res["longest"] = {"from": lg["from"], "to": lg["to"], "hr": float(lg["est_hr"]),
                              "km": float(lg["km"]), "date": lg["date"].date().isoformat()}
    else:
        return res

    if not legs.empty:
        rail = legs[legs["mode"].isin(RAIL_MODES)]
        res["rail_days"] = int(rail["date"].dt.date.nunique())
    res["full_days_equiv"] = res["rail_hours"] / 24.0
    other = 0.0
    if not legs.empty:
        other = float(legs[~legs["mode"].isin(RAIL_MODES)]["est_hr"].sum(skipna=True))
    denom = res["rail_hours"] + other
    res["rail_hour_share"] = res["rail_hours"] / denom if denom else 0.0
    return res


def mode_breakdown(d: dict) -> pd.DataFrame:
    legs = d["legs"]
    if legs.empty:
        return pd.DataFrame()
    g = legs.groupby("mode").agg(
        legs=("mode", "size"),
        hours=("est_hr", lambda s: s.sum(skipna=True)),
        km=("km", lambda s: s.sum(skipna=True)),
        days=("date", lambda s: s.dt.date.nunique()),
    )
    g["estimated"] = True
    # swap in the real Eurail rail totals for the train row
    ts = train_stats(d)
    if not ts.get("estimated", True) and "train" in g.index:
        g.loc["train", ["legs", "hours", "km", "estimated"]] = [
            ts["rail_legs"], ts["rail_hours"], ts["rail_km"], False]
    order = [m for m in MODE_ORDER if m in g.index] + [m for m in g.index if m not in MODE_ORDER]
    return g.reindex(order)


def transport_timeline(d: dict) -> pd.DataFrame:
    legs = d["legs"]
    if legs.empty:
        return pd.DataFrame()
    t = legs.dropna(subset=["est_hr"]).copy()
    return t.pivot_table(index=t["date"].dt.date, columns="mode", values="est_hr",
                         aggfunc="sum", fill_value=0.0)


def active_span(d: dict):
    """(first, last) date with any journey — the axis for the strips."""
    if d["legs"].empty:
        return None
    return d["legs"]["date"].min().date(), d["legs"]["date"].max().date()


def transit_by_day(d: dict) -> pd.DataFrame:
    """Per-day hours in transit by mode. Long hauls listed in rail_<trip>.yml
    `notable:` override the estimate for their day; then the whole train series
    is rescaled so its total matches the real Eurail figure."""
    tl = transport_timeline(d)
    if tl.empty:
        return tl
    tl = tl.copy()
    if "train" not in tl.columns:
        tl["train"] = 0.0
    for o in d.get("rail", {}).values():
        for j in o.get("notable", []):
            day = pd.to_datetime(j["date"]).date()
            if day in tl.index:
                tl.loc[day, "train"] = max(tl.loc[day, "train"], float(j["hours"]))
            else:
                tl.loc[day, "train"] = float(j["hours"])
    tl = tl.fillna(0.0).sort_index()
    ts = train_stats(d)
    if not ts.get("estimated", True):
        cur = tl["train"].sum()
        if cur > 0:
            tl["train"] = tl["train"] * (ts["rail_hours"] / cur)
    return tl


# --------------------------------------------------------------------------- #
# text report
# --------------------------------------------------------------------------- #
def build_report(d: dict) -> str:
    ov, tg, ts = overview(d), tgtg_summary(d), train_stats(d)
    L: list[str] = []
    L.append("eubackpacking — data report")
    L.append("=" * 44)
    L.append(f"{ov['n_trips']} trips · {ov['trip_days']} days · "
             f"{ov['first_day']:%b %Y} – {ov['last_day']:%b %Y}")
    L.append(f"{ov['n_countries']} countries · {ov['n_cities']} cities slept in · "
             f"{ov['nights_logged']} nights")
    if ov["countries"]:
        L.append("  " + ", ".join(ov["countries"]))
    L.append("")

    if tg.get("count"):
        L.append("Too Good To Go")
        L.append("-" * 44)
        line = f"  {tg['count']} bags · {tg['cities']} cities"
        if tg.get("stores"):
            line += f" · {tg['stores']} different stores"
        L.append(line)
        L.append("")

    src = "from the Eurail app" if not ts.get("estimated", True) else "ESTIMATED from route distance"
    L.append(f"Trains  ({src})")
    L.append("-" * 44)
    if ts.get("has_data"):
        pfx = "" if not ts.get("estimated", True) else "~"
        L.append(f"  {pfx}{ts['rail_hours']:.0f} h on trains ({ts['full_days_equiv']:.1f} full days) "
                 f"over {ts['rail_legs']} {'trains' if not ts.get('estimated', True) else 'legs'}")
        line = (f"  {ts['rail_km']:,.0f} km by rail · {ts['rail_hour_share']*100:.0f}% of travel "
                f"time · {ts['countries_by_train']} countries by rail")
        if "rail_days" in ts:
            line += f" · trains on {ts['rail_days']} days"
        L.append(line)
        if "longest" in ts:
            lg = ts["longest"]
            km = f", {lg['km']:,.0f} km" if lg.get("km") else ""
            L.append(f"  longest ride  {lg['from']} → {lg['to']}  {lg['hr']:.1f} h ({lg['date']}{km})")
    L.append("")

    mb = mode_breakdown(d)
    if not mb.empty:
        L.append("By mode  (estimated)")
        L.append("-" * 44)
        L.append(f"  {'mode':<8}{'legs':>6}{'~hours':>9}{'km':>10}")
        for m, r in mb.iterrows():
            L.append(f"  {m:<8}{int(r['legs']):>6}{r['hours']:>9.1f}{r['km']:>10,.0f}")
    L.append("")
    L.append(f"generated {d['generated']:%Y-%m-%d %H:%M UTC}")
    return "\n".join(L)


if __name__ == "__main__":
    print(build_report(load_all()))
