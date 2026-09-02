"""
eubackpacking — analytics.

Loads the static data files in ``data/`` and computes every statistic the
dashboard shows. No network, no secrets, no state — the numbers are a pure
function of what's in ``data/``.

    python analytics.py            # print the full text report

Everything is importable:

    from analytics import load_all, overview, train_stats
    d = load_all()
"""

from __future__ import annotations

import sys
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

# utf-8 stdout so the Windows console doesn't choke on accents / emoji
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent
DATA = ROOT / "data"

# "trains" in the headline sense = intercity heavy rail, not trams/metros.
RAIL_MODES = {"train", "rail"}
URBAN_RAIL = {"tram", "metro", "subway", "u-bahn", "s-bahn"}

CATEGORY_ORDER = ["lodging", "food", "transport", "activities", "shopping", "other"]
MODE_ORDER = ["train", "bus", "flight", "ferry", "tram", "metro", "car", "bike", "walk", "other"]


# --------------------------------------------------------------------------- #
# loaders
# --------------------------------------------------------------------------- #
def _read_yaml(name: str):
    p = DATA / name
    if not p.is_file():
        return []
    return yaml.safe_load(p.read_text(encoding="utf-8")) or []


def load_trips() -> pd.DataFrame:
    df = pd.DataFrame(_read_yaml("trips.yml"))
    if df.empty:
        raise SystemExit("data/trips.yml is empty — define at least one trip.")
    df["start"] = pd.to_datetime(df["start"])
    df["end"] = pd.to_datetime(df["end"])
    df["days"] = (df["end"] - df["start"]).dt.days + 1
    df["expenses_complete"] = df.get("expenses_complete", False).fillna(False).astype(bool)
    return df.set_index("id")


def load_cities() -> pd.DataFrame:
    df = pd.DataFrame(_read_yaml("cities.yml"))
    if df.empty:
        return df
    df["arrive"] = pd.to_datetime(df["arrive"])
    df["depart"] = pd.to_datetime(df["depart"])
    df["nights"] = (df["depart"] - df["arrive"]).dt.days
    for col in ("lat", "lon"):
        df[col] = pd.to_numeric(df.get(col), errors="coerce")
    df["lodging"] = df.get("lodging", "").fillna("").astype(str)
    df["notes"] = df.get("notes", "").fillna("").astype(str)
    return df.sort_values("arrive").reset_index(drop=True)


def _read_csv_pair(stub: str) -> pd.DataFrame:
    frames = []
    for p in sorted(DATA.glob(f"{stub}_*.csv")):
        f = pd.read_csv(p)
        f.columns = [c.strip().lower() for c in f.columns]
        frames.append(f)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def load_expenses() -> pd.DataFrame:
    df = _read_csv_pair("expenses")
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df["amount_usd"] = pd.to_numeric(df["amount_usd"], errors="coerce").fillna(0.0)
    df["category"] = df["category"].str.strip().str.lower()
    for col in ("country", "city", "description", "trip"):
        if col in df:
            df[col] = df[col].fillna("").astype(str).str.strip()
    return df.sort_values("date").reset_index(drop=True)


def load_transport() -> pd.DataFrame:
    df = _read_csv_pair("transport")
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df["mode"] = df["mode"].str.strip().str.lower()
    for col in ("duration_hr", "distance_km", "cost_usd"):
        df[col] = pd.to_numeric(df.get(col), errors="coerce")
    for col in ("from", "to", "operator", "notes", "trip"):
        if col in df:
            df[col] = df[col].fillna("").astype(str).str.strip()
    return df.sort_values("date").reset_index(drop=True)


def load_all() -> dict:
    """Everything the dashboard needs, in one dict."""
    return {
        "trips": load_trips(),
        "cities": load_cities(),
        "expenses": load_expenses(),
        "transport": load_transport(),
        "generated": dt.datetime.now(dt.timezone.utc),
    }


# --------------------------------------------------------------------------- #
# metrics
# --------------------------------------------------------------------------- #
def overview(d: dict) -> dict:
    trips, cities = d["trips"], d["cities"]
    out = {
        "trip_days": int(trips["days"].sum()),
        "n_trips": len(trips),
        "first_day": trips["start"].min(),
        "last_day": trips["end"].max(),
    }
    if not cities.empty:
        out["n_cities"] = int(cities[["city", "country"]].drop_duplicates().shape[0])
        out["n_countries"] = int(cities["country"].nunique())
        out["nights_logged"] = int(cities["nights"].sum())
        out["cities_by_trip"] = cities.groupby("trip")["city"].nunique().to_dict()
        out["countries"] = sorted(cities["country"].unique().tolist())
    else:
        out.update(n_cities=0, n_countries=0, nights_logged=0, cities_by_trip={}, countries=[])
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
    res["by_category"] = (
        exp.groupby("category")["amount_usd"].sum()
        .reindex(CATEGORY_ORDER).dropna().sort_values(ascending=False)
    )
    res["by_country"] = exp.groupby("country")["amount_usd"].sum().sort_values(ascending=False)
    res["by_trip_category"] = exp.pivot_table(
        index="category", columns="trip", values="amount_usd", aggfunc="sum", fill_value=0.0
    )
    return res


