# A gap year around Europe, in numbers

Two backpacking trips — **Summer 2025** (2 months) and **Spring 2026** (3 months) —
turned into a small stats dashboard. Not a blog: just where I went, what it cost,
and how much of it was spent sitting on trains.

**[→ Live dashboard](https://jimmysieja.github.io/eubackpacking/)**

<!-- STATS:START -->

<sub>Jun 2025 – May 2026 &nbsp;·&nbsp; 2 trips &nbsp;·&nbsp; generated 02 Sep 2026</sub>

| Countries | Cities | Days on the road | Nights logged | Spend logged |
|:-:|:-:|:-:|:-:|:-:|
| **15** | **34** | **151** | **149** | **$2,668** \* |

## 🚆 Time on trains

**86 hours** on intercity trains — about **3.6 full days** — over **26** journeys and **8,925 km**. That's 66% of all logged travel time.

Longest single ride: **Bilbao → Porto**, 7.5 h.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/trains-dark.svg">
  <img alt="Hours by transport mode" src="assets/trains-light.svg" width="100%">
</picture>

## Transport by mode

| Mode | Journeys | Hours | km |
|:--|--:|--:|--:|
| Train | 26 | 85.9 | 8,925 |
| Bus | 8 | 44.0 | 2,535 |
| Flight | 4 | 0.0 | 0 |

## Money

- **Summer 2025**: $473 ($8/day) — *partial, still logging*
- **Spring 2026**: $2,195 ($24/day)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/spend-category-dark.svg">
  <img alt="Spend by category" src="assets/spend-category-light.svg" width="100%">
</picture>

## The route

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/route-dark.svg">
  <img alt="Route map of every city in visit order" src="assets/route-light.svg" width="100%">
</picture>

<sub>\* Summer 2025 expenses are only partly logged, so its spend and the combined total are a floor, not a final number.</sub>

<!-- STATS:END -->

---

## How it works

Everything lives as flat files in [`data/`](data/) and [`photos/`](photos/). One
script turns them into the site — there is no database, no API, and nothing
scheduled. When I add expenses or photos, I re-run the build and commit the
output.

| File | What it holds |
|---|---|
| `data/trips.yml` | The two trips: dates, and whether the expense list is complete |
| `data/cities.yml` | Every place I slept: country, arrive/depart, coordinates, notes |
| `data/expenses_trip1.csv` | Summer 2025 spend — **partial**, still being entered |
| `data/expenses_trip2.csv` | Spring 2026 spend — fully itemised |
| `data/transport_trip1.csv` | Every intercity journey: mode, date, from/to, duration, distance |
| `data/transport_trip2.csv` | Same, for the second trip |
| `photos/` | Web-sized JPGs + `captions.yml` |

```
python -m pip install -r requirements.txt   # once
python build.py                             # regenerate docs/ + assets/ + this README block
```

`build.py` writes:

- `docs/index.html` — the dashboard (GitHub Pages serves the `docs/` folder)
- `docs/photos/` — copies of the photos
- `assets/*.svg` — the light/dark charts embedded above
- the `<!-- STATS -->` block in this file

See [SETUP.md](SETUP.md) for first-time setup and how to publish with GitHub Pages.

## Scripts

| Script | Purpose |
|---|---|
| `analytics.py` | Loads `data/`, computes every metric, prints a text report |
| `dashboard.py` | Builds `docs/index.html` (and, with `--assets`, the README SVGs) |
| `build.py` | Everything at once — the one command to run before committing |

## License

MIT — see [LICENSE](LICENSE). The code is MIT; the photos are just mine.
