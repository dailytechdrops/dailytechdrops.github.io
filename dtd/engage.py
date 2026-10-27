"""Friendly public replies to comments on our posts, with a nudge to comment SHOP.

Runs every 30 minutes (workflow "Comment replies"). For each new top-level comment from someone
else on an Instagram post (and a Facebook reel, when the Page token allows it) from the last
few days, it sorts the comment into one kind and posts one short reply from config.yaml:

  price     asks the price: never state one (Amazon rules); nudge to SHOP for today's price
  want      asks where to get it, for the link, the name: nudge to SHOP
  question  any other question: point to the Amazon listing, nudge to SHOP
  praise    likes it: say thanks, sometimes with a soft SHOP nudge

Never answered: comments that say the keyword (Meta Business Suite already DMs those, so we
stay out of the way), comments anyone on our side already replied to, our own comments,
comments with links or that look like spam, and anything that fits no kind. Replies carry no
link and no price, so they need no Amazon disclosure. Each comment is answered at most once.
"""

import re
import sys
import zlib
from datetime import datetime, timedelta, timezone

from . import facebook, instagram
from .config import env, read_state, write_state

# Comments older than this are left alone, so the first run does not answer a backlog at once.
MAX_AGE = timedelta(days=3)
# Remembered comment ids are dropped after this long; their posts are long past MAX_AGE by then.
FORGET_AFTER = timedelta(days=14)
# At most this many replies per platform per run, so a busy post never looks like a reply bot.
MAX_PER_RUN = 8

PRICE = re.compile(r"\b(price|prices|pricing|cost|costs|how much)\b|\$", re.IGNORECASE)
WANT = re.compile(
    r"\b(where (can|do|could|did|would) (i|you|we|one)|where to (get|buy|find)|where('?s| is) (it|this) from|"
    r"(send|drop|share|give)( me)? (the |a )?(link|name)|what('?s| is) (it|this|the) (called|name|brand|model)|"
    r"name of (it|this|the)|brand|model|buy|purchase|order|need (this|one|it|that|these)|want (this|one|it|that|these)|"
    r"take my money|add(ed|ing)? to (my )?cart|amazon)\b",
    re.IGNORECASE,
)
PRAISE = re.compile(
    r"\b(cool|love|loving|awesome|nice|amazing|wow|great|neat|sick|fire|genius|clever|smart|handy|useful|"
    r"brilliant|dope|sweet|perfect|beautiful|cute|so good|game ?changer|need|want|omg)\b|[🔥😍👏🙌❤💯👍🤩😮😲🤯💙💜🖤🧡💛💚♥]",
    re.IGNORECASE,
)
SPAM = re.compile(
    r"https?://|www\.|\.com\b|\b(promot\w*|collab\w*|ambassador|dm (us|me)|send (a )?pic|check my|follow (me|back)|"
    r"giveaway|crypto|invest\w*|forex|bitcoin|onlyfans|earn \$|free followers)\b",
    re.IGNORECASE,
)


def classify(text: str, keyword_words: list[str]) -> str | None:
    """Which kind of reply a comment gets, or None to leave it alone."""
    text = (text or "").strip()
    if not text or SPAM.search(text):
        return None
    if re.search(r"\b(" + "|".join(re.escape(w) for w in keyword_words) + r")\b", text, re.IGNORECASE):
        return None  # the SHOP auto-DM in Meta Business Suite answers these
    if re.fullmatch(r"(@[\w.]+\s*)+", text):
        return None  # only tags a friend; nothing to add
    if PRICE.search(text):
        return "price"
    if WANT.search(text):
        return "want"
    if "?" in text:
        return "question"
    if PRAISE.search(text):
        return "praise"
    return None


def reply_text(cfg: dict, kind: str, comment_id: str, user: str) -> str:
    # Rotating the wording keeps identical replies from looking like spam.
    options = cfg["engagement"]["replies"][kind]
    text = options[zlib.crc32(comment_id.encode()) % len(options)]
    return re.sub(r"\s+([!,.?])", r"\1", text.format(user=f"@{user}" if user else "").replace("  ", " ")).strip()


