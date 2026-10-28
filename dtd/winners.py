"""Winners dashboard: ranks every reel from the last 30 days and says what to repeat.

Each reel gets a score from 0 to 100: the average share of other reels it beats on reach,
saves, shares, average watch time and shop page taps for its product. A tap on the shop
page cannot be tied to one reel, so every reel of a product shares that product's taps.

Writes docs/winners.html (the dashboard, on GitHub Pages next to the shop page),
reports/winners.md and state/winners.json. The weekly report copies the "What to repeat"
list, and the Sunday research reads it from reports/latest.md.
"""

import html
from collections import defaultdict
from datetime import datetime, timedelta

import requests

from . import report
from .config import EASTERN, ROOT, env, read_state, write_state

DAYS = 30
SETTLE_HOURS = 48     # a reel keeps gaining reach for about two days, so newer ones are shown but not judged
MIN_GROUP = 2         # a lane, hook or time slot needs at least this many judged reels to be called a winner
SIGNALS = [("reach", "Reach"), ("saves", "Saves"), ("shares", "Shares"), ("watch_s", "Watch"), ("taps", "Shop taps")]


def build() -> dict:
    until = datetime.now(EASTERN)
    since = until - timedelta(days=DAYS)
    history = read_state("history", [])
    asin_of = {h["id"]: h.get("asin") for h in history}
    reels = [r for r in report.post_rows(since) if r["kind"] == "Reel"]

    taps, taps_ok = _product_taps(since, until, asin_of)
    for r in reels:
        r["taps"] = taps.get(r["asin"], 0)
        r["settled"] = (until - r["when"]).total_seconds() >= SETTLE_HOURS * 3600
    judged = [r for r in reels if r["settled"]]
    for r in reels:
        r["score"] = _score(r, judged)
    judged.sort(key=lambda r: r["score"], reverse=True)
    reels.sort(key=lambda r: (r["settled"], r["score"]), reverse=True)

    groups = {
        "Lane": _groups(judged, lambda r: r["lane"]),
        "Hook style": _groups(judged, lambda r: r["hook"] or "untagged"),
        "Time of day": _groups(judged, lambda r: report._daypart(r["when"])),
        "First post or remix": _groups(judged, lambda r: "remix" if r["remix_of"] else "first post"),
    }
    products = defaultdict(lambda: {"reels": 0, "reach": 0, "taps": 0})
    for r in reels:
        p = products[r["asin"] or r["name"]]
        p.update(name=r["name"], lane=r["lane"], taps=r["taps"])
        p["reels"] += 1
        p["reach"] += r["reach"]
    top_products = sorted(products.values(), key=lambda p: (p["taps"], p["reach"]), reverse=True)

    data = {
        "updated": f"{until:%Y-%m-%d %H:%M}",
        "since": f"{since:%Y-%m-%d}",
        "taps_connected": taps_ok,
        "repeat": _repeat(judged, groups, top_products, taps_ok),
        "reels": [{**r, "when": f"{r['when']:%Y-%m-%d %H:%M}"} for r in reels],
        "groups": groups,
        "products": top_products[:15],
    }
    return data


def _product_taps(since: datetime, until: datetime, asin_of: dict) -> tuple[dict, bool]:
    """Shop page taps to Amazon per ASIN. Card events are amazon-<post id>; the post id ends in the ASIN."""
    if not env("GOATCOUNTER_TOKEN"):
        return {}, False
    try:
        hits = report.goatcounter("hits", since, until).get("hits") or []
    except requests.RequestException as e:
        print(f"Shop taps unavailable: {str(e)[:200]}")
        return {}, False
    taps = defaultdict(int)
    for h in hits:
        path = str(h.get("path", ""))
        if h.get("event") and path.startswith("amazon-"):
            post_id = path[len("amazon-"):]
            asin = asin_of.get(post_id) or post_id.rsplit("-", 1)[-1].upper()
            taps[asin] += h.get("count", 0)
    return dict(taps), True


