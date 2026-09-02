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

# transport words accepted in the stops files (English or French)
MODE_ALIASES = {
    "": "", "train": "train", "bus": "bus", "flight": "flight", "plane": "flight",
    "ferry": "ferry", "boat": "ferry", "car": "car", "walk": "walk", "bike": "bike",
    "avion": "flight", "bateau": "ferry", "voiture": "car", "vélo": "bike",
}
RAIL_MODES = {"train"}

# rough effective speeds (km/h) and fixed per-journey overhead (h) used to
# ESTIMATE journey time from route distance — there are no stopwatch numbers in
# the data. Tune to taste; everything derived from these is labelled "estimated".
SPEED_KMH = {"train": 75, "bus": 55, "ferry": 32, "car": 70, "flight": 650, "bike": 15, "walk": 5}
OVERHEAD_H = {"train": 0.4, "bus": 0.35, "ferry": 1.0, "car": 0.15, "flight": 2.0, "bike": 0.0, "walk": 0.0}

CATEGORY_ORDER = ["lodging", "food", "transport", "shopping", "activities", "gifts", "misc"]
MODE_ORDER = ["train", "bus", "ferry", "flight", "car", "bike", "walk"]


# --------------------------------------------------------------------------- #
# loaders
# --------------------------------------------------------------------------- #
def load_trips() -> pd.DataFrame:
    df = pd.DataFrame(yaml.safe_load((DATA / "trips.yml").read_text(encoding="utf-8")))
    df["start"] = pd.to_datetime(df["start"])
    df["end"] = pd.to_datetime(df["end"])
    df["days"] = (df["end"] - df["start"]).dt.days + 1
    df["expenses_complete"] = df.get("expenses_complete", False).fillna(False).astype(bool)
    return df.set_index("id")


def load_fx() -> dict:
    return yaml.safe_load((DATA / "fx.yml").read_text(encoding="utf-8"))


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
            if prev["city"] == cur["city"]:
                continue
            mode = cur["transport"] or "train"
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


