"""Builds the public shop page (docs/index.html) from the post history, newest first.
The Instagram SHOP auto-reply points here, so every posted product is linked without
anyone editing a link-in-bio page by hand."""

import html
import os
from datetime import datetime
from urllib.parse import quote_plus

import yaml

from .config import ROOT, affiliate_link, env


def build(cfg: dict, history: list) -> None:
    base = env("MEDIA_BASE_URL") or f"https://raw.githubusercontent.com/{os.environ.get('GITHUB_REPOSITORY', '')}/media"
    handle = cfg["brand"]["handle"]
    cards = []
    for h in reversed([h for h in history if h.get("link")]):
        when = datetime.strptime(h["id"][:10], "%Y-%m-%d").strftime("%b %d").replace(" 0", " ")
        cards.append(
            f'<a class="card" href="{html.escape(h["link"])}" rel="sponsored noopener">'
            f'<img src="{base}/{h["id"]}/slide_1.jpg" alt="" loading="lazy">'
            f'<span class="meta"><span class="date">{when}</span>'
            f'<strong>{html.escape(h["name"])}</strong><span class="cta">See it on Amazon</span></span></a>'
        )
    earlier = []
    archive = ROOT / "shop_archive.yaml"
    for e in (yaml.safe_load(archive.read_text()) or []) if archive.exists() else []:
        if e.get("asin"):
            link = affiliate_link(cfg, e["asin"])
        else:
            link = f"https://{cfg['amazon']['marketplace']}/s?k={quote_plus(e['search'])}" + (f"&tag={cfg['amazon']['tag']}" if cfg["amazon"]["tag"] else "")
        earlier.append(
            f'<a class="card" href="{html.escape(link)}" rel="sponsored noopener">'
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
