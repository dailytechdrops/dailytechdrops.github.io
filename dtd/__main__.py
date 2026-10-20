"""Command line entry point.

  python -m dtd render  --week weeks/2026-10-26.yaml   render every product in a week -> output/<id>/
  python -m dtd preview --week weeks/2026-10-26.yaml   print a markdown preview of the week
  python -m dtd post-due                               post the next product whose time has come
  python -m dtd reply                                  DM the link to anyone who commented the keyword
  python -m dtd refresh-token                          print a refreshed Instagram token
"""

import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import zlib
from datetime import datetime, timedelta
from pathlib import Path

from . import facebook, instagram, shop
from .carousel import render_carousel
from .config import EASTERN, OUTPUT_DIR, affiliate_link, env, load_all_weeks, load_config, load_week, read_state, write_state
from .reel import render_reel
from .writer import full_caption, write_content

# A post whose time passed longer ago than this is skipped rather than posted late.
STALE_AFTER = timedelta(hours=6)
# A link DM that keeps failing (for example, the person blocks messages) is dropped after this many tries.
MAX_DM_ATTEMPTS = 3


def render(cfg: dict, week: Path) -> int:
    for item in load_week(week):
        out = OUTPUT_DIR / item["id"]
        content = write_content(cfg, item)
        reel = render_reel(cfg, content, out / "work")
        reel.rename(out / "reel.mp4")
        # Optional extra reels in other free voices, for comparing before choosing one.
        # Names are Piper voices, or kokoro:<voice> for Kokoro.
        for voice in os.environ.get("EXTRA_VOICES", "").split():
            alt = copy.deepcopy(cfg)
            if voice.startswith("kokoro:"):
                alt["voice"]["provider"], alt["voice"]["kokoro_voice"] = "kokoro", voice.split(":", 1)[1]
            else:
                alt["voice"]["provider"], alt["voice"]["piper_voice"] = "piper", voice
            voice = voice.replace(":", "-")
            render_reel(alt, content, out / "work" / voice).rename(out / f"reel-{voice}.mp4")
        slides = render_carousel(cfg, content, out)
        link = affiliate_link(cfg, item["asin"])
        draft = {
            "id": item["id"],
            "slot": item["when"].isoformat(),
            "name": item["name"],
            "asin": item["asin"],
            "lane": item.get("lane"),
            "link": link,
            "caption": full_caption(cfg, content),
            "dm_message": content.dm_message.replace("{link}", link),
            "slides": [p.name for p in slides],
        }
        (out / "draft.json").write_text(json.dumps(draft, indent=2))
        shutil.rmtree(out / "work")
        print(f"Rendered {item['id']}: {item['name']}")
    return 0


def preview(cfg: dict, week: Path, base: str) -> int:
    print(f"### Week of {week.stem}\n")
    print("Merging this pull request approves every post below.\n")
    for item in load_week(week):
        raw = f"{base}/{item['id']}"
        # GitHub's raw links download instead of playing on phones; jsDelivr streams the same file.
        phone = f"https://cdn.jsdelivr.net/gh/{os.environ.get('GITHUB_REPOSITORY', '')}@media/{item['id']}/reel.mp4"
        print(f"**{item['when']:%a %b %d, %-I:%M %p} ET: {item['name']}**  ")
        print(f"[Watch on phone]({phone}) · [Reel file]({raw}/reel.mp4) · [Amazon](https://www.amazon.com/dp/{item['asin']})\n")
        print(f'<img src="{raw}/slide_1.jpg" width="200"> <img src="{raw}/slide_2.jpg" width="200">\n')
    return 0


def post_due(cfg: dict) -> int:
    if not (env("IG_USER_ID") and env("IG_ACCESS_TOKEN")):
        print("Instagram secrets not set yet; skipping.")
        return 0
    now = datetime.now(EASTERN)
    history = read_state("history", [])
    posted = {h["id"] for h in history}
    due = sorted((i for i in load_all_weeks() if i["id"] not in posted and i["when"] <= now), key=lambda i: i["when"])
    for item in due:
        if now - item["when"] > STALE_AFTER:
            print(f"Skipping {item['id']}: its time passed more than {STALE_AFTER} ago")
            history.append({"id": item["id"], "skipped": True})
            continue
        try:
            _publish(item["id"], history)
        except Exception as e:
            # Run logs are hard to read; an error annotation shows the cause on the run page.
            print(f"::error title=Post failed::{item['id']}: {type(e).__name__}: {str(e)[:500]}")
            raise
        break  # one product per run keeps posts spaced out if several are due
    else:
        print("Nothing due.")
    write_state("history", history)
    shop.build(cfg, history)
    return 0


