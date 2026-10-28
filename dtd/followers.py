"""Follower counts on every channel, for the weekly report.

Each platform is asked with the token it already has. A platform that cannot give a number
says why in its row instead of leaving it blank. History is kept in state/followers.json so
the report can show the change since the last one.

Pinterest is the exception: its refresh token changes on every use, and the hourly Pinterest
workflow owns it, so that workflow saves the count (state/pinterest_account.json) and the
report only reads it.
"""

from datetime import datetime

import requests

from . import facebook, instagram, threads, tiktok, youtube
from .config import EASTERN, env, read_state, write_state

PLATFORMS = ["Instagram", "Facebook", "Threads", "TikTok", "YouTube", "Pinterest"]


def _instagram() -> int:
    return int(instagram.account().get("followers_count", 0))


def _facebook() -> int:
    if not facebook.configured():
        raise LookupError("Facebook Page secrets not set")
    page = env("FB_PAGE_ID")
    token = facebook.page_token(page, env("FB_PAGE_TOKEN"))
    data = facebook._call("GET", f"{facebook.API}/{page}", params={"fields": "followers_count,fan_count", "access_token": token})
    return int(data.get("followers_count", data.get("fan_count", 0)))


def _threads() -> int:
    if not threads.configured():
        raise LookupError("Threads secrets not set")
    try:
        data = threads._call("GET", f"{threads.API}/{env('THREADS_USER_ID')}/threads_insights",
                             params={"metric": "followers_count", "access_token": env("THREADS_ACCESS_TOKEN")})
    except threads.ThreadsError as e:
        # Follower counts sit behind the threads_manage_insights permission, which the posting token may not have.
        raise LookupError(f"Threads refused (token likely needs threads_manage_insights): {str(e)[-150:]}") from e
    for metric in data.get("data", []):
        if metric.get("name") == "followers_count":
            return int(metric.get("total_value", {}).get("value", 0))
    raise LookupError("Threads returned no follower count")


def _tiktok() -> int:
    """Buffer is our only route to TikTok. Its API is checked for any follower field on a
    channel; if Buffer does not share one, the row says so."""
    if not tiktok.configured():
        raise LookupError("Buffer key not set")
    t = tiktok._gql('query { __type(name: "Channel") { fields { name } } }')["__type"] or {}
    fields = [f["name"] for f in t.get("fields", []) if "follower" in f["name"].lower()]
    if not fields:
        raise LookupError("Buffer's API does not share TikTok follower counts")
    channel = tiktok.channel_id()
    data = tiktok._gql(f"query($id: ChannelId!) {{ channel(input: {{id: $id}}) {{ {fields[0]} }} }}", {"id": channel})
    return int(data["channel"][fields[0]])


def _youtube() -> int:
    if not youtube.configured():
        raise LookupError("YouTube secrets not set")
    token = youtube._access_token()
    r = requests.get(youtube.CHANNELS_URL, timeout=60, params={"part": "statistics", "id": youtube.CHANNEL_ID},
                     headers={"Authorization": f"Bearer {token}"})
    if r.status_code >= 400:
        raise LookupError(f"YouTube channel lookup failed {r.status_code}")
    items = r.json().get("items", [])
    if not items:
        raise LookupError("YouTube returned no channel")
    stats = items[0]["statistics"]
    if stats.get("hiddenSubscriberCount"):
        raise LookupError("subscriber count is hidden on the channel")
    return int(stats.get("subscriberCount", 0))


def _pinterest() -> int:
    saved = read_state("pinterest_account", None)
    if not saved:
        raise LookupError("not saved yet (the hourly Pinterest run records it)")
    return int(saved["followers"])


FETCHERS = {"Instagram": _instagram, "Facebook": _facebook, "Threads": _threads,
            "TikTok": _tiktok, "YouTube": _youtube, "Pinterest": _pinterest}


def counts() -> dict[str, int | str]:
    """A number per platform, or the reason there is none."""
    out = {}
    for name in PLATFORMS:
        try:
            out[name] = FETCHERS[name]()
        except Exception as e:  # one platform failing must never stop the report
            out[name] = str(e) if isinstance(e, LookupError) else f"lookup failed: {str(e)[:120]}"
    return out


def section() -> list[str]:
    """The Followers table, and a new entry in the history for next week's change."""
    now = counts()
    history = read_state("followers", [])
    md = ["### Followers\n", "| Page | Followers | Change since last report |", "| --- | ---: | ---: |"]
    total, missing = 0, []
    for name in PLATFORMS:
        value = now[name]
        if isinstance(value, str):
            missing.append(name)
            md.append(f"| {name} | n/a | {value} |")
            continue
        total += value
        prev = next((h[name] for h in reversed(history) if isinstance(h.get(name), int)), None)
        change = f"{value - prev:+d}" if prev is not None else "first count"
        md.append(f"| {name} | {value:,} | {change} |")
    md.append(f"| **All pages** | **{total:,}** | |")
    if missing:
        md.append(f"\nNo count for: {', '.join(missing)}. The reason is in each row.")
    md.append("")
    history.append({"date": f"{datetime.now(EASTERN):%Y-%m-%d}", **{k: v for k, v in now.items() if isinstance(v, int)}})
    write_state("followers", history[-104:])
    return md
