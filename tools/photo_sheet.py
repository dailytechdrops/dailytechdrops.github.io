"""Temporary: contact sheets of Pixabay photo candidates for each product, to pin the best ones."""
import io, os, sys, yaml, requests
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

KEY = os.environ["PIXABAY_API_KEY"]
out = Path("tmp-sheets"); out.mkdir(exist_ok=True)
font = ImageFont.truetype("assets/fonts/Inter-ExtraBold.otf", 22)
TW, TH, COLS = 200, 356, 8

def search(q):
    r = requests.get("https://pixabay.com/api/", params={"key": KEY, "q": q[:100], "image_type": "photo", "orientation": "vertical",
                     "safesearch": "true", "min_height": 1200, "per_page": 30}, timeout=60)
    r.raise_for_status()
    return r.json().get("hits", [])[:COLS]

for f in sys.argv[1:]:
    for it in yaml.safe_load(open(f)):
        c = it.get("content") or {}
        if str(it["slot"]) < "2026-10-26":
            continue
        queries = [c.get("photo_query")] + [b["broll_query"] for b in c.get("beats", [])] + it.get("extra_queries", [])
        queries = [q for i, q in enumerate(queries) if q and q not in queries[:i]]
        sheet = Image.new("RGB", (TW * COLS, (TH + 36) * len(queries)), "white")
        d = ImageDraw.Draw(sheet)
        for r, q in enumerate(queries):
            y = r * (TH + 36)
            d.text((6, y + 4), q, font=font, fill=(200, 80, 0))
            for col, h in enumerate(search(q)):
                im = Image.open(io.BytesIO(requests.get(h["webformatURL"], timeout=60).content)).convert("RGB")
                im.thumbnail((TW - 6, TH - 6))
                sheet.paste(im, (col * TW + 3, y + 34))
                d.rectangle([col * TW + 3, y + 34, col * TW + 120, y + 60], fill="white")
                d.text((col * TW + 6, y + 34), str(h["id"]), font=font, fill="black")
        sheet.save(out / f"{it['slot'].replace(' ', '-').replace(':', '')}-{it['asin']}.jpg", quality=80)
        print("sheet", it["name"])
