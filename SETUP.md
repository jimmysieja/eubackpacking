# Setup

## 1. Install

```bash
python -m venv .venv
. .venv/Scripts/activate          # Windows
# source .venv/bin/activate       # macOS / Linux
python -m pip install -r requirements.txt
```

## 2. Put in your data

Edit the files in `data/`. They're plain CSV and YAML — open them in a spreadsheet
or a text editor.

- **`trips.yml`** — the two trips. Flip `expenses_complete` to `true` once a
  trip's expense list is finished; until then the site labels that trip's spend
  as partial.
- **`cities.yml`** — one entry per place you slept. `arrive`/`depart` are
  check-in / check-out; `lat`/`lon` are optional but draw the route map.
- **`expenses_*.csv`** — columns: `date, trip, country, city, category,
  description, amount_usd`. Categories: `lodging, food, transport, activities,
  shopping, other` (anything else falls under "other").
- **`transport_*.csv`** — columns: `date, trip, mode, from, to, duration_hr,
  distance_km, cost_usd, operator, notes`. Only `date` and `mode` are required;
  `duration_hr` is what powers the "time on trains" number, so fill it where you
  can. Modes: `train, bus, flight, ferry, tram, metro, car, bike, walk`.
  "Trains" in the headline stat means `train` only — trams and metros don't count.

The sample rows currently in those files are placeholders. Replace them.

## 3. Add photos

Drop web-sized JPGs into `photos/` (long edge ≤ 2000px, quality ~80 — the build
does **not** resize for you). List each one in `photos/captions.yml`:

```yaml
- file: berlin-eastside.jpg
  caption: East Side Gallery on a grey morning.
  city: Berlin
  featured: true      # optional — pulls it into the README
```

Keep it under ~100 photos so the repo stays small.

## 4. Build

```bash
python build.py
```

Then open `docs/index.html`, or run `python dashboard.py` to build and open it in
one step. Commit `docs/`, `assets/`, and `README.md` along with your data changes.

## 5. Publish with GitHub Pages

1. Push the repo to GitHub.
2. **Settings → Pages → Build and deployment → Source: Deploy from a branch.**
3. **Branch: `main`, folder: `/docs`.** Save.
4. After a minute the site is live at
   `https://<you>.github.io/eubackpacking/`. Link that from your personal site.

No GitHub Actions, no secrets. Every update is: edit `data/`, run `python
build.py`, commit, push.
