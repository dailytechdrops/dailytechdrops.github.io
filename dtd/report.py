"""Weekly performance report: how each post and lane did over the last 7 days.

Writes reports/<date>.md (the Sunday research reads the latest one to pick next week's
products) and keeps a follower history in state/insights.json for week-over-week change.
"""

from collections import defaultdict
from datetime import datetime, timedelta

import requests

from . import instagram
from .config import EASTERN, ROOT, env, load_all_weeks, load_config, read_state, write_state

REPORTS_DIR = ROOT / "reports"
POST_METRICS = ["reach", "views", "likes", "comments", "saved", "shares", "total_interactions"]
REEL_METRICS = POST_METRICS + ["ig_reels_avg_watch_time"]
ACCOUNT_METRICS = ["reach", "views", "accounts_engaged", "total_interactions", "profile_links_taps"]


def build(days: int = 7) -> tuple[str, str]:
    """Returns (title, markdown)."""
    until = datetime.now(EASTERN)
    since = until - timedelta(days=days)
    rows = post_rows(since)

    acct = instagram.account()
    totals = instagram.account_insights(ACCOUNT_METRICS, since, until)
    followers = acct.get("followers_count", 0)
    snapshots = read_state("insights", [])
    previous = snapshots[-1]["followers"] if snapshots else None
    snapshots.append({"date": f"{until:%Y-%m-%d}", "followers": followers, **totals})
    write_state("insights", snapshots[-52:])

    title = f"Weekly report: {since:%b %d} to {until:%b %d}"
    md = [f"## {title}\n"]
    change = f" ({followers - previous:+d} this week)" if previous is not None else ""
    md.append(f"**Followers:** {followers}{change}  ")
    md.append(f"**Posts:** {len(rows)}  ·  **Link DMs sent:** {sum(r['dms'] for r in rows)}  ")
    md.append(
        f"**Accounts reached:** {totals.get('reach', 0):,.0f}  ·  **Views:** {totals.get('views', 0):,.0f}  ·  "
        f"**Engaged:** {totals.get('accounts_engaged', 0):,.0f}  ·  **Bio link taps:** {totals.get('profile_links_taps', 0):,.0f}\n"
    )
    from .winners import repeat_section
    md += repeat_section()
    md += shop_section(since, until)
    if not rows:
        md.append("No posts in the last 7 days.")
        return title, "\n".join(md) + "\n"

    # Link DMs are the closest thing to a sale we can see, so they rank first.
    ranked = sorted(rows, key=lambda r: (r["dms"], r["saves"] + r["shares"], r["reach"]), reverse=True)
    md.append("### Posts, best first\n")
    md.append("| Post | Type | Reach | Views | Saves | Shares | Eng. | Watch | Link DMs |")
    md.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for r in ranked:
        watch = f"{r['watch_s']:.1f}s" if r["watch_s"] else ""
        md.append(
            f"| [{r['name']}]({r['url']}) {r['when']:%a %-I:%M%p} | {r['kind']} | {r['reach']:,.0f} | {r['views']:,.0f} "
            f"| {r['saves']:.0f} | {r['shares']:.0f} | {r['eng']:.1%} | {watch} | {r['dms']} |"
        )

    by_lane = defaultdict(list)
    for r in rows:
        by_lane[r["lane"]].append(r)
    md.append("\n### By lane\n")
    md.append("| Lane | Posts | Avg reach | Avg eng. | Link DMs |")
    md.append("| --- | ---: | ---: | ---: | ---: |")
    lane_rows = sorted(by_lane.items(), key=lambda kv: (sum(r["dms"] for r in kv[1]), _avg(kv[1], "reach")), reverse=True)
    for lane, items in lane_rows:
        md.append(f"| {lane} | {len(items)} | {_avg(items, 'reach'):,.0f} | {_rate(items):.1%} | {sum(r['dms'] for r in items)} |")

    md += experiments_section(rows)
    md += hook_trend_section(rows, until)

    best, worst = ranked[0], ranked[-1]
    md.append("\n### For next week's picks\n")
    md.append(f"- Best post: **{best['name']}** ({best['lane']}).")
    if len(ranked) > 1:
        md.append(f"- Weakest post: **{worst['name']}** ({worst['lane']}).")
    if lane_rows[0][0] != "other":
        md.append(f"- Strongest lane: **{lane_rows[0][0]}**. Lean into it next week while keeping the mix varied.")
    return title, "\n".join(md) + "\n"


