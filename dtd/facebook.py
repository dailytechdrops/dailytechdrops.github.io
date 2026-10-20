"""Facebook Page Reels (graph.facebook.com).

Needs FB_PAGE_ID and FB_PAGE_TOKEN, a Page access token with pages_manage_posts and
pages_read_engagement. Both are optional: without them the reel is simply not cross-posted.
"""

import re
import time
from pathlib import Path

import requests

from .config import env

API = "https://graph.facebook.com/v23.0"


class FacebookError(RuntimeError):
    pass


def configured() -> bool:
    return bool(env("FB_PAGE_ID") and env("FB_PAGE_TOKEN"))


def _call(method: str, url: str, **kwargs) -> dict:
    r = requests.request(method, url, timeout=180, **kwargs)
    if r.status_code >= 400:
        raise FacebookError(f"{method} {url.split('?')[0]} failed {r.status_code}: {r.text[:500]}")
    return r.json()


def caption_for_facebook(caption: str, link: str) -> str:
    """Facebook has no comment-for-link DM here, so the call to action becomes the link itself."""
    return re.sub(r"^Comment \w+ and I will DM you the Amazon link\.$", f"Get it on Amazon: {link}", caption, flags=re.MULTILINE)


def publish_reel(video: Path, caption: str) -> str:
    page, token = env("FB_PAGE_ID"), env("FB_PAGE_TOKEN")
    if not (page and token):
        raise FacebookError("FB_PAGE_ID and FB_PAGE_TOKEN must be set")
    start = _call("POST", f"{API}/{page}/video_reels", data={"upload_phase": "start", "access_token": token})
    video_id = start["video_id"]
    _call("POST", start["upload_url"], headers={
        "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(video.stat().st_size),
    }, data=video.read_bytes())
    _call("POST", f"{API}/{page}/video_reels", data={
        "upload_phase": "finish", "video_id": video_id, "video_state": "PUBLISHED",
        "description": caption, "access_token": token,
    })
    _wait_published(video_id, token)
    return video_id


def _wait_published(video_id: str, token: str, timeout_s: int = 600) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        status = _call("GET", f"{API}/{video_id}", params={"fields": "status", "access_token": token}).get("status", {})
        phase = status.get("video_status")
        if phase == "ready":
            return
        if phase == "error":
            raise FacebookError(f"Facebook rejected the reel: {status}")
        time.sleep(10)
    raise FacebookError("Timed out waiting for Facebook to process the reel")
