# Setup

## 1. Install

```bash
python -m venv .venv
. .venv/Scripts/activate          # Windows
# source .venv/bin/activate       # macOS / Linux
python -m pip install -r requirements.txt
```

## 2. The data files

Everything the site shows comes from `data/`. Edit these in a spreadsheet or text
editor; the sample rows are real for Trip 2 and empty for Trip 1.

### `trips.yml`
The two trips. Set `expenses_complete: true` once a trip's expense list is
finished — until then the site labels that trip's spend as partial. `stops` and
`expenses` name the files that hold that trip's data.

### `trip2_stops.csv` / `trip1_stops.csv`
The itinerary, one row per stop, in order:

```
stop_number,city,country,transport,arrival_date,departure_date
2,Paris,France,Avion,2026-02-24,2026-03-10
```

- `transport` is how you *arrived* at that stop. English or French both work:
  `train/bus/ferry/flight/car` or `Train/Bus/Bateau/Avion/Voiture`.
- `arrival_date == departure_date` marks a same-day stop (a day trip or a
  pass-through). More than one night ⇒ it counts as a place you slept.
- Home / airport bookends can have a blank transport and blank dates.
- Every city named here must also appear in `coords.csv`.

### `coords.csv`
`city,lat,lon` — city-centre coordinates. Powers the route map and the
distance-based time estimates. Add a row whenever you add a new city to a stops
file.

### `expenses_trip2.csv` / `expenses_trip1.csv`
One row per purchase:

```
date,trip,city,country,currency,amount,amount_usd,category,description
2026-03-02,trip2,Paris,France,EUR,32.40,34.99,transport,week metro pass
```

- `category` — one of `lodging, food, transport, shopping, activities, gifts,
  misc` (anything else is treated as `misc`).
- `amount_usd` can be left blank; the build fills it from `amount` × the rate in
  `fx.yml`.
- `city` / `country` can be left blank; they only feed the "spend by country"
  chart.

### `fx.yml`
Currency → USD rates. They're approximate period averages — replace with your
real statement rates if you have them.

### Rebuilding an expense file from raw notes
If you'd rather paste a rough text log than hand-format a CSV, drop it in
`data/sources/expenses_<trip>.txt` as date headers plus `- <amount> <description>`
bullets and run:

```bash
python tools/parse_expenses.py trip2
```

It guesses `category` from keywords and fills `city`/`country` from the stops
file. Skim the result and fix the rows it gets wrong — after that the CSV is the
source of truth and you can ignore the text file.

## 3. Photos

Drop web-sized JPGs into `photos/` (long edge ≤ 2000px, quality ~80 — the build
does **not** resize). List each in `photos/captions.yml`:

```yaml
- file: berlin-eastside.jpg
  caption: East Side Gallery on a grey morning.
  city: Berlin
```

Keep it under ~100 photos so the repo stays small.

## 4. Build

```bash
python build.py            # regenerate everything
python dashboard.py        # build just the dashboard and open it in a browser
python analytics.py        # print the text report (quick sanity check on the numbers)
```

Commit `docs/`, `assets/`, and `README.md` along with your data changes.

## 5. Publish with GitHub Pages

1. Push the repo to GitHub.
2. **Settings → Pages → Build and deployment → Source: Deploy from a branch.**
3. **Branch: `main`, folder: `/docs`.** Save.
4. After a minute it's live at `https://<you>.github.io/eubackpacking/`. Link
   that from your personal site.

No GitHub Actions, no secrets. Every update is: edit `data/`, run `python
build.py`, commit, push.
