"""YouTube Shorts uploads (YouTube Data API v3).

Needs YT_CLIENT_ID, YT_CLIENT_SECRET and YT_REFRESH_TOKEN for the channel's Google account
(scope youtube.upload). All three are optional: without them nothing is uploaded.

Google keeps every upload from an unaudited API project private. Until the project passes
YouTube's compliance audit, set the YOUTUBE_PRIVACY variable to private (the default) and
switch it to public after approval.
"""

import json
from pathlib import Path

import requests

from .config import env

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
SHOP_URL = "https://kevingalus.github.io/daily-tech-drops/"
# YouTube rejects titles over 100 characters.
MAX_TITLE = 100


class YouTubeError(RuntimeError):
    pass


def configured() -> bool:
    return bool(env("YT_CLIENT_ID") and env("YT_CLIENT_SECRET") and env("YT_REFRESH_TOKEN"))


def _access_token() -> str:
    r = requests.post(TOKEN_URL, timeout=60, data={
        "client_id": env("YT_CLIENT_ID"), "client_secret": env("YT_CLIENT_SECRET"),
        "refresh_token": env("YT_REFRESH_TOKEN"), "grant_type": "refresh_token",
    })
    if r.status_code >= 400:
        raise YouTubeError(f"Token refresh failed {r.status_code}: {r.text[:500]}")
    return r.json()["access_token"]


def title_for(name: str) -> str:
    suffix = " #Shorts"
    return name[: MAX_TITLE - len(suffix)].rstrip() + suffix


def description_for(cfg: dict, draft: dict) -> str:
    """The reel says to comment for the link, which only works on Instagram, so the
    description carries the link instead. Shorts descriptions do not make links
    clickable, so the shop page is named too; it is also linked on the channel."""
    return "\n".join([
        cfg["instagram"]["disclosure"],
        "",
        f"{draft['name']}: {draft['link']}",
        "",
        f"Every gadget we post: {SHOP_URL}",
        "Prices change often, so check Amazon for today's price.",
        "",
        "#Shorts #techgadgets #amazonfinds #coolgadgets",
    ])


def upload_short(video: Path, title: str, description: str, privacy: str = "private") -> str:
    token = _access_token()
    meta = {
        "snippet": {"title": title, "description": description, "categoryId": "28"},  # Science & Technology
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False, "containsSyntheticMedia": False},
    }
    start = requests.post(UPLOAD_URL, timeout=60, params={"uploadType": "resumable", "part": "snippet,status"}, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(video.stat().st_size),
    }, data=json.dumps(meta))
    if start.status_code >= 400:
        raise YouTubeError(f"Upload start failed {start.status_code}: {start.text[:500]}")
    r = requests.put(start.headers["Location"], timeout=600, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "video/mp4",
    }, data=video.read_bytes())
    if r.status_code >= 400:
        raise YouTubeError(f"Upload failed {r.status_code}: {r.text[:500]}")
    return r.json()["id"]
