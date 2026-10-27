"""Instagram API with Instagram Login (graph.instagram.com).

Needs IG_USER_ID and IG_ACCESS_TOKEN with the scopes instagram_business_basic,
instagram_business_content_publish, instagram_business_manage_comments,
instagram_business_manage_messages and (for the weekly report)
instagram_business_manage_insights.
"""

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from .config import env

API = "https://graph.instagram.com/v23.0"


class InstagramError(RuntimeError):
    pass


def _creds() -> tuple[str, str]:
    user, token = env("IG_USER_ID"), env("IG_ACCESS_TOKEN")
    if not user or not token:
        raise InstagramError("IG_USER_ID and IG_ACCESS_TOKEN must be set")
    return user, token


def _call(method: str, url: str, **kwargs) -> dict:
    r = requests.request(method, url, timeout=120, **kwargs)
    if r.status_code >= 400:
        raise InstagramError(f"{method} {url.split('?')[0]} failed {r.status_code}: {r.text[:500]}")
    return r.json()


def publish_reel(video: Path, caption: str, video_url: str | None = None) -> str:
    """Uploads the local file directly (resumable upload); if Instagram refuses that,
    falls back to letting it fetch the file from a public URL."""
    user, token = _creds()
    try:
        container = _call("POST", f"{API}/{user}/media", params={
            "media_type": "REELS", "upload_type": "resumable", "caption": caption,
            "share_to_feed": "true", "thumb_offset": "500", "access_token": token,
        })
        size = video.stat().st_size
        _call("POST", container["uri"], headers={
            "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size),
        }, data=video.read_bytes())
    except InstagramError as e:
        if not video_url:
            raise
        print(f"Resumable upload refused ({e}); using the public URL instead", file=sys.stderr)
        container = _call("POST", f"{API}/{user}/media", params={
            "media_type": "REELS", "video_url": video_url, "caption": caption,
            "share_to_feed": "true", "thumb_offset": "500", "access_token": token,
        })
    _wait_ready(container["id"], token)
    return _publish(user, token, container["id"])


def publish_carousel(image_urls: list[str], caption: str) -> str:
    """Instagram fetches images itself, so each URL must be publicly reachable."""
    user, token = _creds()
    children = []
    for url in image_urls:
        child = _call("POST", f"{API}/{user}/media", params={
            "image_url": url, "is_carousel_item": "true", "access_token": token,
        })
        children.append(child["id"])
    for child in children:
        _wait_ready(child, token)
    parent = _call("POST", f"{API}/{user}/media", params={
        "media_type": "CAROUSEL", "children": ",".join(children), "caption": caption, "access_token": token,
    })
    _wait_ready(parent["id"], token)
    return _publish(user, token, parent["id"])


def publish_story(image_url: str) -> str:
    """A Story from one public image. The API cannot add link stickers, so this is for reach only."""
    user, token = _creds()
    container = _call("POST", f"{API}/{user}/media", params={
        "media_type": "STORIES", "image_url": image_url, "access_token": token,
    })
    _wait_ready(container["id"], token)
    return _publish(user, token, container["id"])


def _wait_ready(container_id: str, token: str, timeout_s: int = 600) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        status = _call("GET", f"{API}/{container_id}", params={"fields": "status_code,status", "access_token": token})
        code = status.get("status_code")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise InstagramError(f"Container {container_id} {code}: {status.get('status')}")
        time.sleep(10)
    raise InstagramError(f"Container {container_id} not ready after {timeout_s}s")


def _publish(user: str, token: str, container_id: str, attempts: int = 5) -> str:
    # Right after a container reports FINISHED, Instagram sometimes still answers "Media Not Found"
    # (2207006) or "not ready" (9007). Nothing was published in that case, so a retry is safe.
    for attempt in range(attempts):
        try:
            result = _call("POST", f"{API}/{user}/media_publish", params={"creation_id": container_id, "access_token": token})
            return result["id"]
        except InstagramError as e:
            if attempt == attempts - 1 or not any(code in str(e) for code in ("2207006", "2207027", '"code":9007')):
                raise
            time.sleep(20)
    raise AssertionError("unreachable")


