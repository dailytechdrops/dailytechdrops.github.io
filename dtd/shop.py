"""Builds the public shop page (docs/index.html) from the post history, newest first.
The Instagram SHOP auto-reply points here, so every posted product is linked without
anyone editing a link-in-bio page by hand."""

import html
import os
from datetime import datetime
from urllib.parse import quote_plus

import yaml

from .config import ROOT, affiliate_link, env
from .media_sources import stock_photo

IMG_DIR = ROOT / "docs" / "img"
# Posts whose own slide is only text get a stock photo on the shop page instead.
PHOTO_OVERRIDES = {"2026-10-20-1730-B002L6BZXC": "hotel room door"}


def _slug(text: str) -> str:
    return "".join(c.lower() if c.isalnum() else "-" for c in text).strip("-")[:60]


def fetch_images() -> int:
    """Saves one small stock photo per earlier pick (and per override) into docs/img, so the page serves its own copies."""
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    archive = ROOT / "shop_archive.yaml"
    wanted = {_slug(e["name"]): e.get("photo") for e in (yaml.safe_load(archive.read_text()) or [])}
    wanted.update({k: v for k, v in PHOTO_OVERRIDES.items()})
    from PIL import Image
    for slug, query in wanted.items():
        target = IMG_DIR / f"{slug}.jpg"
        if not query or target.exists():
            continue
        raw = IMG_DIR / f"{slug}.src.jpg"
        if stock_photo(query, raw):
            Image.open(raw).convert("RGB").resize((264, 330)).save(target, quality=82)
            raw.unlink()
            print(f"Saved {target.name} for '{query}'")
    return 0


def _img_for_card(item_id: str, base: str) -> str:
    return f"img/{item_id}.jpg" if (IMG_DIR / f"{item_id}.jpg").exists() else f"{base}/{item_id}/slide_1.jpg"


def build(cfg: dict, history: list) -> None:
    base = env("MEDIA_BASE_URL") or f"https://raw.githubusercontent.com/{os.environ.get('GITHUB_REPOSITORY', '')}/media"
    handle = cfg["brand"]["handle"]
    cards = []
    for h in reversed([h for h in history if h.get("link")]):
        when = datetime.strptime(h["id"][:10], "%Y-%m-%d").strftime("%b %d").replace(" 0", " ")
        reel = f"https://cdn.jsdelivr.net/gh/{os.environ.get('GITHUB_REPOSITORY', '')}@media/{h['id']}/reel.mp4"
        cards.append(
            f'<div class="item"><a class="card" href="{html.escape(h["link"])}" rel="sponsored noopener">'
            f'<img src="{_img_for_card(h["id"], base)}" alt="" loading="lazy">'
            f'<span class="meta"><span class="date">{when}</span>'
            f'<strong>{html.escape(h["name"])}</strong><span class="cta">See it on Amazon</span></span></a>'
            f'<a class="reel" href="{reel}">Watch the reel</a></div>'
        )
    earlier = []
    archive = ROOT / "shop_archive.yaml"
    for e in (yaml.safe_load(archive.read_text()) or []) if archive.exists() else []:
        if e.get("asin"):
            link = affiliate_link(cfg, e["asin"])
        else:
            link = f"https://{cfg['amazon']['marketplace']}/s?k={quote_plus(e['search'])}" + (f"&tag={cfg['amazon']['tag']}" if cfg["amazon"]["tag"] else "")
        pic = IMG_DIR / f"{_slug(e['name'])}.jpg"
        thumb = f'<img src="img/{pic.name}" alt="" loading="lazy">' if pic.exists() else ""
        earlier.append(
            f'<a class="card" href="{html.escape(link)}" rel="sponsored noopener">{thumb}'
            f'<span class="meta"><strong>{html.escape(e["name"])}</strong>'
            f'<span class="date">{html.escape(e.get("tagline", ""))}</span>'
            f'<span class="cta">See it on Amazon</span></span></a>'
        )
    earlier_html = ("<h2>Earlier picks</h2>\n" + "\n".join(earlier)) if earlier else ""
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Daily Tech Drops: every gadget we have posted</title>
<style>
:root {{ --bg:#FBF6EE; --ink:#3B2F27; --muted:#7A6A5D; --accent:#E8792B; --card:#fff; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:16px/1.5 Inter, system-ui, sans-serif; }}
main {{ max-width:520px; margin:0 auto; padding:24px 16px 48px; }}
h1 {{ font:700 28px/1.2 Poppins, system-ui, sans-serif; margin:0 0 4px; }}
p.sub {{ color:var(--muted); margin:0 0 20px; }}
.card {{ display:flex; gap:14px; align-items:center; background:var(--card); border-radius:16px; padding:12px; margin-bottom:12px; text-decoration:none; color:inherit; box-shadow:0 1px 4px rgba(59,47,39,.08); }}
.card img {{ width:88px; height:110px; object-fit:cover; border-radius:10px; flex:none; }}
.meta {{ display:flex; flex-direction:column; gap:4px; }}
.date {{ color:var(--muted); font-size:13px; }}
.item {{ margin-bottom:12px; }}
.item .card {{ margin-bottom:4px; }}
.reel {{ display:block; text-align:right; padding:0 6px; color:var(--accent); font-size:13px; text-decoration:none; }}
.cta {{ color:var(--accent); font-weight:600; font-size:14px; }}
h2 {{ font:600 18px/1.3 Poppins, system-ui, sans-serif; margin:28px 0 12px; }}
footer {{ color:var(--muted); font-size:13px; margin-top:24px; }}
</style></head><body><main>
<h1>Daily Tech Drops</h1>
<p class="sub">Every gadget from @{html.escape(handle)}, newest first.</p>
{chr(10).join(cards) or "<p>Our first drop is coming soon.</p>"}
{earlier_html}
<footer>As an Amazon Associate we earn from qualifying purchases.</footer>
</main></body></html>
"""
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "index.html").write_text(page)