def run(cfg: dict) -> int:
    eng = cfg.get("engagement", {})
    dry = bool(env("ENGAGE_DRY_RUN")) or not eng.get("enabled", False)
    words = [cfg["instagram"]["comment_keyword"], *cfg["instagram"].get("comment_aliases", [])]
    done = read_state("engaged", {})
    now = datetime.now(timezone.utc)
    lines = []
    if env("IG_USER_ID") and env("IG_ACCESS_TOKEN"):
        lines += _instagram(cfg, words, done, now, dry)
    else:
        lines.append("Instagram secrets not set; skipped.")
    if facebook.configured() and eng.get("facebook", True):
        lines += _facebook(cfg, words, done, now, dry)
    cutoff = (now - FORGET_AFTER).isoformat()
    write_state("engaged", {k: v for k, v in done.items() if v.get("at", "") >= cutoff})
    print(("DRY RUN, nothing posted.\n" if dry else "") + "\n".join(lines))
    return 0


def _instagram(cfg: dict, words: list[str], done: dict, now: datetime, dry: bool) -> list[str]:
    handle = cfg["brand"]["handle"].lower()
    lines, sent, read = [], 0, 0
    recent = instagram.recent_media(days=7)
    for media in recent:
        try:
            found = instagram.comments_with_replies(media["id"])
        except instagram.InstagramError as e:
            lines.append(f"IG {media['id']}: could not read comments: {e}")
            continue
        read += len(found)
        for c in found:
            key = f"ig:{c['id']}"
            user = c.get("username", "")
            if key in done or user.lower() == handle or now - _ts(c["timestamp"]) > MAX_AGE:
                continue
            if any(r.get("username", "").lower() == handle for r in c.get("replies", {}).get("data", [])):
                continue  # already answered by us, by Meta Business Suite, or by hand
            kind = classify(c.get("text", ""), words)
            text = reply_text(cfg, kind, c["id"], user) if kind else None
            lines.append(f"IG @{user}: {c.get('text', '')[:60]!r} -> {kind or 'no reply'}{': ' + text if text else ''}")
            if dry:
                continue
            if not kind:
                done[key] = {"at": now.isoformat(), "kind": None}
                continue
            if sent >= MAX_PER_RUN:
                break
            try:
                instagram.public_reply(c["id"], text)
            except instagram.InstagramError as e:
                print(f"IG reply to {c['id']} failed: {e}", file=sys.stderr)
                continue
            done[key] = {"at": now.isoformat(), "kind": kind}
            sent += 1
    counted = sum(m.get("comments_count", 0) for m in recent)
    lines.append(f"Instagram: {read} of {counted} comments readable on {len(recent)} posts, {sent} replies sent.")
    return lines


def _facebook(cfg: dict, words: list[str], done: dict, now: datetime, dry: bool) -> list[str]:
    page = env("FB_PAGE_ID")
    lines, sent = [], 0
    since = f"{now - timedelta(days=7):%Y-%m-%d}"
    videos = [h["facebook_id"] for h in read_state("history", []) if h.get("facebook_id") and h["id"] >= since]
    if dry:
        lines.append(f"Facebook token permissions: {', '.join(facebook.token_permissions()) or 'unknown'}")
    for video in videos:
        try:
            found = facebook.comments(video)
        except facebook.FacebookError as e:
            # Most likely the Page token lacks pages_read_user_content; one line, then stop trying this run.
            lines.append(f"Facebook comments unavailable: {str(e)[:300]}")
            return lines
        for c in found:
            key = f"fb:{c['id']}"
            author = c.get("from") or {}
            if key in done or author.get("id") == page or now - _ts(c["created_time"]) > MAX_AGE:
                continue
            if any((r.get("from") or {}).get("id") == page for r in c.get("comments", {}).get("data", [])):
                continue
            kind = classify(c.get("message", ""), words)
            # Facebook does not let a Page @mention a person by name in plain text, so no {user} here.
            text = reply_text(cfg, kind, c["id"], "") if kind else None
            lines.append(f"FB {author.get('name', '?')}: {c.get('message', '')[:60]!r} -> {kind or 'no reply'}{': ' + text if text else ''}")
            if dry:
                continue
            if not kind:
                done[key] = {"at": now.isoformat(), "kind": None}
                continue
            if sent >= MAX_PER_RUN:
                break
            try:
                facebook.reply_to_comment(c["id"], text)
            except facebook.FacebookError as e:
                lines.append(f"Facebook reply failed (likely missing pages_manage_engagement): {str(e)[:300]}")
                return lines
            done[key] = {"at": now.isoformat(), "kind": kind}
            sent += 1
    lines.append(f"Facebook: {sent} replies sent on {len(videos)} reels.")
    return lines


def _ts(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")
