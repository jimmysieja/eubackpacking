"""
Turn a free-text expense log (date headers + "- <amount> <description>" bullets)
into a clean CSV the site can read.

    python tools/parse_expenses.py trip2

Reads  data/sources/expenses_<trip>.txt
Writes data/expenses_<trip>.csv   with columns:
       date, trip, city, country, currency, amount, amount_usd, category, description

City / country are inferred from the trip's stops file (whichever stop you were
sleeping at that night). Category is a keyword guess — skim the CSV afterwards
and fix the rows it gets wrong; from then on the CSV is the source of truth and
you can delete / ignore the raw text.
"""

from __future__ import annotations

import re
import sys
import csv
import unicodedata
from pathlib import Path

import yaml
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
YEAR = 2026

SYMBOL = {"€": "EUR", "£": "GBP", "$": "USD"}
CODES = ("DKK", "SEK", "PLN", "BAM", "LEK", "EUR", "GBP", "USD", "NOK", "CZK", "HUF")

DATE_RE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})\s*$")
BULLET_RE = re.compile(r"^\s*[-⁃•]\s*(.*)$")
SYM_RE = re.compile(r"^([€£$])\s?([\d,]+(?:\.\d+)?)\s*(.*)$")
CODE_RE = re.compile(r"^([\d,]+(?:\.\d+)?)\s*(" + "|".join(CODES) + r")\b\s*(.*)$", re.I)

# category keywords, checked in this order — first hit wins
CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("lodging", ["hostel", "hotel", "airbnb", "guesthouse", "dorm"]),
    ("transport", [
        "metro", "métro", "tram", "seat reservation", "seat rezzo", "train to",
        "train seat", "ferry", "flight", "bus", "rer", "transpo", "velib",
        "vélib", "bike for a day", "bike rental", "bike pass", "uber", "taxi",
        "day pass metro", "week metro pass", "weekly pass", "metro pass",
        "24hr metro", "airport", "flight extension", "to heuston",
        "to letterfrack", "to pen y pass", "to center", "to ralph",
    ]),
    ("gifts", [
        "gift", "gifts", "for katherine", "for rj", "for zach", "hot sauce",
        "dad gift", "mom gift", "zach gift", "annie gift", "manu gifts",
        "garment gifts", "chocolate for",
    ]),
    ("activities", [
        "tour", "museum", "exhibit", "exhibition", "versailles", "toboggan",
        "footy match", "football match", "club entry", "psg tickets", "tix",
        "tickets", "entry fee", "ntl park", "national park", "park exhibition",
        "walking tour", "boat tour", "anfield", "architecture center",
        "grand palais", "patch yr wyddfa",
    ]),
    ("shopping", [
        "zara", "uniqlo", "airism", "tote bag", " bag", "bag ", "trousers",
        "pants", "jacket", "sweater", "jeans", "socks", "vest", "tie", "shirt",
        "hat", "loafers", "longcoat", "long coat", "coat", "sunnies", "glasses",
        "moisturizer", "cleanser", "sss", "hand sanitizer", "soap", "towel",
        "charging plug", "earbud adapter", "earbuds", "lock and tape",
        "tape", "playing cards", "book", "merch", "lego", "minifigure",
        "chair art piece", "necklace", "bracelet", "dragonfly ring", "charm",
        "belt", "stickers", "humana", "guerrisol", "thrift", "thrifted",
        "weekday", "five vintage", "uff",
    ]),
    ("food", [
        "tgtg", "grocery", "groceries", "lidl", "aldi", "tesco", "sainsbury",
        "spar", "rewe", "penny", "rimi", "mercator", "carrefour", "franprix",
        "intermarché", "intermarche", "g20", "zabka", "interspar", "spoons",
        "meal deal", "mcdonald", "burger king", "hesburger", "max burgers",
        "pizza", "sandwich", "sandy", "baguette", "tradition", "pastry",
        "pastries", "croissant", "pain au", "brioche", "bread", "eclair",
        "éclair", "beignet", "feuilleté", "feuillete", "chausson", "pancake",
        "crepe", "crêpe", "fish & chips", "tacos", "panini", "joe & juice",
        "fruitjuice", "juice", "matcha", "latte", "espresso", "coffee", "cafe",
        "café", "beer", "cider", "wine", "guinness", "guiness", "pitcher",
        "alcohol", "buzz", "burek", "byrek", "shawarma", "hummus", "eggs",
        "mushrooms", "grapes", "strawberries", "yoghurt", "yogurt", "proshake",
        "protein milk", "donut", "ice cream", "dinner", "lunch", "breakfast",
        "street food", "beet soup", "lido", "selver", "voli", "supermarket",
        "bakery", "boulangerie", "ham butter", "tuc and dates", "spinach twist",
        "poulette", "picnic", "snacks", "cookie", "pringles", "water",
        "eurokrem", "la parisienne", "bambino", "restaurant", "noisette",
        "drink and cake", "honey", "food", "dates", "protein powder",
        "market", "amaretto", "amoretto", "sour cream", "beee",
    ]),
    ("misc", ["postcard", "atm withdrawal", "shipping", "omniva", "locker",
              "misc exp", "stamps", "humana"]),
]


