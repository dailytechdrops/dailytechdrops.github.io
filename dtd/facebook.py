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


def page_token(page: str, token: str) -> str:
    """FB_PAGE_TOKEN may be a Page token or a long-lived user token of the Page's admin.
    Facebook only lets a Page token post, so a user token is traded for the Page's own token
    (which does not expire) on every run. If the lookup fails the saved token is used as is."""
    try:
        return _call("GET", f"{API}/{page}", params={"fields": "access_token", "access_token": token}).get("access_token") or token
    except FacebookError:
        return token


def publish_reel(video: Path, caption: str) -> str:
    page = env("FB_PAGE_ID")
    if not (page and env("FB_PAGE_TOKEN")):
        raise FacebookError("FB_PAGE_ID and FB_PAGE_TOKEN must be set")
    token = page_token(page, env("FB_PAGE_TOKEN"))
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
        try:
            status = _call("GET", f"{API}/{video_id}", params={"fields": "status", "access_token": token}).get("status", {})
        except FacebookError as e:
            # A just-finished reel can briefly read as "does not exist" (subcode 33) before Facebook indexes it.
            if '"error_subcode":33' not in str(e):
                raise
            time.sleep(15)
            continue
        phase = status.get("video_status")
        if phase == "ready":
            return
        if phase == "error":
            raise FacebookError(f"Facebook rejected the reel: {status}")
        time.sleep(10)
    raise FacebookError("Timed out waiting for Facebook to process the reel")


def comments(video_id: str) -> list[dict]:
    """Top-level comments on one of our Page reels, with who already replied to each.
    Reading other people's comments needs pages_read_user_content on the Page token."""
    page = env("FB_PAGE_ID")
    token = page_token(page, env("FB_PAGE_TOKEN"))
    data = _call("GET", f"{API}/{video_id}/comments", params={
        "filter": "toplevel", "limit": 50, "access_token": token,
        "fields": "id,message,from{id,name},created_time,comments.limit(25){from{id}}",
    })
    return data.get("data", [])


def reply_to_comment(comment_id: str, text: str) -> str:
    """Replies as the Page. Needs pages_manage_engagement on the Page token."""
    page = env("FB_PAGE_ID")
    token = page_token(page, env("FB_PAGE_TOKEN"))
    return _call("POST", f"{API}/{comment_id}/comments", data={"message": text, "access_token": token})["id"]


def token_permissions() -> list[str]:
    """The granted permissions of the token behind FB_PAGE_TOKEN (empty if Facebook will not say)."""
    try:
        data = _call("GET", f"{API}/me/permissions", params={"access_token": env("FB_PAGE_TOKEN")})
    except FacebookError:
        return []
    return [p["permission"] for p in data.get("data", []) if p.get("status") == "granted"]