def _score(r: dict, judged: list[dict]) -> float:
    """0 to 100: on each signal, the share of the other judged reels this one beats (a tie counts half)."""
    others = [o for o in judged if o is not r]
    if not others:
        return 0.0
    parts = []
    for key, _ in SIGNALS:
        beaten = sum(1 if r[key] > o[key] else 0.5 if r[key] == o[key] else 0 for o in others)
        parts.append(beaten / len(others))
    return round(100 * sum(parts) / len(parts), 1)


def _groups(reels: list[dict], key) -> list[dict]:
    by = defaultdict(list)
    for r in reels:
        by[key(r)].append(r)
    out = [{
        "name": name,
        "reels": len(items),
        "score": round(sum(i["score"] for i in items) / len(items), 1),
        "reach": round(sum(i["reach"] for i in items) / len(items)),
        "saves_shares": sum(i["saves"] + i["shares"] for i in items),
        "watch_s": round(sum(i["watch_s"] for i in items) / len(items), 1),
        "taps": sum(i["taps"] for i in items),
    } for name, items in by.items()]
    return sorted(out, key=lambda g: g["score"], reverse=True)


def _repeat(judged: list[dict], groups: dict, products: list[dict], taps_ok: bool) -> list[str]:
    """The short list the weekly report and the Sunday research act on."""
    if len(judged) < 3:
        return ["Not enough reels older than two days yet to call winners."]
    out = []
    top = judged[:3]
    out.append("Top reels: " + "; ".join(
        f"**{r['name']}** (score {r['score']:.0f}, reach {r['reach']:,.0f}, watch {r['watch_s']:.1f}s"
        f"{', ' + str(r['hook']) + ' hook' if r['hook'] else ''})" for r in top) + ".")
    for title in ("Lane", "Hook style", "Time of day", "First post or remix"):
        # "untagged" and "other" are reels from before tagging, so they are not something to repeat.
        ranked = [g for g in groups[title] if g["reels"] >= MIN_GROUP and g["name"] not in ("untagged", "other")]
        if len(ranked) < 2:
            continue
        best, worst = ranked[0], ranked[-1]
        if best["score"] - worst["score"] < 10:
            out.append(f"{title}: no clear winner yet ({best['name']} {best['score']:.0f} vs {worst['name']} {worst['score']:.0f}).")
        else:
            out.append(f"{title}: repeat **{best['name']}** (avg score {best['score']:.0f}); "
                       f"use less **{worst['name']}** ({worst['score']:.0f}).")
    tapped = [p for p in products if p["taps"]]
    if tapped:
        out.append("Most tapped on the shop page: " + ", ".join(f"**{p['name']}** ({p['taps']})" for p in tapped[:3])
                   + ". Remix these first and pick similar products.")
    elif taps_ok:
        out.append("No shop page taps to Amazon yet in the last 30 days.")
    bottom = judged[-1]
    out.append(f"Weakest reel: **{bottom['name']}** (score {bottom['score']:.0f}). Avoid repeating its angle.")
    return out


def repeat_section(data: dict | None = None) -> list[str]:
    """Markdown for the weekly report, from the last saved dashboard run."""
    data = data or read_state("winners", {})
    if not data.get("repeat"):
        return []
    return [f"### What to repeat (last {DAYS} days, from the winners dashboard)\n",
            *[f"- {line}" for line in data["repeat"]],
            "\nFull ranking: https://dailytechdrops.github.io/winners.html\n"]


