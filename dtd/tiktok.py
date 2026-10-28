"""TikTok posts, sent through Buffer's API (api.buffer.com, GraphQL).

TikTok's own Content Posting API only lets audited apps post publicly, and its rules turn
down apps that post only to the owner's accounts. Buffer is an audited TikTok partner, and
its API is free on the free plan, so reels go to TikTok through Buffer instead.

Needs BUFFER_API_KEY (Buffer, Settings, API) with the daily_tech_drops TikTok account
connected as a Buffer channel. Optional: without it nothing is posted. Posting also waits
for the repo variable TIKTOK_POSTING to be "on", so the connection can be tested first.
"""

import requests

from .config import env

API = "https://api.buffer.com"
# No clickable bio link until 1,000 followers, so the shop page address is spelled out.
SHOP_LINE = "Every gadget we post: dailytechdrops.github.io"
# TikTok captions allow 2,200 characters; stay well under it.
MAX_TEXT = 2000


class TikTokError(RuntimeError):
    pass


def configured() -> bool:
    return bool(env("BUFFER_API_KEY"))


def enabled() -> bool:
    return configured() and (env("TIKTOK_POSTING") or "").lower() == "on"


def _gql(query: str, variables: dict | None = None) -> dict:
    if not env("BUFFER_API_KEY").isascii():
        raise TikTokError("BUFFER_API_KEY is not a real key (it has non-letter symbols, e.g. copied masked dots); paste the key again")
    r = requests.post(API, timeout=120, json={"query": query, "variables": variables or {}},
                      headers={"Authorization": f"Bearer {env('BUFFER_API_KEY')}"})
    if r.status_code >= 400:
        raise TikTokError(f"Buffer API failed {r.status_code}: {r.text[:500]}")
    body = r.json()
    if body.get("errors"):
        raise TikTokError(f"Buffer API error: {str(body['errors'])[:500]}")
    return body["data"]


def channel_id() -> str:
    """The TikTok channel in the Buffer account. Found by looking, so only the API key is a secret."""
    orgs = _gql("query { account { organizations { id } } }")["account"]["organizations"]
    for org in orgs:
        channels = _gql("query($org: OrganizationId!) { channels(input: {organizationId: $org}) { id service name } }",
                        {"org": org["id"]})["channels"]
        for ch in channels:
            if ch["service"].lower() == "tiktok":
                return ch["id"]
    raise TikTokError("No TikTok channel is connected in Buffer")


def share_modes() -> list[str]:
    """What Buffer accepts as a post mode, read from its schema, to check shareNow before posting goes live."""
    t = _gql('query { __type(name: "ShareMode") { enumValues { name } } }')["__type"]
    return [v["name"] for v in (t or {}).get("enumValues", [])]


def text_for_tiktok(caption: str, disclosure: str) -> str:
    """The Instagram caption, minus the comment-SHOP-for-a-DM lines (no DMs on TikTok, and
    TikTok captions cannot hold links), plus the shop page address. Disclosure stays last."""
    lines = [l for l in caption.strip().splitlines() if l.strip() != disclosure]
    body = [l for l in lines if not ("SHOP" in l and "omment" in l)]
    while body and not body[-1].strip():
        body.pop()
    tags = body.pop() if body and body[-1].lstrip().startswith("#") else ""
    text = "\n".join(body).strip() + f"\n\n{SHOP_LINE}"
    tail = (f"\n\n{tags}" if tags else "") + f"\n\n{disclosure}"
    return text[: MAX_TEXT - len(tail)] + tail


def publish_video(video_url: str, text: str) -> str:
    """Asks Buffer to post the video to TikTok now. Returns Buffer's post id."""
    data = _gql("""
        mutation($input: CreatePostInput!) {
          createPost(input: $input) {
            ... on PostActionSuccess { post { id } }
            ... on MutationError { message }
          }
        }""", {"input": {
        "channelId": channel_id(), "text": text, "schedulingType": "automatic", "mode": "shareNow",
        "assets": [{"video": {"url": video_url}}],
    }})["createPost"]
    if "post" not in data:
        raise TikTokError(f"Buffer refused the post: {data.get('message')}")
    return data["post"]["id"]