def load_expenses(trips: pd.DataFrame | None = None) -> pd.DataFrame:
    trips = load_trips() if trips is None else trips
    fx = load_fx()
    frames = []
    for tid, row in trips.iterrows():
        path = DATA / row.get("expenses", f"expenses_{tid}.csv")
        if not path.is_file():
            continue
        e = pd.read_csv(path)
        if e.empty:
            continue
        e["trip"] = tid
        frames.append(e)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df.columns = [c.strip().lower() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["amount"] = pd.to_numeric(df.get("amount"), errors="coerce")
    df["amount_usd"] = pd.to_numeric(df.get("amount_usd"), errors="coerce")
    need = df["amount_usd"].isna() & df["amount"].notna()
    df.loc[need, "amount_usd"] = df.loc[need].apply(
        lambda r: r["amount"] * fx.get(str(r.get("currency", "")).upper(), float("nan")), axis=1)
    df["category"] = df.get("category", "misc").fillna("misc").astype(str).str.strip().str.lower()
    for col in ("city", "country", "description", "currency"):
        if col in df:
            df[col] = df[col].fillna("").astype(str).str.strip()
    return df.sort_values("date").reset_index(drop=True)


def load_all() -> dict:
    trips = load_trips()
    stops = load_stops(trips)
    return {
        "trips": trips,
        "stops": stops,
        "legs": load_legs(stops),
        "expenses": load_expenses(trips),
        "fx": load_fx(),
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


def spend_summary(d: dict) -> dict:
    exp, trips = d["expenses"], d["trips"]
    res = {"by_trip": {}, "complete": {}, "cost_per_day": {}, "total": 0.0, "any_partial": False}
    if exp.empty:
        return res
    by_trip = exp.groupby("trip")["amount_usd"].sum()
    for tid, row in trips.iterrows():
        total = float(by_trip.get(tid, 0.0))
        res["by_trip"][tid] = total
        res["complete"][tid] = bool(row["expenses_complete"])
        res["cost_per_day"][tid] = total / row["days"] if row["days"] else 0.0
        if not row["expenses_complete"] and total > 0:
            res["any_partial"] = True
    res["total"] = float(by_trip.sum())
    res["by_category"] = (exp.groupby("category")["amount_usd"].sum()
                          .reindex(CATEGORY_ORDER).dropna().sort_values(ascending=False))
    res["by_country"] = (exp[exp["country"] != ""].groupby("country")["amount_usd"].sum()
                         .sort_values(ascending=False))
    daily = exp.groupby(exp["date"].dt.date)["amount_usd"].sum()
    if not daily.empty:
        res["priciest_day"] = (daily.idxmax(), float(daily.max()))
        nonzero = daily[daily > 0]
        res["cheapest_day"] = (nonzero.idxmin(), float(nonzero.min())) if not nonzero.empty else None
        res["mean_day"] = float(daily.mean())
    res["tgtg_count"] = int(exp["description"].str.contains("tgtg", case=False, na=False).sum())
    return res


def train_stats(d: dict) -> dict:
    legs = d["legs"]
    res = {"has_data": not legs.empty, "estimated": True}
    if legs.empty:
        return res
    rail = legs[legs["mode"].isin(RAIL_MODES)]
    res["rail_legs"] = int(len(rail))
    res["rail_hours"] = float(rail["est_hr"].sum(skipna=True))
    res["rail_km"] = float(rail["km"].sum(skipna=True))
    res["rail_days"] = int(rail["date"].dt.date.nunique())
    res["full_days_equiv"] = res["rail_hours"] / 24.0
    total_hours = float(legs["est_hr"].sum(skipna=True))
    res["rail_hour_share"] = res["rail_hours"] / total_hours if total_hours else 0.0
    crossed = rail[rail["from_country"] != rail["to_country"]]
    res["countries_by_train"] = int(crossed["to_country"].nunique())
    if not rail["est_hr"].dropna().empty:
        lg = rail.loc[rail["est_hr"].idxmax()]
        res["avg_leg_hr"] = float(rail["est_hr"].mean(skipna=True))
        res["longest"] = {"from": lg["from"], "to": lg["to"], "hr": float(lg["est_hr"]),
                          "km": float(lg["km"]), "date": lg["date"].date().isoformat()}
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
    order = [m for m in MODE_ORDER if m in g.index] + [m for m in g.index if m not in MODE_ORDER]
    return g.reindex(order)


def transport_timeline(d: dict) -> pd.DataFrame:
    legs = d["legs"]
    if legs.empty:
        return pd.DataFrame()
    t = legs.dropna(subset=["est_hr"]).copy()
    return t.pivot_table(index=t["date"].dt.date, columns="mode", values="est_hr",
                         aggfunc="sum", fill_value=0.0)


# --------------------------------------------------------------------------- #
# text report
# --------------------------------------------------------------------------- #
def build_report(d: dict) -> str:
    ov, sp, ts = overview(d), spend_summary(d), train_stats(d)
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

    L.append("Spend")
    L.append("-" * 44)
    for tid, row in d["trips"].iterrows():
        total = sp["by_trip"].get(tid, 0.0)
        tag = "" if sp["complete"].get(tid) else "   (PARTIAL)"
        L.append(f"  {row['name']:<13} ${total:>9,.0f}   ${sp['cost_per_day'].get(tid,0):>5,.0f}/day{tag}")
    L.append(f"  {'TOTAL':<13} ${sp['total']:>9,.0f}")
    if not d["expenses"].empty:
        L.append("")
        for cat, amt in sp["by_category"].items():
            L.append(f"    {cat:<11} ${amt:>8,.0f}")
        if sp.get("priciest_day"):
            L.append("")
            L.append(f"  priciest day {sp['priciest_day'][0]}  ${sp['priciest_day'][1]:,.0f}")
        if sp.get("cheapest_day"):
            L.append(f"  cheapest day {sp['cheapest_day'][0]}  ${sp['cheapest_day'][1]:,.0f}")
        L.append(f"  Too Good To Go bags: {sp['tgtg_count']}")
    L.append("")

    L.append("Trains  (durations ESTIMATED from route distance)")
    L.append("-" * 44)
    if ts.get("has_data"):
        L.append(f"  ~{ts['rail_hours']:.0f} h on trains ({ts['full_days_equiv']:.1f} full days) "
                 f"over {ts['rail_legs']} legs")
        L.append(f"  {ts['rail_km']:,.0f} km by rail · {ts['rail_hour_share']*100:.0f}% of travel "
                 f"time · trains on {ts['rail_days']} days · {ts['countries_by_train']} countries "
                 f"entered by train")
        if "longest" in ts:
            lg = ts["longest"]
            L.append(f"  longest leg  {lg['from']} → {lg['to']}  ~{lg['hr']:.1f} h "
                     f"({lg['km']:,.0f} km, {lg['date']})")
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
