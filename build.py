"""
One command to regenerate everything the site publishes:

    python build.py

  docs/index.html      the dashboard GitHub Pages serves (from the /docs folder)
  docs/photos/         web-sized copies of photos/*.jpg
  assets/*.svg         the light/dark charts embedded in README.md
  README.md            the block between <!-- STATS:START --> and <!-- STATS:END -->

Run it whenever you change anything in data/ or photos/, then commit the result.
There is no scheduler and nothing to configure — the output is a pure function
of the files in data/ and photos/.
"""

from __future__ import annotations

from pathlib import Path

import analytics as A
import dashboard as D

ROOT = Path(__file__).parent
MARK_START = "<!-- STATS:START -->"
MARK_END = "<!-- STATS:END -->"


def _picture(name: str, alt: str) -> str:
    return (
        "<picture>\n"
        f'  <source media="(prefers-color-scheme: dark)" srcset="assets/{name}-dark.svg">\n'
        f'  <img alt="{alt}" src="assets/{name}-light.svg" width="100%">\n'
        "</picture>"
    )


def stats_markdown(d: dict) -> str:
    ov = A.overview(d)
    sp = A.spend_summary(d)
    ts = A.train_stats(d)
    star = " \\*" if sp["any_partial"] else ""
    charts = D._chart_set(d)
    L: list[str] = []

    L.append(f"<sub>{ov['first_day']:%b %Y} – {ov['last_day']:%b %Y} &nbsp;·&nbsp; "
             f"generated {d['generated']:%d %b %Y}</sub>")
    L.append("")
    L.append("| Countries | Cities | Days | Trains | Spent |")
    L.append("|:-:|:-:|:-:|:-:|:-:|")
    L.append(f"| **{ov['n_countries_visited']}** | **{ov['n_cities']}** | **{ov['trip_days']}** "
             f"| **{ts.get('rail_legs', 0)}** | **${sp['total']:,.0f}**{star} |")
    L.append("")

    if "route" in charts:
        L.append(_picture("route", "Route trace of every stop in order"))
        L.append("")

    if ts.get("has_data"):
        lg = ts.get("longest")
        long_txt = (f" The longest single ride was **{lg['from']} → {lg['to']}**, "
                    f"{lg['hr']:.1f} h.") if lg else ""
        L.append(f"**{ts['rail_hours']:,.0f} hours on trains** — about {ts['full_days_equiv']:.1f} "
                 f"full days — over {ts['rail_legs']} trains and {ts['rail_km']:,.0f} km of track, "
                 f"through {ts['countries_by_train']} countries.{long_txt}")
        L.append("")
        if "trains" in charts:
            L.append(_picture("trains", "Hours in transit, by day"))
            L.append("")

    if not d["expenses"].empty:
        L.append(f"**${sp['total']:,.0f} spent** on the spring trip, "
                 f"${sp['total'] / d['trips'].loc['trip2', 'days']:,.0f} a day.")
        L.append("")
        if "spend" in charts:
            L.append(_picture("spend", "Spend by category"))
            L.append("")

    if sp["any_partial"]:
        L.append("<sub>\\* Summer 2025 not fully logged yet — totals are a floor.</sub>")
    return "\n".join(L).rstrip()


def update_readme(d: dict, path: Path | None = None) -> bool:
    path = path or (ROOT / "README.md")
    text = path.read_text(encoding="utf-8")
    if MARK_START not in text or MARK_END not in text:
        raise SystemExit(f"{path.name} is missing the {MARK_START} / {MARK_END} markers")
    head, _, rest = text.partition(MARK_START)
    _, _, tail = rest.partition(MARK_END)
    new = f"{head}{MARK_START}\n\n{stats_markdown(d)}\n\n{MARK_END}{tail}"
    if new != text:
        path.write_text(new, encoding="utf-8")
        return True
    return False


def main() -> None:
    d = A.load_all()

    D.write_docs(d)
    print(f"docs/index.html written ({len(list((D.DOCS / 'photos').glob('*'))) if (D.DOCS / 'photos').exists() else 0} photos)")

    written = D.export_assets(d)
    print(f"assets/: {len(written)} svg files")

    changed = update_readme(d)
    print("README.md updated" if changed else "README.md already current")


if __name__ == "__main__":
    main()
