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
    mb = A.mode_breakdown(d)
    star = " \\*" if sp["any_partial"] else ""
    L: list[str] = []

    L.append(f"<sub>{ov['first_day']:%b %Y} – {ov['last_day']:%b %Y} &nbsp;·&nbsp; "
             f"{ov['n_trips']} trips &nbsp;·&nbsp; generated {d['generated']:%d %b %Y}</sub>")
    L.append("")
    real = not ts.get("estimated", True)
    approx = "" if real else "~"
    L.append(f"| Countries | Cities slept in | Nights | {'Trains' if real else 'Train legs'} | Spend logged |")
    L.append("|:-:|:-:|:-:|:-:|:-:|")
    L.append(f"| **{ov['n_countries']}** | **{ov['n_cities']}** | **{ov['nights_logged']}** "
             f"| **{ts.get('rail_legs', 0)}** | **${sp['total']:,.0f}**{star} |")
    L.append("")

    if ts.get("has_data"):
        L.append("## 🚆 Time on trains")
        L.append("")
        L.append(f"{approx}**{ts['rail_hours']:,.0f} hours** on trains — about "
                 f"**{ts['full_days_equiv']:.1f} full days** — over **{ts['rail_legs']}** "
                 f"{'trains' if real else 'legs'} and **{ts['rail_km']:,.0f} km**, across "
                 f"**{ts['countries_by_train']}** countries. That's "
                 f"{ts['rail_hour_share']*100:.0f}% of all travel time.")
        if "longest" in ts:
            lg = ts["longest"]
            km = f" ({lg['km']:,.0f} km)" if lg.get("km") else ""
            L.append("")
            L.append(f"Longest ride: **{lg['from']} → {lg['to']}**, {approx}{lg['hr']:.1f} h{km}.")
        L.append("")
        L.append("<sub>" + ("Train figures come straight from the Eurail Rail Planner app."
                 if real else "Durations estimated from route distance — no stopwatch numbers "
                 "in the data.") + "</sub>")
        L.append("")
        L.append(_picture("trains", "Hours by transport mode"))
        L.append("")

    if not mb.empty:
        L.append("## Every leg, by mode")
        L.append("")
        L.append("| Mode | Legs | Hours | km |")
        L.append("|:--|--:|--:|--:|")
        for m, r in mb.iterrows():
            pfx = "" if not r["estimated"] else "~"
            L.append(f"| {D.MODE_LABEL.get(m, m.title())} | {int(r['legs'])} "
                     f"| {pfx}{r['hours']:,.1f} | {r['km']:,.0f} |")
        if mb["estimated"].any():
            L.append("")
            L.append("<sub>Train row from the Eurail app; other modes estimated from route "
                     "distance.</sub>")
        L.append("")

    if not d["expenses"].empty:
        L.append("## Money")
        L.append("")
        for tid, row in d["trips"].iterrows():
            total = sp["by_trip"].get(tid, 0)
            if total <= 0:
                L.append(f"- **{row['name']}**: expenses not entered yet")
                continue
            tag = "" if sp["complete"].get(tid) else " — *partial, still logging*"
            L.append(f"- **{row['name']}**: ${total:,.0f} "
                     f"(${sp['cost_per_day'].get(tid, 0):,.0f}/day){tag}")
        L.append("")
        L.append(_picture("spend-category", "Spend by category"))
        L.append("")
        if "route" in D._chart_set(d):
            L.append("## The route")
            L.append("")
            L.append(_picture("route", "Route map of every city in visit order"))
            L.append("")

    if sp["any_partial"]:
        L.append("<sub>\\* Summer 2025 expenses are only partly logged, so its spend and "
                 "the combined total are a floor, not a final number.</sub>")

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