def markdown(data: dict) -> str:
    md = [f"## Winners: reels since {data['since']}\n", *repeat_section(data)[:-1], "",
          *_hook_table(data), "### Every reel, best first\n",
          "Score is 0 to 100: the average share of other reels it beats on reach, saves, shares, watch time and shop taps. "
          "Reels under two days old are listed last and not scored against the others yet.\n",
          "| Reel | Lane | Hook | Score | Reach | Saves | Shares | Watch | Shop taps |",
          "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for r in data["reels"]:
        score = f"{r['score']:.0f}" if r["settled"] else "new"
        md.append(f"| [{r['name']}]({r['url']}) {r['when'][5:10]} | {r['lane']} | {r['hook'] or ''} | {score} "
                  f"| {r['reach']:,.0f} | {r['saves']:.0f} | {r['shares']:.0f} | {r['watch_s']:.1f}s | {r['taps']} |")
    return "\n".join(md) + "\n"


def _hook_table(data: dict) -> list[str]:
    """Hook styles side by side, so the Sunday research can see which openings hold viewers."""
    groups = data.get("groups", {}).get("Hook style") or []
    if not groups:
        return []
    md = ["### By hook style (reels older than two days)\n",
          "| Hook style | Reels | Avg score | Avg reach | Avg watch | Saves + shares | Shop taps |",
          "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    md += [f"| {g['name']} | {g['reels']} | {g['score']:.0f} | {g['reach']:,} | {g['watch_s']:.1f}s | {g['saves_shares']} | {g['taps']} |"
           for g in groups]
    return md + [""]


def page(data: dict) -> str:
    e = html.escape

    def bold(text: str) -> str:
        parts = e(text).split("**")
        return "".join(f"<strong>{p}</strong>" if i % 2 else p for i, p in enumerate(parts))

    rows = []
    for r in data["reels"]:
        score = f"{r['score']:.0f}" if r["settled"] else '<span class="new">new</span>'
        bar = f'<span class="bar" style="width:{r["score"]:.0f}%"></span>' if r["settled"] else ""
        rows.append(
            f'<tr><td class="name"><a href="{e(r["url"])}">{e(r["name"])}</a><span class="sub">{e(r["when"][5:16])} · {e(r["lane"])}'
            f'{" · " + e(r["hook"]) + " hook" if r["hook"] else ""}{" · remix" if r["remix_of"] else ""}</span></td>'
            f'<td class="num score" data-v="{r["score"] if r["settled"] else -1}">{bar}<b>{score}</b></td>'
            f'<td class="num" data-v="{r["reach"]}">{r["reach"]:,.0f}</td><td class="num" data-v="{r["saves"]}">{r["saves"]:.0f}</td>'
            f'<td class="num" data-v="{r["shares"]}">{r["shares"]:.0f}</td><td class="num" data-v="{r["watch_s"]}">{r["watch_s"]:.1f}s</td>'
            f'<td class="num" data-v="{r["taps"]}">{r["taps"]}</td></tr>')
    group_html = []
    for title, groups in data["groups"].items():
        if not groups:
            continue
        lines = "".join(
            f'<tr><td>{e(g["name"])}</td><td class="num">{g["reels"]}</td><td class="num"><b>{g["score"]:.0f}</b></td>'
            f'<td class="num">{g["reach"]:,}</td><td class="num">{g["watch_s"]:.1f}s</td><td class="num">{g["saves_shares"]}</td><td class="num">{g["taps"]}</td></tr>'
            for g in groups)
        group_html.append(f'<div class="panel"><h3>{e(title)}</h3><table><thead><tr><th></th><th class="num">Reels</th><th class="num">Score</th>'
                          f'<th class="num">Avg reach</th><th class="num">Avg watch</th><th class="num">Saves+shares</th><th class="num">Taps</th></tr></thead>'
                          f'<tbody>{lines}</tbody></table></div>')
    products = "".join(
        f'<tr><td>{e(p["name"])}<span class="sub">{e(p["lane"])}</span></td><td class="num">{p["reels"]}</td>'
        f'<td class="num">{p["reach"]:,}</td><td class="num"><b>{p["taps"]}</b></td></tr>' for p in data["products"])
    taps_note = "" if data["taps_connected"] else '<p class="note">Shop taps are not connected in this run, so they count as 0.</p>'
    repeat = "".join(f"<li>{bold(line)}</li>" for line in data["repeat"])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>Winners dashboard · Daily Tech Drops</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;800&display=swap" rel="stylesheet">
<style>
:root {{ --bg:#FBF6EE; --ink:#3B2F27; --muted:#7A6A5D; --accent:#E8792B; --accent-soft:#FBE7D6; --card:#fff; --line:#F1E8DC; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 Inter, system-ui, sans-serif; -webkit-font-smoothing:antialiased; }}
main {{ max-width:1080px; margin:0 auto; padding:28px 16px 48px; }}
h1 {{ font:800 26px/1.15 Inter, system-ui, sans-serif; letter-spacing:-.02em; margin:0; }}
p.sub, .note {{ color:var(--muted); margin:4px 0 0; font-size:14px; }}
h2 {{ font:600 13px/1.3 Inter, system-ui, sans-serif; text-transform:uppercase; letter-spacing:.08em; color:var(--muted); margin:30px 0 12px; }}
h3 {{ font-size:15px; margin:0 0 8px; }}
.panel {{ background:var(--card); border-radius:16px; padding:16px; box-shadow:0 1px 2px rgba(59,47,39,.05), 0 6px 18px rgba(59,47,39,.06); overflow-x:auto; }}
.repeat {{ background:var(--accent-soft); }}
.repeat ul {{ margin:0; padding-left:20px; }} .repeat li {{ margin:6px 0; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(320px, 1fr)); gap:14px; }}
table {{ width:100%; border-collapse:collapse; font-size:14px; }}
th {{ text-align:left; color:var(--muted); font-weight:500; font-size:12.5px; padding:6px 8px; border-bottom:1px solid var(--line); white-space:nowrap; }}
#reels th {{ cursor:pointer; }} #reels th:hover {{ color:var(--accent); }}
td {{ padding:8px; border-bottom:1px solid var(--line); vertical-align:top; }}
.num {{ text-align:right; white-space:nowrap; font-variant-numeric:tabular-nums; }}
.name a {{ color:var(--ink); font-weight:600; text-decoration:none; }} .name a:hover {{ color:var(--accent); }}
.sub {{ display:block; color:var(--muted); font-size:12.5px; }}
.score {{ position:relative; min-width:70px; }}
.bar {{ position:absolute; right:8px; bottom:4px; height:3px; max-width:54px; background:var(--accent); border-radius:2px; opacity:.55; }}
.new {{ color:var(--muted); font-weight:500; }}
</style></head><body><main>
<h1>Winners dashboard</h1>
<p class="sub">Every Instagram reel since {e(data['since'])}, ranked. Updated {e(data['updated'])} ET, every morning.</p>
<h2>What to repeat</h2>
<div class="panel repeat"><ul>{repeat}</ul></div>
<h2>Every reel</h2>
<div class="panel"><table id="reels"><thead><tr><th>Reel</th><th class="num">Score</th><th class="num">Reach</th><th class="num">Saves</th>
<th class="num">Shares</th><th class="num">Watch</th><th class="num">Shop taps</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<p class="note">Score 0 to 100 is the average share of other reels it beats on reach, saves, shares, average watch time and shop taps.
Shop taps are per product, so every reel of a product shares them. Reels under two days old are marked new and not scored yet. Tap a column to sort.</p>{taps_note}</div>
<h2>Patterns</h2>
<div class="grid">{''.join(group_html)}</div>
<h2>Products by shop taps</h2>
<div class="panel"><table><thead><tr><th>Product</th><th class="num">Reels</th><th class="num">Total reach</th><th class="num">Shop taps</th></tr></thead><tbody>{products}</tbody></table></div>
</main>
<script>
document.querySelectorAll('#reels th').forEach((th, i) => th.addEventListener('click', () => {{
  const body = th.closest('table').tBodies[0], rows = [...body.rows];
  const val = r => i === 0 ? r.cells[0].innerText.toLowerCase() : parseFloat(r.cells[i].dataset.v);
  const dir = th.dataset.dir === 'desc' ? 1 : -1; th.dataset.dir = dir === 1 ? 'asc' : 'desc';
  rows.sort((a, b) => (val(a) > val(b) ? 1 : val(a) < val(b) ? -1 : 0) * dir).forEach(r => body.appendChild(r));
}}));
</script>
</body></html>
"""


def run() -> int:
    data = build()
    write_state("winners", data)
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "winners.md").write_text(markdown(data))
    (ROOT / "docs" / "winners.html").write_text(page(data))
    print("\n".join(data["repeat"]))
    return 0
