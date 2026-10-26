"""Threads posts (graph.threads.net), a third place every reel goes after Instagram and Facebook.

Needs THREADS_USER_ID and THREADS_ACCESS_TOKEN, a long-lived Threads token with the scopes
threads_basic and threads_content_publish, from the same Meta app. Both are optional: without
them nothing is posted to Threads. The token lasts 60 days and is renewed monthly.
"""

import time

import requests

from .config import env

API = "https://graph.threads.net/v1.0"
# Threads caps a post at 500 characters.
MAX_TEXT = 500


class ThreadsError(RuntimeError):
    pass


def configured() -> bool:
    return bool(env("THREADS_USER_ID") and env("THREADS_ACCESS_TOKEN"))


def _call(method: str, url: str, **kwargs) -> dict:
    r = requests.request(method, url, timeout=120, **kwargs)
    if r.status_code >= 400:
        raise ThreadsError(f"{method} {url.split('?')[0]} failed {r.status_code}: {r.text[:500]}")
    return r.json()


def text_for_threads(caption: str, link: str, disclosure: str) -> str:
    """The caption's opening line, the Amazon link and the disclosure. Threads has no
    comment-for-link DM here, so the link goes in the post itself, like on Facebook."""
    first = next((l for l in caption.splitlines() if l.strip()), "").strip()
    tail = f"\n\nGet it on Amazon: {link}\n\n{disclosure}"
    return first[: MAX_TEXT - len(tail)] + tail


def publish_video(video_url: str, text: str) -> str:
    user, token = env("THREADS_USER_ID"), env("THREADS_ACCESS_TOKEN")
    if not (user and token):
        raise ThreadsError("THREADS_USER_ID and THREADS_ACCESS_TOKEN must be set")
    container = _call("POST", f"{API}/{user}/threads", data={
        "media_type": "VIDEO", "video_url": video_url, "text": text, "access_token": token,
    })["id"]
    deadline = time.time() + 600
    while True:
        status = _call("GET", f"{API}/{container}", params={"fields": "status,error_message", "access_token": token})
        if status.get("status") == "FINISHED":
            break
        if status.get("status") in ("ERROR", "EXPIRED"):
            raise ThreadsError(f"Threads rejected the video: {status}")
        if time.time() > deadline:
            raise ThreadsError("Timed out waiting for Threads to process the video")
        time.sleep(10)
    return _call("POST", f"{API}/{user}/threads_publish", data={"creation_id": container, "access_token": token})["id"]


def refresh_token() -> str:
    token = env("THREADS_ACCESS_TOKEN")
    if not token:
        raise ThreadsError("THREADS_ACCESS_TOKEN must be set")
    return _call("GET", "https://graph.threads.net/refresh_access_token",
                 params={"grant_type": "th_refresh_token", "access_token": token})["access_token"]