def train_stats(d: dict) -> dict:
    tr = d["transport"]
    res = {"has_data": not tr.empty}
    if tr.empty:
        return res
    rail = tr[tr["mode"].isin(RAIL_MODES)]
    res["rail_journeys"] = int(len(rail))
    res["rail_hours"] = float(rail["duration_hr"].sum(skipna=True))
    res["rail_km"] = float(rail["distance_km"].sum(skipna=True))
    res["rail_days"] = int(rail["date"].dt.date.nunique())
    res["rail_cost"] = float(rail["cost_usd"].sum(skipna=True))
    total_hours = float(tr["duration_hr"].sum(skipna=True))
    res["rail_hour_share"] = res["rail_hours"] / total_hours if total_hours else 0.0
    if not rail["duration_hr"].dropna().empty:
        res["avg_journey_hr"] = float(rail["duration_hr"].mean(skipna=True))
        longest = rail.loc[rail["duration_hr"].idxmax()]
        res["longest"] = {
            "from": longest.get("from", ""), "to": longest.get("to", ""),
            "hr": float(longest["duration_hr"]), "date": longest["date"].date().isoformat(),
        }
    res["full_days_equiv"] = res["rail_hours"] / 24.0
    return res


def mode_breakdown(d: dict) -> pd.DataFrame:
    tr = d["transport"]
    if tr.empty:
        return pd.DataFrame()
    g = tr.groupby("mode").agg(
        journeys=("mode", "size"),
        hours=("duration_hr", lambda s: s.sum(skipna=True)),
        km=("distance_km", lambda s: s.sum(skipna=True)),
        cost=("cost_usd", lambda s: s.sum(skipna=True)),
    )
    order = [m for m in MODE_ORDER if m in g.index] + [m for m in g.index if m not in MODE_ORDER]
    return g.reindex(order)


def transport_timeline(d: dict) -> pd.DataFrame:
    """Hours by mode per calendar date — feeds the timeline chart."""
    tr = d["transport"]
    if tr.empty:
        return pd.DataFrame()
    t = tr.dropna(subset=["duration_hr"]).copy()
    if t.empty:
        return pd.DataFrame()
    return t.pivot_table(index=t["date"].dt.date, columns="mode",
                         values="duration_hr", aggfunc="sum", fill_value=0.0)


# --------------------------------------------------------------------------- #
# text report
# --------------------------------------------------------------------------- #
def build_report(d: dict) -> str:
    ov, sp, ts = overview(d), spend_summary(d), train_stats(d)
    L: list[str] = []
    L.append("eubackpacking — data report")
    L.append("=" * 40)
    L.append(f"{ov['n_trips']} trips · {ov['trip_days']} days on the road · "
             f"{ov['first_day']:%b %Y} – {ov['last_day']:%b %Y}")
    L.append(f"{ov['n_countries']} countries · {ov['n_cities']} cities · "
             f"{ov['nights_logged']} nights logged")
    if ov["countries"]:
        L.append("  " + ", ".join(ov["countries"]))
    L.append("")

    L.append("Spend")
    L.append("-" * 40)
    for tid, row in d["trips"].iterrows():
        total = sp["by_trip"].get(tid, 0.0)
        tag = "" if sp["complete"].get(tid) else "  (PARTIAL — still logging receipts)"
        L.append(f"  {row['name']:<14} ${total:>10,.0f}   ${sp['cost_per_day'].get(tid,0):>5,.0f}/day{tag}")
    L.append(f"  {'TOTAL':<14} ${sp['total']:>10,.0f}")
    if not d["expenses"].empty:
        L.append("")
        L.append("  by category:")
        for cat, amt in sp["by_category"].items():
            L.append(f"    {cat:<12} ${amt:>9,.0f}")
    L.append("")

    L.append("Trains")
    L.append("-" * 40)
    if ts.get("has_data"):
        L.append(f"  {ts['rail_hours']:.0f} h on intercity trains "
                 f"({ts['full_days_equiv']:.1f} full days) across {ts['rail_journeys']} journeys")
        L.append(f"  {ts['rail_km']:,.0f} km by rail · {ts['rail_hour_share']*100:.0f}% "
                 f"of all logged travel time · trains on {ts['rail_days']} days")
        if "longest" in ts:
            lg = ts["longest"]
            L.append(f"  longest single ride: {lg['from']} → {lg['to']}  "
                     f"{lg['hr']:.1f} h  ({lg['date']})")
    else:
        L.append("  no transport data yet")
    L.append("")

    mb = mode_breakdown(d)
    if not mb.empty:
        L.append("Transport by mode")
        L.append("-" * 40)
        L.append(f"  {'mode':<8}{'trips':>7}{'hours':>9}{'km':>10}{'cost':>10}")
        for mode, r in mb.iterrows():
            L.append(f"  {mode:<8}{int(r['journeys']):>7}{r['hours']:>9.1f}"
                     f"{r['km']:>10,.0f}{r['cost']:>10,.0f}")
    L.append("")
    L.append(f"generated {d['generated']:%Y-%m-%d %H:%M UTC}")
    return "\n".join(L)


if __name__ == "__main__":
    print(build_report(load_all()))