def post_rows(since: datetime) -> list[dict]:
    """Every Instagram post since then with its lifetime stats, matched to its week file entry."""
    history = read_state("history", [])
    by_media = {m: h for h in history for m in h.get("media_ids", [])}
    items = {i["id"]: i for i in load_all_weeks()}

    rows = []
    for media in instagram.media_since(since):
        reel = media.get("media_product_type") == "REELS"
        stats = instagram.media_insights(media["id"], REEL_METRICS if reel else POST_METRICS)
        post = by_media.get(media["id"], {})
        reach = stats.get("reach", 0)
        item = items.get(post.get("id"), {})
        rows.append({
            "id": post.get("id"),
            "asin": post.get("asin"),
            "hook": hook_style(item, _snippet(media.get("caption", ""), 200)) if reel else None,
            "remix_of": item.get("remix_of"),
            "name": (post.get("name") or _snippet(media.get("caption", ""))).replace("|", "/"),
            "lane": item.get("lane") or "other",
            "kind": "Reel" if reel else {"CAROUSEL_ALBUM": "Carousel", "IMAGE": "Photo"}.get(media.get("media_type"), "Post"),
            "when": instagram._ts(media["timestamp"]).astimezone(EASTERN),
            "url": media.get("permalink", ""),
            "reach": reach,
            "views": stats.get("views", 0),
            "saves": stats.get("saved", 0),
            "shares": stats.get("shares", 0),
            "interactions": stats.get("total_interactions", media.get("like_count", 0) + media.get("comments_count", 0)),
            "watch_s": stats.get("ig_reels_avg_watch_time", 0) / 1000,
            "dms": post.get("dms", 0),
        })
    for r in rows:
        r["eng"] = r["interactions"] / r["reach"] if r["reach"] else 0
    return rows



def shop_section(since: datetime, until: datetime) -> list[str]:
    """Shop page visits, where they came from, and which product cards were tapped through
    to Amazon, from GoatCounter. A tap is the last step we can see before Amazon; the
    Associates Orders report (by tracking ID) shows what was bought."""
    code = (load_config().get("analytics") or {}).get("goatcounter")
    token = env("GOATCOUNTER_TOKEN")
    md = ["### Shop page\n"]
    if not (code and token):
        md.append("Shop page stats are not connected yet (needs the GOATCOUNTER_TOKEN secret).\n")
        return md
    try:
        rows = goatcounter("hits", since, until).get("hits") or []
        refs = goatcounter("toprefs", since, until)
    except requests.RequestException as e:
        md.append(f"Could not read shop page stats this week: {str(e)[:200]}\n")
        return md
    _save_top_products(rows)
    visits = sum(h.get("count", 0) for h in rows if not h.get("event"))
    taps = sorted((h for h in rows if h.get("event") and str(h.get("path", "")).startswith(("amazon-", "gift-"))), key=lambda h: h.get("count", 0), reverse=True)
    reels = sum(h.get("count", 0) for h in rows if h.get("event") and str(h.get("path", "")).startswith("reel-"))
    md.append(f"**Visits:** {visits}  ·  **Taps to Amazon:** {sum(h.get('count', 0) for h in taps)}  ·  **Reel plays:** {reels}\n")
    sources = [r for r in (refs.get("stats") or []) if r.get("count")]
    if sources:
        md.append("Came from: " + ", ".join(f"{r.get('name') or 'direct or app'} {r['count']}" for r in sources[:6]) + "\n")
    if taps:
        md.append("| Product tapped | Taps |")
        md.append("| --- | ---: |")
        for h in taps[:15]:
            md.append(f"| {(h.get('title') or h['path']).replace('|', '/')} | {h.get('count', 0)} |")
        md.append("")
    md += _gift_guides(rows)
    return md


def goatcounter(stat: str, since: datetime, until: datetime) -> dict:
    """One GoatCounter stats call (hits, toprefs, ...) over the window. Raises on HTTP errors."""
    code = (load_config().get("analytics") or {}).get("goatcounter")
    api = f"https://{code}.goatcounter.com/api/v0"
    params = {"start": f"{since:%Y-%m-%d}", "end": f"{until:%Y-%m-%d}", "limit": 100}
    headers = {"Authorization": f"Bearer {env('GOATCOUNTER_TOKEN')}", "Content-Type": "application/json"}
    resp = requests.get(f"{api}/stats/{stat}", params=params, headers=headers, timeout=60)
    resp.raise_for_status()
    return resp.json()