def recent_media(days: int = 7) -> list[dict]:
    user, token = _creds()
    data = _call("GET", f"{API}/{user}/media", params={"fields": "id,timestamp", "limit": 25, "access_token": token})
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return [m for m in data.get("data", []) if _ts(m["timestamp"]) >= cutoff]


def comments(media_id: str) -> list[dict]:
    _, token = _creds()
    data = _call("GET", f"{API}/{media_id}/comments", params={"fields": "id,text,username,timestamp", "limit": 50, "access_token": token})
    return data.get("data", [])


def comments_with_replies(media_id: str) -> list[dict]:
    """Top-level comments plus who already replied to each, so a comment someone (us, Meta Business
    Suite, or Kevin by hand) already answered is never answered twice."""
    _, token = _creds()
    data = _call("GET", f"{API}/{media_id}/comments", params={"fields": "id,text,username,timestamp,replies{username}", "limit": 50, "access_token": token})
    return data.get("data", [])


def private_reply(comment_id: str, text: str) -> None:
    """Sends a DM to the commenter. Instagram allows one per comment, within 7 days."""
    user, token = _creds()
    _call("POST", f"{API}/{user}/messages", params={"access_token": token},
          json={"recipient": {"comment_id": comment_id}, "message": {"text": text}})


def comment(media_id: str, text: str) -> str:
    """A comment from our own account on our own post. The API has no way to pin it."""
    _, token = _creds()
    return _call("POST", f"{API}/{media_id}/comments", params={"message": text, "access_token": token})["id"]


def public_reply(comment_id: str, text: str) -> None:
    _, token = _creds()
    _call("POST", f"{API}/{comment_id}/replies", params={"message": text, "access_token": token})


def account() -> dict:
    user, token = _creds()
    return _call("GET", f"{API}/{user}", params={"fields": "username,followers_count,media_count", "access_token": token})


def media_since(since: datetime) -> list[dict]:
    """Every post published at or after since, newest first."""
    user, token = _creds()
    fields = "id,timestamp,caption,media_type,media_product_type,permalink,like_count,comments_count"
    url, params, found = f"{API}/{user}/media", {"fields": fields, "limit": 50, "access_token": token}, []
    while url:
        data = _call("GET", url, params=params)
        page = data.get("data", [])
        found += [m for m in page if _ts(m["timestamp"]) >= since]
        if not page or _ts(page[-1]["timestamp"]) < since:
            break
        url, params = data.get("paging", {}).get("next"), None
    return found


def media_insights(media_id: str, metrics: list[str]) -> dict[str, float]:
    """Lifetime totals per metric. Metrics Instagram rejects for this post are left out."""
    _, token = _creds()
    try:
        data = _call("GET", f"{API}/{media_id}/insights", params={"metric": ",".join(metrics), "access_token": token})
    except InstagramError:
        # One unsupported metric fails the whole request, so fall back to asking one at a time.
        if len(metrics) == 1:
            return {}
        return {k: v for m in metrics for k, v in media_insights(media_id, [m]).items()}
    return {d["name"]: _value(d) for d in data.get("data", [])}


def account_insights(metrics: list[str], since: datetime, until: datetime) -> dict[str, float]:
    """Account totals over a window of up to 30 days."""
    user, token = _creds()
    out = {}
    for metric in metrics:
        try:
            data = _call("GET", f"{API}/{user}/insights", params={
                "metric": metric, "period": "day", "metric_type": "total_value",
                "since": int(since.timestamp()), "until": int(until.timestamp()), "access_token": token,
            })
        except InstagramError as e:
            print(f"Account metric {metric} unavailable: {e}")
            continue
        out.update({d["name"]: _value(d) for d in data.get("data", [])})
    return out


def _value(entry: dict) -> float:
    if "total_value" in entry:
        return entry["total_value"].get("value", 0)
    return sum(v.get("value", 0) for v in entry.get("values", []) if isinstance(v.get("value"), (int, float)))


def refresh_token() -> str:
    """Long-lived tokens last 60 days; refreshing returns a token good for another 60."""
    _, token = _creds()
    data = _call("GET", f"{API.rsplit('/', 1)[0]}/refresh_access_token", params={"grant_type": "ig_refresh_token", "access_token": token})
    return data["access_token"]


def _ts(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")
