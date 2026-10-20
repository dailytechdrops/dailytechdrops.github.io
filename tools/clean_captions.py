"""Builds compliant captions for the posts made before the current pipeline.

Reads an audit report (tools/audit.py output) and writes audit/caption_fixes.json:
no prices, discounts or review counts (Amazon Associates rules), the standard Amazon
disclosure as the first line, the shop link on Facebook, and tidy hashtags.
"""

import json
import re
import sys

SHOP = "https://kevingalus.github.io/daily-tech-drops/"
DISCLOSURE = "#ad As an Amazon Associate I earn from qualifying purchases."

# Lines or phrases that state a price, a discount or Amazon review data, rewritten by hand.
PHRASES = {
    "Your TV looks $500 fancier for $9. ✨": "Your TV just got a cinema upgrade. ✨",
    " Peace of mind for sixty bucks.": "",
    "Your room is boring. Fix it for $59.99 💡": "Your room is boring. Fix it. 💡",
    "Your phone screen is disgusting. Fix it for $9 📱": "Your phone screen is disgusting. Fix it. 📱",
    "Stop paying $249 for these 🎧": "Apple's best earbuds, and they translate for you 🎧",
    "14,563 reviews. Amazon's Choice. 10,000+ bought last month.\n\n": "",
    "This is nearly the lowest price they’ve ever been. ": "",
    "This is nearly the lowest price they've ever been. ": "",
    "Save this — your future self will thank you when the price jumps back up 💾": "Save this for your next upgrade 💾",
    "How we pick every deal ✅ Real discounts, highly rated, actually useful.": "How we pick every find ✅ Highly rated, genuinely useful, and fun to own.",
    "Testing tomorrow's picks. New drops daily at 10am & 2pm!": "Lining up tomorrow's picks. New drops daily at 11:30am and 7pm ET!",
    "All live on the site: ": "All on the site: ",
    "USB TV Backlight Kit $9.99 — a $10 movie-night upgrade": "USB TV Backlight Kit, an easy movie-night upgrade",
    "Govee Floor Lamp 💡 $59.99 —": "Govee Floor Lamp 💡",
    "eufy SoloCam S220 📷 $56.99 (43% off) —": "eufy SoloCam S220 📷",
}
AIRPODS = re.compile(r"AirPods Pro 3 just dropped to \$199 ?— that[’']s \$50 off Apple[’']s best earbuds\. You get")
PRICE_LINE = re.compile(r"^(💰 )?\$[\d.,]+[^—\n]*— (link in bio 👆|https?://\S+)$", re.M)
OLD_DISCLOSURE = re.compile(r"^#?ad\b.*(affiliate|commission).*$", re.M | re.I)
COMMENT_LINE = re.compile(r"^💬 C[0o]mment SHOP and I.{1,3}ll DM you the link!$|^💬 C[0o]mment SHOP and I will DM you the link!$", re.M)


def clean(text: str, facebook: bool) -> str:
    t = text
    for old, new in PHRASES.items():
        t = t.replace(old, new)
    t = AIRPODS.sub("AirPods Pro 3 give you", t)
    t = PRICE_LINE.sub(f"Shop it: {SHOP}" if facebook else "Link in bio 👆", t)
    if facebook:
        t = t.replace("Link in bio 👆", f"Shop it: {SHOP}")
        t = COMMENT_LINE.sub("", t)
    else:
        t = t.replace("C0mment", "Comment")
    had_disclosure = bool(OLD_DISCLOSURE.search(t)) or DISCLOSURE in t
    had_disclosure |= bool(re.search(r" #ad$", t))
    t = re.sub(r" #ad$", "", OLD_DISCLOSURE.sub("", t).replace(DISCLOSURE, ""))
    # Hashtag lines: give bare words their missing #.
    t = "\n".join(re.sub(r"(?<=\s)(?!#)(\w+)", r"#\1", l) if l.startswith("#") else l for l in t.split("\n"))
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    if had_disclosure or SHOP in t or "link in bio" in t.lower() or "amazon" in t.lower():
        t = f"{DISCLOSURE}\n\n{t}"
    return t


def main(report_path: str, out_path: str) -> None:
    r = json.load(open(report_path))
    fixes = []
    for m in r.get("ig_media", []):
        old = m.get("caption") or ""
        new = clean(old, facebook=False)
        if new != old:
            fixes.append({"platform": "instagram", "id": m["id"], "permalink": m.get("permalink"), "old": old, "new": new})
    for v in r.get("fb_videos", []):
        old = v.get("description") or ""
        new = clean(old, facebook=True)
        if new != old and old:
            fixes.append({"platform": "facebook_video", "id": v["id"], "old": old, "new": new})
    for p in r.get("fb_posts", []):
        old = p.get("message") or ""
        if p.get("status_type") == "added_video" or not old:
            continue
        new = clean(old, facebook=True)
        if new != old:
            fixes.append({"platform": "facebook_post", "id": p["id"].split("_")[-1], "old": old, "new": new})
    json.dump(fixes, open(out_path, "w"), indent=1, ensure_ascii=False)
    print(f"{len(fixes)} captions to fix")


if __name__ == "__main__":
    main(*sys.argv[1:3])