def _gift_guides(rows: list) -> list[str]:
    """Per holiday gift guide: page visits, taps on its tile on the shop page, taps through to Amazon
    from the guide page, and Pinterest saves started from it. Event names come from dtd/shop.py."""
    from .shop import load_guides
    out = []
    for g in load_guides():
        s = g["slug"]
        count = lambda test: sum(h.get("count", 0) for h in rows if test(h))  # noqa: E731
        visits = count(lambda h: not h.get("event") and str(h.get("path", "")).endswith((f"/gifts/{s}", f"/gifts/{s}.html")))
        tiles = count(lambda h: h.get("event") and h.get("path") == f"guide-{s}")
        amazon = count(lambda h: h.get("event") and str(h.get("path", "")).startswith(f"gift-{s}-"))
        pins = count(lambda h: h.get("event") and h.get("path") == f"pin-{s}")
        out.append(f"| {g['title']} | {visits} | {tiles} | {amazon} | {pins} |")
    if not out:
        return []
    return ["#### Gift guides\n", "| Guide | Visits | Opened from shop | Taps to Amazon | Pinterest saves |", "| --- | ---: | ---: | ---: | ---: |", *out, ""]


# Hook styles the first beat is sorted into, so the report can say which kind of opening holds viewers.
# Every week file entry sets hook_style; reels from before tagging get a guess from their first line.
HOOK_STYLES = {
    "callout": "names the viewer's own problem (\"Your phone is at 1 percent. Again.\")",
    "question": "asks the viewer something they answer yes to",
    "number": "leads with a concrete number",
    "demo": "tells them to watch something happen",
    "curiosity": "a surprising claim that makes them stay for the answer",
    "statement": "plain description of the product; the weakest, kept only for old reels",
}
CURIOSITY_WORDS = ("nobody", "secret", "actually", "wait", "pov", "turns out", "not every", "you didn't know", "survives")
NUMBER_WORDS = {"two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "hundred", "thousand"}


def hook_style(item: dict, fallback_text: str = "") -> str | None:
    """The week file's hook_style if set, otherwise a guess from the first beat's text
    (or from fallback_text, the caption's first line, for reels with no week file entry)."""
    if item.get("hook_style"):
        return item["hook_style"]
    beats = (item.get("content") or {}).get("beats") or []
    screen, voice = (beats[0].get("on_screen", ""), beats[0].get("voiceover", "")) if beats else (fallback_text, fallback_text)
    if not (screen or voice).strip():
        return None
    return guess_hook_style(screen, voice)


def guess_hook_style(screen: str, voice: str) -> str:
    text = f"{screen} {voice}".lower()
    words = [w.strip(".,!?:;\"'").lower() for w in screen.split()]
    if "?" in screen or voice.rstrip().endswith("?"):
        return "question"
    if voice.split(" ", 1)[0].strip(".,").lower() in {"watch", "look", "see"} or (words and words[0] in {"watch", "look"}):
        return "demo"
    if any(ch.isdigit() for ch in screen) or NUMBER_WORDS & set(words):
        return "number"
    if any(w in text for w in CURIOSITY_WORDS):
        return "curiosity"
    if words and words[0] in {"your", "you", "you're", "stop", "still"}:
        return "callout"
    return "statement"


def _daypart(when: datetime) -> str:
    h = when.hour + when.minute / 60
    return "morning (before 11)" if h < 11 else "midday (11 to 2)" if h < 14 else "afternoon (2 to 6)" if h < 18 else "evening (after 6)"


def experiments_section(rows: list[dict]) -> list[str]:
    """Reels only: which hook style and which time of day did best, and how each remix
    (same product, new hook) did against its first post."""
    reels = [r for r in rows if r["kind"] == "Reel"]
    if not reels:
        return []
    md = ["\n### Experiments (reels only)\n"]
    for title, key in (("Hook style", lambda r: r["hook"] or "untagged"), ("Time of day", lambda r: _daypart(r["when"]))):
        groups = defaultdict(list)
        for r in reels:
            groups[key(r)].append(r)
        md.append(f"| {title} | Reels | Avg reach | Avg watch | Saves + shares | Link DMs |")
        md.append("| --- | ---: | ---: | ---: | ---: | ---: |")
        for name, items in sorted(groups.items(), key=lambda kv: _avg(kv[1], "reach"), reverse=True):
            watched = [i for i in items if i["watch_s"]]
            md.append(f"| {name} | {len(items)} | {_avg(items, 'reach'):,.0f} | {_avg(watched, 'watch_s'):.1f}s "
                      f"| {sum(i['saves'] + i['shares'] for i in items):.0f} | {sum(i['dms'] for i in items)} |")
        md.append("")
    by_id = {r["id"]: r for r in reels if r["id"]}
    pairs = [(by_id.get(r["remix_of"]), r) for r in reels if r["remix_of"]]
    if pairs:
        md.append("| Remix (same product, new hook) | First post | Remix |")
        md.append("| --- | --- | --- |")
        for first, remix in pairs:
            before = f"{first['hook']}: reach {first['reach']:,.0f}, watch {first['watch_s']:.1f}s" if first else "posted before this week"
            md.append(f"| {remix['name']} | {before} | {remix['hook']}: reach {remix['reach']:,.0f}, watch {remix['watch_s']:.1f}s |")
        md.append("")
    md.append("Small samples swing a lot; trust a pattern only once it holds for two or three weeks.\n")
    return md


def hook_trend_section(rows: list[dict], until: datetime) -> list[str]:
    """Saves this week's reels per hook style and shows the last four weeks side by side, so a style
    is judged on several weeks rather than one. Reach is the main signal, watch time the tie-breaker."""
    groups = defaultdict(list)
    for r in rows:
        if r["kind"] == "Reel":
            groups[r["hook"] or "untagged"].append(r)
    if not groups:
        return []
    week = {name: {"reels": len(items), "reach": round(_avg(items, "reach")),
                   "watch_s": round(_avg([i for i in items if i["watch_s"]], "watch_s"), 1),
                   "saves_shares": sum(i["saves"] + i["shares"] for i in items)} for name, items in groups.items()}
    trend = [t for t in read_state("hook_trend", []) if t["date"] != f"{until:%Y-%m-%d}"]
    trend.append({"date": f"{until:%Y-%m-%d}", "styles": week})
    write_state("hook_trend", trend[-12:])
    recent = trend[-4:]
    styles = sorted({s for t in recent for s in t["styles"]},
                    key=lambda s: -_avg([t["styles"][s] for t in recent if s in t["styles"]], "reach"))
    md = ["\n### Hook styles, last four weeks\n",
          "Each cell is avg reach / avg watch (reels). A style wins once it leads on reach for two or three weeks running.\n",
          "| Hook style | " + " | ".join(f"Week to {t['date'][5:]}" for t in recent) + " |",
          "| --- |" + " ---: |" * len(recent)]
    for style in styles:
        cells = [f"{c['reach']:,} / {c['watch_s']:.1f}s ({c['reels']})" if (c := t["styles"].get(style)) else "" for t in recent]
        md.append(f"| {style} | " + " | ".join(cells) + " |")
    md.append("")
    return md


def _save_top_products(hits: list[dict]) -> None:
    """The most tapped products this week, for the "Most tapped" row at the top of the shop page."""
    taps = sorted((h for h in hits if h.get("event") and str(h.get("path", "")).startswith("amazon-")), key=lambda h: h.get("count", 0), reverse=True)
    write_state("shop_top", [h["path"][len("amazon-"):] for h in taps if h.get("count", 0) > 0][:3])


def run() -> str:
    title, md = build()
    REPORTS_DIR.mkdir(exist_ok=True)
    (REPORTS_DIR / f"{datetime.now(EASTERN):%Y-%m-%d}.md").write_text(md)
    (REPORTS_DIR / "latest.md").write_text(md)
    print(md)
    return title


def _avg(items: list[dict], key: str) -> float:
    return sum(i[key] for i in items) / len(items) if items else 0


def _rate(items: list[dict]) -> float:
    """Engagement over the lane's total reach, so a post seen by 3 people cannot skew it."""
    reach = sum(i["reach"] for i in items)
    return sum(i["interactions"] for i in items) / reach if reach else 0


def _snippet(caption: str, length: int = 40) -> str:
    first = caption.strip().splitlines()[0] if caption.strip() else "Untitled post"
    return (first[:length] + "...") if len(first) > length else first
