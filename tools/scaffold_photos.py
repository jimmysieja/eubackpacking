"""
Bring a batch of photos into photos/ and pre-fill photos/captions.yml.

    python tools/scaffold_photos.py <folder-of-images>

For each image it:
  - reads EXIF GPS + timestamp
  - downscales to <= 2560 px long edge, saves as photos/<stem>.jpg (EXIF kept)
  - guesses the city: the date picks the itinerary stop(s); GPS breaks ties
  - merges into photos/captions.yml, keeping any caption / featured already set

Then it prints which files it couldn't place. Edit those `city:` values (and
write captions) by hand, then run `python build.py`.
"""

from __future__ import annotations

import sys
import math
import datetime as dt
from pathlib import Path

import yaml
import pandas as pd
from PIL import Image, ExifTags

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PHOTOS = ROOT / "photos"
MAXPX = 1800   # photos/ is a working copy; keep true originals elsewhere
GPS_IFD = ExifTags.IFD.GPSInfo


def _haversine(a, b):
    r = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = math.radians(b[0] - a[0]), math.radians(b[1] - a[1])
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(x))


def _exif(p: Path):
    """-> (latlon | None, date | None)"""
    try:
        ex = Image.open(p).getexif()
    except Exception:
        return None, None
    date = None
    raw = ex.get(306) or ex.get_ifd(ExifTags.IFD.Exif).get(36867)
    if raw:
        try:
            date = dt.datetime.strptime(str(raw)[:19], "%Y:%m:%d %H:%M:%S").date()
        except ValueError:
            pass
    gps = ex.get_ifd(GPS_IFD)
    latlon = None
    if gps and 2 in gps and 4 in gps:
        def dms(v):
            return float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
        lat = dms(gps[2]) * (-1 if gps.get(1) == "S" else 1)
        lon = dms(gps[4]) * (-1 if gps.get(3) == "W" else 1)
        latlon = (lat, lon)
    return latlon, date


def _load_itinerary():
    coords = pd.read_csv(DATA / "coords.csv").drop_duplicates("city").set_index("city")
    trips = yaml.safe_load((DATA / "trips.yml").read_text(encoding="utf-8"))
    stops = []
    for t in trips:
        f = DATA / t["stops"]
        if not f.is_file():
            continue
        s = pd.read_csv(f)
        s["arrival_date"] = pd.to_datetime(s["arrival_date"], errors="coerce")
        s["departure_date"] = pd.to_datetime(s["departure_date"], errors="coerce")
        for _, r in s.dropna(subset=["arrival_date"]).iterrows():
            if r["city"] in coords.index:
                stops.append({"city": r["city"],
                              "a": r["arrival_date"].date(),
                              "d": (r["departure_date"] or r["arrival_date"]).date(),
                              "ll": (coords.loc[r["city"], "lat"], coords.loc[r["city"], "lon"])})
    return coords, stops


def guess_city(latlon, date, coords, stops):
    """-> (city, confidence, why)"""
    active = [s for s in stops if date and s["a"] <= date <= s["d"]] if date else []
    if latlon:
        near = min(coords.index, key=lambda c: _haversine(latlon, (coords.loc[c, "lat"], coords.loc[c, "lon"])))
        near_km = _haversine(latlon, (coords.loc[near, "lat"], coords.loc[near, "lon"]))
        if active:
            best = min(active, key=lambda s: _haversine(latlon, s["ll"]))
            if _haversine(latlon, best["ll"]) <= 60:
                return best["city"], "ok", ""
            if near_km <= 40:
                return near, "ok", "gps"
            return near, "check", f"gps~{near} but itinerary had {'/'.join(s['city'] for s in active)}"
        return (near, "ok", "gps-only") if near_km <= 40 else (near, "check", f"gps~{near}, no itinerary match for {date}")
    if len(active) == 1:
        return active[0]["city"], "ok", "date"
    if active:
        return active[0]["city"], "check", "travel day: " + "/".join(s["city"] for s in active)
    return "", "manual", "no gps, no usable date"


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: python tools/scaffold_photos.py <folder-of-images>")
    src = Path(sys.argv[1])
    imgs = sorted(p for p in src.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    if not imgs:
        sys.exit(f"no images in {src}")
    coords, stops = _load_itinerary()

    cap_file = PHOTOS / "captions.yml"
    existing = yaml.safe_load(cap_file.read_text(encoding="utf-8")) if cap_file.is_file() else []
    by_file = {e["file"]: e for e in (existing or []) if isinstance(e, dict) and e.get("file")}

    PHOTOS.mkdir(exist_ok=True)
    flagged, tally = [], {}
    for p in imgs:
        stem = p.stem.lower()
        out = PHOTOS / f"{stem}.jpg"
        latlon, date = _exif(p)
        im = Image.open(p)
        ex_bytes = im.info.get("exif")
        if max(im.size) > MAXPX:
            im.thumbnail((MAXPX, MAXPX))
        im.convert("RGB").save(out, "JPEG", quality=85, **({"exif": ex_bytes} if ex_bytes else {}))

        city, conf, why = guess_city(latlon, date, coords, stops)
        tally[city or "??"] = tally.get(city or "??", 0) + 1
        rec = by_file.get(out.name, {})
        rec.update(file=out.name, city=city, date=date.isoformat() if date else "")
        rec.setdefault("caption", "")
        by_file[out.name] = rec
        if conf != "ok":
            flagged.append((out.name, city or "—", why))

    merged = sorted(by_file.values(), key=lambda e: (e.get("date") or "9999", e["file"]))
    cap_file.write_text(
        "# Auto-scaffolded by tools/scaffold_photos.py — edit `caption` and fix any\n"
        "# wrong `city`. `featured: true` also pulls a photo onto the main page.\n\n"
        + yaml.safe_dump(merged, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8")

    print(f"processed {len(imgs)} images -> photos/  (captions.yml has {len(merged)} entries)")
    print("by city:", ", ".join(f"{k} {v}" for k, v in sorted(tally.items(), key=lambda x: -x[1])))
    if flagged:
        print(f"\n{len(flagged)} need a look:")
        for name, city, why in flagged:
            print(f"  {name:<28} -> {city:<22} {why}")


if __name__ == "__main__":
    main()
