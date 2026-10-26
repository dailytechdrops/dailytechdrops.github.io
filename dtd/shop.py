"""Builds the public shop page (docs/index.html) from the post history, newest first.
The Instagram SHOP auto-reply points here, so every posted product is linked without
anyone editing a link-in-bio page by hand."""

import html
import os
from datetime import datetime
from urllib.parse import quote_plus

import yaml

from .config import ROOT, affiliate_link, channel_link, env, read_state
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


def _track(event: str, name: str) -> str:
    """GoatCounter counts a tap on any link carrying these, named by product, so the weekly report can rank them."""
    return f'data-goatcounter-click="{html.escape(event)}" data-goatcounter-title="{html.escape(name)}"'


def build(cfg: dict, history: list) -> None:
    base = env("MEDIA_BASE_URL") or f"https://raw.githubusercontent.com/{os.environ.get('GITHUB_REPOSITORY', '')}/media"
    handle = cfg["brand"]["handle"]
    cards, top, seen = [], [], set()
    wanted = read_state("shop_top", [])
    for h in reversed([h for h in history if h.get("link")]):
        # A remix posts the same product again with a new hook; list each product once, at its newest post.
        if h.get("asin") in seen:
            continue
        seen.add(h.get("asin"))
        when = datetime.strptime(h["id"][:10], "%Y-%m-%d").strftime("%b %d").replace(" 0", " ")
        reel = f"https://cdn.jsdelivr.net/gh/{os.environ.get('GITHUB_REPOSITORY', '')}@media/{h['id']}/reel.mp4"
        cards.append(
            f'<div class="item"><a class="card" href="{html.escape(channel_link(cfg, h["link"], "shop"))}" rel="sponsored noopener" {_track("amazon-" + h["id"], h["name"])}>'
            f'<img src="{_img_for_card(h["id"], base)}" alt="" loading="lazy">'
            f'<span class="meta"><span class="date">{when}</span>'
            f'<strong>{html.escape(h["name"])}</strong><span class="cta">See it on Amazon</span></span></a>'
            f'<a class="reel" href="{reel}" {_track("reel-" + h["id"], h["name"])}>Watch the reel</a></div>'
        )
        # Taps are counted per post, so a remix's first post still finds its card.
        if any(w in (h["id"], *(x["id"] for x in history if x.get("asin") == h.get("asin"))) for w in wanted):
            top.append(
                f'<a class="pick" href="{html.escape(channel_link(cfg, h["link"], "shop"))}" rel="sponsored noopener" {_track("amazon-" + h["id"], h["name"])}>'
                f'<img src="{_img_for_card(h["id"], base)}" alt="" loading="lazy"><span>{html.escape(h["name"].split(" (")[0])}</span></a>'
            )
    earlier = []
    archive = ROOT / "shop_archive.yaml"
    for e in (yaml.safe_load(archive.read_text()) or []) if archive.exists() else []:
        if e.get("asin"):
            link = channel_link(cfg, affiliate_link(cfg, e["asin"]), "shop")
        else:
            link = f"https://{cfg['amazon']['marketplace']}/s?k={quote_plus(e['search'])}" + (f"&tag={cfg['amazon']['tag']}" if cfg["amazon"]["tag"] else "")
            link = channel_link(cfg, link, "shop")
        pic = IMG_DIR / f"{_slug(e['name'])}.jpg"
        thumb = f'<img src="img/{pic.name}" alt="" loading="lazy">' if pic.exists() else f'<span class="tile">{html.escape(e["name"][0].upper())}</span>'
        earlier.append(
            f'<a class="card" href="{html.escape(link)}" rel="sponsored noopener" {_track("amazon-" + _slug(e["name"]), e["name"])}>{thumb}'
            f'<span class="meta"><strong>{html.escape(e["name"])}</strong>'
            f'<span class="date">{html.escape(e.get("tagline", ""))}</span>'
            f'<span class="cta">See it on Amazon</span></span></a>'
        )
    code = (cfg.get("analytics") or {}).get("goatcounter")
    counter = f'<script data-goatcounter="https://{code}.goatcounter.com/count" async src="https://gc.zgo.at/count.js"></script>' if code else ""
    top_html = ('<h2>Most tapped this week</h2>\n<div class="picks">' + "".join(top[:3]) + "</div>") if top else ""
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
p.sub {{ color:var(--muted); margin:0 0 6px; }}
p.disclose {{ color:var(--muted); font-size:13px; margin:0 0 20px; }}
.card {{ display:flex; gap:14px; align-items:center; background:var(--card); border-radius:16px; padding:12px; margin-bottom:12px; text-decoration:none; color:inherit; box-shadow:0 1px 4px rgba(59,47,39,.08); }}
.card img {{ width:88px; height:110px; object-fit:cover; border-radius:10px; flex:none; }}
.meta {{ display:flex; flex-direction:column; gap:4px; }}
.date {{ color:var(--muted); font-size:13px; }}
.tile {{ width:88px; height:110px; border-radius:10px; flex:none; display:flex; align-items:center; justify-content:center; background:#F6D9BF; color:var(--accent); font:700 34px Poppins, system-ui, sans-serif; }}
.item {{ margin-bottom:12px; }}
.item .card {{ margin-bottom:4px; }}
.reel {{ display:block; text-align:right; padding:0 6px; color:var(--accent); font-size:13px; text-decoration:none; }}
.cta {{ color:var(--accent); font-weight:600; font-size:14px; }}
.picks {{ display:grid; grid-template-columns:repeat(3, 1fr); gap:10px; margin-bottom:8px; }}
.pick {{ background:var(--card); border-radius:14px; padding:8px; text-decoration:none; color:inherit; font-size:13px; line-height:1.3; box-shadow:0 1px 4px rgba(59,47,39,.08); }}
.pick img {{ width:100%; aspect-ratio:4/5; object-fit:cover; border-radius:10px; display:block; margin-bottom:6px; }}
h2 {{ font:600 18px/1.3 Poppins, system-ui, sans-serif; margin:28px 0 12px; }}
footer {{ color:var(--muted); font-size:13px; margin-top:24px; }}
</style></head><body><main>
<h1>Daily Tech Drops</h1>
<p class="sub">Every gadget from @{html.escape(handle)}, newest first.</p>
<p class="disclose">As an Amazon Associate we earn from qualifying purchases. Product links on this page are affiliate links.</p>
{top_html}
{"<h2>Newest first</h2>" if top_html else ""}
{chr(10).join(cards) or "<p>Our first drop is coming soon.</p>"}
{earlier_html}
<footer>As an Amazon Associate we earn from qualifying purchases.</footer>
</main>
{counter}
</body></html>
"""
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "index.html").write_text(page)
