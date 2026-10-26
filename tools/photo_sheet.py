"""Contact sheets of Pixabay photo candidates for each product in a week file, labelled with
their ids, so the best photo for each reel beat can be picked by eye and pinned as photo_ids.

  python tools/photo_sheet.py weeks/2026-11-07.yaml   -> photo-sheets/<slot>-<asin>.jpg

One row per search: the product's photo_query, then each beat's broll_query. Needs PIXABAY_API_KEY."""

import io
import os
import sys
from pathlib import Path

import requests
import yaml
from PIL import Image, ImageDraw, ImageFont

TW, TH, COLS = 200, 356, 8


def search(key: str, query: str) -> list[dict]:
    r = requests.get("https://pixabay.com/api/", params={"key": key, "q": query[:100], "image_type": "photo", "orientation": "vertical",
                     "safesearch": "true", "min_height": 1200, "per_page": 30}, timeout=60)
    r.raise_for_status()
    return r.json().get("hits", [])[:COLS]


def main(weeks: list[str]) -> None:
    key = os.environ["PIXABAY_API_KEY"]
    out = Path("photo-sheets")
    out.mkdir(exist_ok=True)
    font = ImageFont.truetype("assets/fonts/Inter-ExtraBold.otf", 22)
    for f in weeks:
        for item in yaml.safe_load(open(f)):
            c = item.get("content") or {}
            queries = [c.get("photo_query")] + [b["broll_query"] for b in c.get("beats", [])]
            queries = [q for i, q in enumerate(queries) if q and q not in queries[:i] and not q.startswith("assets/")]
            if not queries:
                continue
            sheet = Image.new("RGB", (TW * COLS, (TH + 36) * len(queries)), "white")
            draw = ImageDraw.Draw(sheet)
            for row, q in enumerate(queries):
                y = row * (TH + 36)
                draw.text((6, y + 4), q, font=font, fill=(200, 80, 0))
                for col, hit in enumerate(search(key, q)):
                    im = Image.open(io.BytesIO(requests.get(hit["webformatURL"], timeout=60).content)).convert("RGB")
                    im.thumbnail((TW - 6, TH - 6))
                    sheet.paste(im, (col * TW + 3, y + 34))
                    draw.rectangle([col * TW + 3, y + 34, col * TW + 120, y + 60], fill="white")
                    draw.text((col * TW + 6, y + 34), str(hit["id"]), font=font, fill="black")
            sheet.save(out / f"{str(item['slot']).replace(' ', '-').replace(':', '')}-{item['asin']}.jpg", quality=80)
            print("Sheet for", item["name"])


if __name__ == "__main__":
    main(sys.argv[1:])
