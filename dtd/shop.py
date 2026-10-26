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
# Posts whose own slide is only text can get a photo on the shop page instead (post id: stock search).
# Only for a photo that truly shows the product; a look-alike stock photo costs trust.
PHOTO_OVERRIDES: dict[str, str] = {}


def _slug(text: str) -> str:
    return "".join(c.lower() if c.isalnum() else "-" for c in text).strip("-")[:60]


def fetch_images() -> int:
    """Saves one small photo per earlier pick with a `photo` search (and per override) into docs/img, so the page serves its own copies."""
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
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    base = env("MEDIA_BASE_URL") or f"https://raw.githubusercontent.com/{repo}/media"
    owner, _, name = repo.partition("/")
    site = f"https://{owner}.github.io/{name}/" if owner else ""
    handle = cfg["brand"]["handle"]
    cards, top, seen = [], [], set()
    wanted = read_state("shop_top", [])
    for h in reversed([h for h in history if h.get("link")]):
        # A remix posts the same product again with a new hook; list each product once, at its newest post.
        if h.get("asin") in seen:
            continue
        seen.add(h.get("asin"))
        when = datetime.strptime(h["id"][:10], "%Y-%m-%d").strftime("%b %d").replace(" 0", " ")
        reel = f"https://cdn.jsdelivr.net/gh/{repo}@media/{h['id']}/reel.mp4"
        cards.append(
            f'<div class="item"><a class="card" href="{html.escape(channel_link(cfg, h["link"], "shop"))}" rel="sponsored noopener" {_track("amazon-" + h["id"], h["name"])}>'
            f'<img src="{_img_for_card(h["id"], base)}" alt="" loading="lazy">'
            f'<span class="meta"><span class="date">{when}</span>'
            f'<strong>{html.escape(h["name"])}</strong><span class="cta">See it on Amazon</span></span></a>'
            f'<a class="reel" href="{reel}" {_track("reel-" + h["id"], h["name"])}>&#9654;&#xFE0E; Watch the reel</a></div>'
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
        # A thumbnail only when it is a real photo of this product; a look-alike stock photo costs trust.
        pic = IMG_DIR / f"{_slug(e['name'])}.jpg"
        thumb = f'<img src="img/{pic.name}" alt="" loading="lazy">' if pic.exists() else ""
        earlier.append(
            f'<a class="row" href="{html.escape(link)}" rel="sponsored noopener" {_track("amazon-" + _slug(e["name"]), e["name"])}>{thumb}'
            f'<span class="meta"><strong>{html.escape(e["name"])}</strong>'
            f'<span class="date">{html.escape(e.get("tagline", ""))}</span></span>'
            f'<span class="go">Amazon &rsaquo;</span></a>'
        )
    code = (cfg.get("analytics") or {}).get("goatcounter")
    counter = f'<script data-goatcounter="https://{code}.goatcounter.com/count" async src="https://gc.zgo.at/count.js"></script>' if code else ""
    top_html = ('<h2>Most tapped this week</h2>\n<div class="picks">' + "".join(top[:3]) + "</div>") if top else ""
    earlier_html = ('<h2>More picks</h2>\n<div class="list">\n' + "\n".join(earlier) + "\n</div>") if earlier else ""
    og = (f'<meta property="og:image" content="{site}img/logo.png">\n<meta property="og:url" content="{site}">\n') if site else ""
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Daily Tech Drops: cool tech finds on Amazon</title>
<meta name="description" content="Every gadget from @{html.escape(handle)}, newest first. Cool tech finds on Amazon, new every day.">
<meta property="og:title" content="Daily Tech Drops">
<meta property="og:description" content="Cool tech finds on Amazon, new every day.">
{og}<link rel="icon" href="img/logo.png">
<link rel="apple-touch-icon" href="img/logo.png">
<meta name="theme-color" content="#FBF6EE">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;800&display=swap" rel="stylesheet">
<style>
:root {{ --bg:#FBF6EE; --ink:#3B2F27; --muted:#7A6A5D; --accent:#E8792B; --accent-soft:#FBE7D6; --card:#fff; --line:#F1E8DC; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:16px/1.5 Inter, system-ui, sans-serif; -webkit-font-smoothing:antialiased; }}
main {{ max-width:520px; margin:0 auto; padding:28px 16px 48px; }}
header {{ display:flex; gap:14px; align-items:center; margin-bottom:14px; }}
header img {{ width:60px; height:60px; border-radius:16px; box-shadow:0 2px 10px rgba(59,47,39,.10); flex:none; }}
h1 {{ font:800 26px/1.15 Inter, system-ui, sans-serif; letter-spacing:-.02em; margin:0; }}
p.sub {{ color:var(--muted); margin:2px 0 0; font-size:15px; }}
p.disclose {{ color:var(--muted); font-size:12.5px; line-height:1.45; margin:0 0 22px; padding:10px 12px; background:var(--accent-soft); border-radius:12px; }}
h2 {{ font:600 13px/1.3 Inter, system-ui, sans-serif; text-transform:uppercase; letter-spacing:.08em; color:var(--muted); margin:30px 0 12px; }}
.item {{ background:var(--card); border-radius:18px; margin-bottom:14px; box-shadow:0 1px 2px rgba(59,47,39,.05), 0 6px 18px rgba(59,47,39,.06); overflow:hidden; }}
.card {{ display:flex; gap:14px; align-items:center; padding:12px; text-decoration:none; color:inherit; }}
.card img {{ width:96px; height:120px; object-fit:cover; border-radius:12px; flex:none; background:var(--line); }}
.meta {{ display:flex; flex-direction:column; gap:4px; min-width:0; }}
.meta strong {{ font-weight:600; font-size:16px; line-height:1.3; }}
.date {{ color:var(--muted); font-size:13px; }}
.cta {{ align-self:flex-start; margin-top:6px; background:var(--accent); color:#fff; font-weight:600; font-size:14px; padding:7px 14px; border-radius:999px; }}
.reel {{ display:block; padding:10px 14px; border-top:1px solid var(--line); color:var(--accent); font-size:14px; font-weight:500; text-decoration:none; }}
.list {{ background:var(--card); border-radius:18px; box-shadow:0 1px 2px rgba(59,47,39,.05), 0 6px 18px rgba(59,47,39,.06); overflow:hidden; }}
.row {{ display:flex; gap:12px; align-items:center; padding:13px 14px; text-decoration:none; color:inherit; border-top:1px solid var(--line); }}
.row:first-child {{ border-top:0; }}
.row img {{ width:52px; height:52px; object-fit:cover; border-radius:10px; flex:none; }}
.row .meta {{ flex:1; gap:1px; }}
.row strong {{ font-size:15px; }}
.picks {{ display:grid; grid-template-columns:repeat(3, 1fr); gap:10px; margin-bottom:8px; }}
.pick {{ background:var(--card); border-radius:14px; padding:8px; text-decoration:none; color:inherit; font-size:13px; font-weight:500; line-height:1.3; box-shadow:0 1px 2px rgba(59,47,39,.05), 0 6px 18px rgba(59,47,39,.06); }}
.pick img {{ width:100%; aspect-ratio:4/5; object-fit:cover; border-radius:10px; display:block; margin-bottom:6px; }}
.go {{ color:var(--accent); font-weight:600; font-size:13px; white-space:nowrap; }}
footer {{ color:var(--muted); font-size:12.5px; margin-top:28px; text-align:center; line-height:1.6; }}
footer a {{ color:var(--muted); }}
</style></head><body><main>
<header><img src="img/logo.png" alt="Daily Tech Drops logo"><div><h1>Daily Tech Drops</h1><p class="sub">Cool tech finds, new every day.</p></div></header>
<p class="disclose">As an Amazon Associate we earn from qualifying purchases. Product links on this page are affiliate links.</p>
{top_html}
<h2>Latest drops</h2>
{chr(10).join(cards) or "<p>Our first drop is coming soon.</p>"}
{earlier_html}
<footer>Every gadget from @{html.escape(handle)}, newest first.<br>Prices change often, so check Amazon for today's price.<br>As an Amazon Associate we earn from qualifying purchases.<br><a href="https://www.youtube.com/@daily_tech_drops">Watch us on YouTube</a> · <a href="privacy.html">Privacy Policy</a> · <a href="terms.html">Terms of Service</a></footer>
</main>
{counter}
</body></html>
"""
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "index.html").write_text(page)