def deaccent(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def categorize(desc: str) -> str:
    d = deaccent(desc).lower()
    if "hostel bar" in d or "hotel bar" in d:
        return "food"  # a drink at the bar, not the bed
    for cat, kws in CATEGORY_RULES:
        for kw in kws:
            if deaccent(kw).lower() in d:
                return cat
    return "misc"


def parse_amount(text: str) -> tuple[str | None, float | None, str]:
    m = SYM_RE.match(text)
    if m:
        return SYMBOL[m.group(1)], float(m.group(2).replace(",", "")), m.group(3).strip()
    m = CODE_RE.match(text)
    if m:
        return m.group(2).upper(), float(m.group(1).replace(",", "")), m.group(3).strip()
    return None, None, text.strip()


def sleep_stop_lookup(trip_id: str):
    trips = {t["id"]: t for t in yaml.safe_load((DATA / "trips.yml").read_text(encoding="utf-8"))}
    stops = pd.read_csv(DATA / trips[trip_id]["stops"])
    stops["arrival_date"] = pd.to_datetime(stops["arrival_date"], errors="coerce")
    stops["departure_date"] = pd.to_datetime(stops["departure_date"], errors="coerce")
    stops["nights"] = (stops["departure_date"] - stops["arrival_date"]).dt.days
    stops = stops.dropna(subset=["arrival_date"])

    def lookup(d: pd.Timestamp) -> tuple[str, str]:
        inrange = stops[(stops["arrival_date"] <= d) & (stops["departure_date"] >= d)]
        pref = inrange[inrange["nights"] > 0]
        pool = pref if not pref.empty else inrange
        if pool.empty:
            return "", ""
        row = pool.sort_values(["arrival_date", "stop_number"]).iloc[-1]
        return str(row["city"]), str(row["country"])

    return lookup


def main() -> None:
    trip_id = sys.argv[1] if len(sys.argv) > 1 else "trip2"
    src = DATA / "sources" / f"expenses_{trip_id}.txt"
    out = DATA / f"expenses_{trip_id}.csv"
    fx = yaml.safe_load((DATA / "fx.yml").read_text(encoding="utf-8"))
    where = sleep_stop_lookup(trip_id)

    rows, unpriced, unknown_ccy = [], 0, set()
    cur_date: pd.Timestamp | None = None

    for raw in src.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        m = DATE_RE.match(raw)
        if m:
            cur_date = pd.Timestamp(YEAR, int(m.group(1)), int(m.group(2)))
            continue
        bm = BULLET_RE.match(raw)
        if not bm or cur_date is None:
            continue
        body = bm.group(1).strip()
        if not body:
            continue
        ccy, amt, desc = parse_amount(body)
        desc = re.sub(r"\s+", " ", desc).strip(" .")
        if ccy is None:
            unpriced += 1
        elif ccy not in fx:
            unknown_ccy.add(ccy)
        usd = round(amt * fx[ccy], 2) if (amt is not None and ccy in fx) else ""
        city, country = where(cur_date)
        rows.append({
            "date": cur_date.date().isoformat(),
            "trip": trip_id,
            "city": city,
            "country": country,
            "currency": ccy or "",
            "amount": amt if amt is not None else "",
            "amount_usd": usd,
            "category": categorize(desc),
            "description": desc,
        })

    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    total = sum(r["amount_usd"] for r in rows if r["amount_usd"] != "")
    by_cat: dict[str, float] = {}
    for r in rows:
        if r["amount_usd"] != "":
            by_cat[r["category"]] = by_cat.get(r["category"], 0) + r["amount_usd"]
    print(f"wrote {out}  ({len(rows)} line items, ${total:,.0f} total)")
    for c, v in sorted(by_cat.items(), key=lambda kv: -kv[1]):
        print(f"  {c:<11} ${v:>8,.0f}")
    if unpriced:
        print(f"  ({unpriced} items had no parseable amount — left blank)")
    if unknown_ccy:
        print(f"  (!) currencies missing from fx.yml: {', '.join(sorted(unknown_ccy))}")


if __name__ == "__main__":
    main()
