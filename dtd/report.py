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
    history = read_state("history", [])
    by_media = {m: h for h in history for m in h.get("media_ids", [])}
    lanes = {i["id"]: i.get("lane") for i in load_all_weeks()}

    rows = []
    for media in instagram.media_since(since):
        reel = media.get("media_product_type") == "REELS"
        stats = instagram.media_insights(media["id"], REEL_METRICS if reel else POST_METRICS)
        post = by_media.get(media["id"], {})
        reach = stats.get("reach", 0)
        rows.append({
            "name": (post.get("name") or _snippet(media.get("caption", ""))).replace("|", "/"),
            "lane": lanes.get(post.get("id")) or "other",
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

    best, worst = ranked[0], ranked[-1]
    md.append("\n### For next week's picks\n")
    md.append(f"- Best post: **{best['name']}** ({best['lane']}).")
    if len(ranked) > 1:
        md.append(f"- Weakest post: **{worst['name']}** ({worst['lane']}).")
    if lane_rows[0][0] != "other":
        md.append(f"- Strongest lane: **{lane_rows[0][0]}**. Lean into it next week while keeping the mix varied.")
    return title, "\n".join(md) + "\n"


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
    api = f"https://{code}.goatcounter.com/api/v0"
    params = {"start": f"{since:%Y-%m-%d}", "end": f"{until:%Y-%m-%d}", "limit": 100}
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        hits = requests.get(f"{api}/stats/hits", params=params, headers=headers, timeout=60)
        hits.raise_for_status()
        refs = requests.get(f"{api}/stats/toprefs", params=params, headers=headers, timeout=60)
        refs.raise_for_status()
    except requests.RequestException as e:
        md.append(f"Could not read shop page stats this week: {str(e)[:200]}\n")
        return md
    rows = hits.json().get("hits") or []
    visits = sum(h.get("count", 0) for h in rows if not h.get("event"))
    taps = sorted((h for h in rows if h.get("event") and str(h.get("path", "")).startswith("amazon-")), key=lambda h: h.get("count", 0), reverse=True)
    reels = sum(h.get("count", 0) for h in rows if h.get("event") and str(h.get("path", "")).startswith("reel-"))
    md.append(f"**Visits:** {visits}  ·  **Taps to Amazon:** {sum(h.get('count', 0) for h in taps)}  ·  **Reel plays:** {reels}\n")
    sources = [r for r in (refs.json().get("stats") or []) if r.get("count")]
    if sources:
        md.append("Came from: " + ", ".join(f"{r.get('name') or 'direct or app'} {r['count']}" for r in sources[:6]) + "\n")
    if taps:
        md.append("| Product tapped | Taps |")
        md.append("| --- | ---: |")
        for h in taps[:15]:
            md.append(f"| {(h.get('title') or h['path']).replace('|', '/')} | {h.get('count', 0)} |")
        md.append("")
    return md


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


def _snippet(caption: str) -> str:
    first = caption.strip().splitlines()[0] if caption.strip() else "Untitled post"
    return (first[:40] + "...") if len(first) > 40 else first
