"""Pinterest video Pins (Pinterest API v5), one per reel already posted to Instagram.

Needs the PINTEREST_APP_SECRET and PINTEREST_REFRESH_TOKEN secrets; the app id is in config.yaml.
Without them nothing is pinned. The refresh token comes from the one-time "Connect Pinterest"
workflow, and every refresh hands back a new one, which the workflow saves over the old secret.

Pinterest keeps Pins made by an app on Trial access visible only to the account owner. They
go public once the app is upgraded to Standard access (developers.pinterest.com > the app >
Upgrade access); nothing here changes when that happens.
"""

import base64
import time
from pathlib import Path

import requests

from .config import env

API = "https://api.pinterest.com/v5"
SHOP_URL = "https://kevingalus.github.io/daily-tech-drops/"
# Pinterest caps titles at 100 characters and descriptions at 800.
MAX_TITLE = 100
MAX_DESCRIPTION = 800


class PinterestError(RuntimeError):
    pass


def configured() -> bool:
    return bool(env("PINTEREST_APP_SECRET") and env("PINTEREST_REFRESH_TOKEN"))


def _call(method: str, path: str, token: str, **kwargs) -> dict:
    r = requests.request(method, f"{API}{path}", timeout=120, headers={"Authorization": f"Bearer {token}"}, **kwargs)
    if r.status_code >= 400:
        raise PinterestError(f"{method} {path} failed {r.status_code}: {r.text[:500]}")
    return r.json()


def _oauth(cfg: dict, data: dict) -> dict:
    basic = base64.b64encode(f"{cfg['pinterest']['app_id']}:{env('PINTEREST_APP_SECRET')}".encode()).decode()
    r = requests.post(f"{API}/oauth/token", timeout=60, data=data, headers={"Authorization": f"Basic {basic}"})
    if r.status_code >= 400:
        raise PinterestError(f"Pinterest token request failed {r.status_code}: {r.text[:500]}")
    return r.json()


def exchange_code(cfg: dict, code: str) -> str:
    """Turns the one-time code from the Connect page into a refresh token."""
    tokens = _oauth(cfg, {
        "grant_type": "authorization_code", "code": code.strip(),
        "redirect_uri": cfg["pinterest"]["redirect_uri"], "continuous_refresh": "true",
    })
    return tokens["refresh_token"]


def access_token(cfg: dict, new_refresh_file: str | None = None) -> str:
    """A fresh access token. Pinterest's continuous refresh also returns a new refresh token;
    it is written to new_refresh_file so the workflow can save it as the secret."""
    tokens = _oauth(cfg, {"grant_type": "refresh_token", "refresh_token": env("PINTEREST_REFRESH_TOKEN")})
    if new_refresh_file and tokens.get("refresh_token"):
        Path(new_refresh_file).write_text(tokens["refresh_token"])
    return tokens["access_token"]


def board_for(cfg: dict, lane: str | None, token: str) -> str:
    """The board id for a product's lane: the first keyword in pinterest.boards found in the
    lane text, else pinterest.default_board. Boards are looked up by name."""
    pc = cfg["pinterest"]
    lane = (lane or "").lower()
    name = next((board for word, board in pc["boards"].items() if word in lane), pc["default_board"])
    boards = _call("GET", "/boards", token, params={"page_size": 100}).get("items", [])
    for b in boards:
        if b["name"] == name:
            return b["id"]
    raise PinterestError(f"No board named {name!r}; boards are {[b['name'] for b in boards]}")


def title_for(name: str) -> str:
    return name[:MAX_TITLE].rstrip()


def description_for(cfg: dict, draft: dict) -> str:
    """The caption's opening line, where to find it, and the disclosure. No prices (Associates rule)."""
    first = next((l for l in draft["caption"].splitlines() if l.strip()), "").strip()
    tail = "\n\n".join([
        f"Find the {draft['name']} and every gadget we post on our shop page.",
        "Prices change often, so check Amazon for today's price.",
        "#techgadgets #amazonfinds #coolgadgets #giftideas",
        cfg["instagram"]["disclosure"],
    ])
    return (first[: MAX_DESCRIPTION - len(tail) - 2] + "\n\n" + tail).strip()


def _upload_video(video: Path, token: str) -> str:
    media = _call("POST", "/media", token, json={"media_type": "video"})
    with video.open("rb") as f:
        r = requests.post(media["upload_url"], timeout=600, data=media["upload_parameters"], files={"file": f})
    if r.status_code >= 400:
        raise PinterestError(f"Video upload failed {r.status_code}: {r.text[:500]}")
    deadline = time.time() + 600
    while True:
        status = _call("GET", f"/media/{media['media_id']}", token).get("status")
        if status == "succeeded":
            return media["media_id"]
        if status == "failed":
            raise PinterestError("Pinterest could not process the video")
        if time.time() > deadline:
            raise PinterestError("Timed out waiting for Pinterest to process the video")
        time.sleep(10)


def follower_count(token: str) -> int:
    """Needs the user_accounts:read scope, which the Connect page asks for."""
    return int(_call("GET", "/user_account", token).get("follower_count", 0))


def publish_video(cfg: dict, video: Path, cover_url: str | None, draft: dict, new_refresh_file: str | None = None, token: str | None = None) -> str:
    token = token or access_token(cfg, new_refresh_file)
    board = board_for(cfg, draft.get("lane"), token)
    media_id = _upload_video(video, token)
    source = {"source_type": "video_id", "media_id": media_id}
    if cover_url:
        source["cover_image_url"] = cover_url
    else:
        source["cover_image_key_frame_time"] = 1
    pin = _call("POST", "/pins", token, json={
        "board_id": board,
        "title": title_for(draft["name"]),
        "description": description_for(cfg, draft),
        "link": f"{SHOP_URL}?utm_source=pinterest",
        "alt_text": draft["name"],
        "media_source": source,
    })
    return pin["id"]
