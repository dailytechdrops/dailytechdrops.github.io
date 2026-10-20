"""Command line entry point.

  python -m dtd generate [--date YYYY-MM-DD]   research pick, script, reel, carousel -> output/<date>/
  python -m dtd publish  --date YYYY-MM-DD     post the reel and carousel for that date
  python -m dtd reply                          DM the link to anyone who commented the keyword
  python -m dtd refresh-token                  print a refreshed Instagram token
"""

import argparse
import json
import os
import re
import sys
from datetime import date

from . import instagram
from .carousel import render_carousel
from .config import OUTPUT_DIR, affiliate_link, env, load_config, read_state, write_state
from .products import next_product
from .reel import render_reel
from .writer import full_caption, write_content


def generate(cfg: dict, day: str) -> int:
    product = next_product(cfg)
    if not product:
        print("Product queue is empty. Add products to products.yaml.", file=sys.stderr)
        return 2
    out = OUTPUT_DIR / day
    content = write_content(cfg, product)
    reel = render_reel(cfg, content, out / "work")
    reel.rename(out / "reel.mp4")
    slides = render_carousel(cfg, content, out)
    link = affiliate_link(cfg, product["asin"])
    draft = {
        "date": day,
        "product": product,
        "link": link,
        "caption": full_caption(cfg, content),
        "dm_message": content.dm_message.replace("{link}", link),
        "beats": [b.model_dump() for b in content.beats],
        "slides": [p.name for p in slides],
    }
    (out / "draft.json").write_text(json.dumps(draft, indent=2))
    for f in (out / "work").iterdir():
        f.unlink()
    (out / "work").rmdir()
    print(f"Draft ready: {out} ({product['name']})")
    _gh_output("product", product["name"])
    return 0


def publish(cfg: dict, day: str) -> int:
    out = OUTPUT_DIR / day
    draft = json.loads((out / "draft.json").read_text())
    history = read_state("history", [])
    if any(h["date"] == day for h in history):
        print(f"{day} already published; skipping.")
        return 0

    reel_id = instagram.publish_reel(out / "reel.mp4", draft["caption"])
    base = env("MEDIA_BASE_URL") or f"https://raw.githubusercontent.com/{os.environ.get('GITHUB_REPOSITORY', '')}/media"
    carousel_id = None
    try:
        carousel_id = instagram.publish_carousel([f"{base}/{day}/{s}" for s in draft["slides"]], draft["caption"])
    except instagram.InstagramError as e:
        # The reel is the main post; a failed carousel should not undo it.
        print(f"Carousel failed, reel is live: {e}", file=sys.stderr)

    history.append({
        "date": day, "asin": draft["product"]["asin"], "lane": draft["product"].get("lane"),
        "name": draft["product"]["name"], "link": draft["link"], "dm_message": draft["dm_message"],
        "media_ids": [m for m in (reel_id, carousel_id) if m],
    })
    write_state("history", history)
    print(f"Published {day}: reel {reel_id}, carousel {carousel_id}")
    return 0 if carousel_id else 1


def reply(cfg: dict) -> int:
    keyword = cfg["instagram"]["comment_keyword"].lower()
    handle = cfg["brand"]["handle"].lower()
    by_media = {m: h for h in read_state("history", []) for m in h["media_ids"]}
    replied = set(read_state("replied", []))
    sent = 0
    for media in instagram.recent_media(days=7):
        post = by_media.get(media["id"])
        if not post:
            continue
        for c in instagram.comments(media["id"]):
            if c["id"] in replied or c.get("username", "").lower() == handle:
                continue
            if re.search(rf"\b{re.escape(keyword)}\b", c.get("text", "").lower()):
                try:
                    instagram.private_reply(c["id"], post["dm_message"])
                    instagram.public_reply(c["id"], "Sent! Check your DMs.")
                    sent += 1
                except instagram.InstagramError as e:
                    print(f"Reply to {c['id']} failed: {e}", file=sys.stderr)
                    continue
                replied.add(c["id"])
    write_state("replied", sorted(replied))
    print(f"Sent {sent} link DMs")
    return 0


def _gh_output(key: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write(f"{key}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(prog="dtd")
    parser.add_argument("command", choices=["generate", "publish", "reply", "refresh-token"])
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()
    cfg = load_config()
    if args.command == "generate":
        return generate(cfg, args.date)
    if args.command == "publish":
        return publish(cfg, args.date)
    if args.command == "reply":
        return reply(cfg)
    print(instagram.refresh_token())
    return 0


if __name__ == "__main__":
    sys.exit(main())