def _publish(item_id: str, history: list) -> None:
    out = OUTPUT_DIR / item_id
    if not out.exists():
        # Rendered media lives on the media branch; pull just this product's folder.
        OUTPUT_DIR.mkdir(exist_ok=True)
        archive = subprocess.run(["git", "archive", "origin/media", item_id], capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", str(OUTPUT_DIR)], input=archive.stdout, check=True)
    draft = json.loads((out / "draft.json").read_text())
    base = env("MEDIA_BASE_URL") or f"https://raw.githubusercontent.com/{os.environ.get('GITHUB_REPOSITORY', '')}/media"
    reel_id = instagram.publish_reel(out / "reel.mp4", draft["caption"], f"{base}/{item_id}/reel.mp4")
    carousel_id = None
    try:
        carousel_id = instagram.publish_carousel([f"{base}/{item_id}/{s}" for s in draft["slides"]], draft["caption"])
    except instagram.InstagramError as e:
        # The reel is the main post; a failed carousel should not undo it.
        print(f"Carousel failed, reel is live: {e}", file=sys.stderr)
    facebook_id = None
    if facebook.configured():
        try:
            facebook_id = facebook.publish_reel(out / "reel.mp4", facebook.caption_for_facebook(draft["caption"], draft["link"]))
        except facebook.FacebookError as e:
            # Cross-posting is a bonus; never undo or block the Instagram post.
            print(f"Facebook reel failed, Instagram is live: {e}", file=sys.stderr)
    history.append({
        "facebook_id": facebook_id,
        "id": item_id, "asin": draft["asin"], "name": draft["name"], "link": draft["link"],
        "dm_message": draft["dm_message"], "media_ids": [m for m in (reel_id, carousel_id) if m],
    })
    print(f"Published {item_id}: reel {reel_id}, carousel {carousel_id}")


def reply(cfg: dict) -> int:
    if not (env("IG_USER_ID") and env("IG_ACCESS_TOKEN")):
        # Runs every 30 minutes; stay quiet until Instagram is connected.
        print("Instagram secrets not set yet; skipping.")
        return 0
    ig = cfg["instagram"]
    words = [ig["comment_keyword"], *ig.get("comment_aliases", [])]
    wanted = re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b", re.IGNORECASE)
    handle = cfg["brand"]["handle"].lower()
    by_media = {m: h for h in read_state("history", []) for m in h.get("media_ids", [])}
    replied = set(read_state("replied", []))
    failures = read_state("reply_failures", {})
    sent = 0
    recent = instagram.recent_media(days=7)
    seen = []
    for media in recent:
        post = by_media.get(media["id"])
        if not post:
            continue
        for c in instagram.comments(media["id"]):
            seen.append(f"{c.get('username')}:{c.get('text', '')[:20]!r}")
            user = c.get("username", "")
            if c["id"] in replied or user.lower() == handle or not wanted.search(c.get("text", "")):
                continue
            try:
                instagram.private_reply(c["id"], _dm_text(cfg, post, user))
            except instagram.InstagramError as e:
                failures[c["id"]] = failures.get(c["id"], 0) + 1
                print(f"DM for comment {c['id']} failed (attempt {failures[c['id']]}): {e}", file=sys.stderr)
                if failures[c["id"]] >= MAX_DM_ATTEMPTS:
                    replied.add(c["id"])  # give up rather than retry every run for a week
                continue
            # The DM went out, so never send it again even if the public reply fails.
            replied.add(c["id"])
            failures.pop(c["id"], None)
            sent += 1
            try:
                instagram.public_reply(c["id"], _public_reply_text(cfg, c["id"], user))
            except instagram.InstagramError as e:
                print(f"Public reply to {c['id']} failed: {e}", file=sys.stderr)
    write_state("replied", sorted(replied))
    write_state("reply_failures", {k: v for k, v in failures.items() if k not in replied})
    print(f"::notice title=Reply scan::{len(recent)} recent posts, {len(by_media)} tracked, comments seen: {seen[:10]}")
    print(f"Sent {sent} link DMs")
    return 0


def _dm_text(cfg: dict, post: dict, user: str) -> str:
    template = cfg["instagram"].get("dm_template")
    if not template:
        return post["dm_message"]
    greeting = f"@{user}" if user else "there"
    return template.format(user=greeting, name=post["name"], link=post["link"]).strip()


def _public_reply_text(cfg: dict, comment_id: str, user: str) -> str:
    # Rotating the wording keeps identical replies from looking like spam to Instagram.
    options = cfg["instagram"].get("public_replies") or ["Sent! Check your DMs."]
    text = options[zlib.crc32(comment_id.encode()) % len(options)]
    return text.format(user=f"@{user}" if user else "").replace("  ", " ").strip()


def main() -> int:
    parser = argparse.ArgumentParser(prog="dtd")
    parser.add_argument("command", choices=["render", "preview", "post-due", "reply", "refresh-token"])
    parser.add_argument("--week", type=Path)
    parser.add_argument("--base", default="", help="media URL base for preview links")
    args = parser.parse_args()
    cfg = load_config()
    if args.command == "render":
        return render(cfg, args.week)
    if args.command == "preview":
        return preview(cfg, args.week, args.base)
    if args.command == "post-due":
        return post_due(cfg)
    if args.command == "reply":
        return reply(cfg)
    print(instagram.refresh_token())
    return 0


if __name__ == "__main__":
    sys.exit(main())
