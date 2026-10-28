"""Daily health check. Prints one line per problem; the workflow turns any output into a GitHub issue,
which emails the repo owner, so nothing fails silently."""

import os
from datetime import date, datetime, timedelta

import requests

from .config import EASTERN, env, load_all_weeks, read_state
from . import facebook, threads, tiktok, youtube

# Dates things expire, from setup. Warned about three weeks ahead.
EXPIRIES = {
    "GH_PAT (the token that lets the monthly Instagram token refresh store itself)": date(2027, 1, 18),
    "Facebook data access for the Page token": date(2027, 1, 17),
}
MIN_DAYS_SCHEDULED = 3
SHOP_URL = "https://dailytechdrops.github.io/"


def problems() -> list[str]:
    found = []
    now = datetime.now(EASTERN)

    if env("IG_ACCESS_TOKEN"):
        r = requests.get("https://graph.instagram.com/v23.0/me", params={"fields": "id", "access_token": env("IG_ACCESS_TOKEN")}, timeout=60)
        if r.status_code != 200:
            found.append(f"Instagram login is failing ({r.status_code}). The token may have expired and needs a new one.")
    if facebook.configured():
        page = env("FB_PAGE_ID")
        tok = facebook.page_token(page, env("FB_PAGE_TOKEN"))
        r = requests.get(f"https://graph.facebook.com/v23.0/{page}", params={"fields": "id", "access_token": tok}, timeout=60)
        if r.status_code != 200:
            found.append(f"Facebook Page login is failing ({r.status_code}). Reels will not cross-post until it is reconnected.")

    if threads.configured():
        r = requests.get("https://graph.threads.net/v1.0/me", params={"fields": "id", "access_token": env("THREADS_ACCESS_TOKEN")}, timeout=60)
        if r.status_code != 200:
            found.append(f"Threads login is failing ({r.status_code}). Reels will not cross-post to Threads until it is reconnected.")

    if youtube.configured():
        try:
            youtube._check_channel(youtube._access_token())
        except youtube.YouTubeError as e:
            found.append(f"YouTube Shorts are paused: the saved YouTube login is not for the Daily Tech Drops channel yet ({str(e)[:120]}).")

    if tiktok.configured():
        try:
            tiktok.channel_id()
        except (tiktok.TikTokError, requests.RequestException) as e:
            found.append(f"TikTok posting is failing: Buffer cannot reach the TikTok account ({str(e)[:120]}). Reconnect TikTok in Buffer.")

    try:
        if requests.get(SHOP_URL, timeout=60).status_code != 200:
            found.append("The shop page is not loading.")
    except requests.RequestException:
        found.append("The shop page is not reachable.")

    posted = {h["id"] for h in read_state("history", [])}
    upcoming = sorted(i["when"] for i in load_all_weeks() if i["id"] not in posted and i["when"] > now)
    if not upcoming or upcoming[-1] < now + timedelta(days=MIN_DAYS_SCHEDULED):
        last = upcoming[-1].strftime("%b %d") if upcoming else "none"
        found.append(f"Fewer than {MIN_DAYS_SCHEDULED} days of posts are scheduled (last slot: {last}). The Sunday research run may have failed.")

    token, repo = env("GITHUB_TOKEN"), env("GITHUB_REPOSITORY")
    if token and repo:
        r = requests.get(f"https://api.github.com/repos/{repo}/actions/workflows/post.yml/runs", params={"per_page": 6, "status": "completed"},
                         headers={"Authorization": f"Bearer {token}"}, timeout=60)
        if r.status_code == 200:
            conclusions = [run["conclusion"] for run in r.json().get("workflow_runs", [])[:3]]
            if len(conclusions) == 3 and all(c == "failure" for c in conclusions):
                found.append("The posting workflow failed its last three runs. Open the Actions tab and look at the Post failed annotation.")

    for name, when in EXPIRIES.items():
        left = (when - date.today()).days
        if left <= 21:
            found.append(f"{name} expires in {left} days ({when:%b %d, %Y}).")
    return found


def main() -> int:
    for line in problems():
        print(line)
    return 0
