"""Contact sheets of Pixabay photo candidates for each product in a week file, labelled with
their ids, so the best photo for each reel beat can be picked by eye and pinned as photo_ids.

  python tools/photo_sheet.py weeks/2026-11-07.yaml   -> photo-sheets/<slot>-<asin>.jpg

One row per search: the product's photo_query, then each beat's broll_query. Needs PIXABAY_API_KEY.
With --videos the rows are Pixabay video candidates (a still from each, labelled id and size), for
pinning real footage of people as clip_ids. Tall clips come first; wide ones get centre-cropped."""

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


def search_videos(key: str, query: str) -> list[dict]:
    r = requests.get("https://pixabay.com/api/videos/", params={"key": key, "q": query[:100], "safesearch": "true",
                     "video_type": "film", "per_page": 40}, timeout=60)
    r.raise_for_status()
    hits = [h for h in r.json().get("hits", []) if (h["videos"].get("large") or {}).get("width") or (h["videos"].get("medium") or {}).get("width")]
    for h in hits:
        v = h["videos"].get("large") if (h["videos"].get("large") or {}).get("url") else h["videos"]["medium"]
        thumbs = [(h["videos"].get(s) or {}).get("thumbnail") for s in ("large", "medium", "small", "tiny")]
        h["webformatURL"], h["tall"] = next((t for t in thumbs if t), ""), v["height"] > v["width"]
    hits = [h for h in hits if h["webformatURL"]]
    return sorted(hits, key=lambda h: not h["tall"])[:COLS]


def main(weeks: list[str]) -> None:
    videos = "--videos" in weeks
    weeks = [w for w in weeks if w != "--videos"]
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
                for col, hit in enumerate((search_videos if videos else search)(key, q)):
                    im = Image.open(io.BytesIO(requests.get(hit["webformatURL"], timeout=60).content)).convert("RGB")
                    im.thumbnail((TW - 6, TH - 6))
                    sheet.paste(im, (col * TW + 3, y + 34))
                    draw.rectangle([col * TW + 3, y + 34, col * TW + 120, y + 60], fill="white")
                    draw.text((col * TW + 6, y + 34), str(hit["id"]) + (" T" if hit.get("tall") else ""), font=font, fill="black")
            sheet.save(out / f"{'video-' if videos else ''}{str(item['slot']).replace(' ', '-').replace(':', '')}-{item['asin']}.jpg", quality=80)
            print("Sheet for", item["name"])


def query_sheets(path: str) -> None:
    """--queries file.txt: one search per line, ten rows per sheet, for picking clip_ids across a whole week."""
    key = os.environ["PIXABAY_API_KEY"]
    out = Path("photo-sheets")
    out.mkdir(exist_ok=True)
    font = ImageFont.truetype("assets/fonts/Inter-ExtraBold.otf", 20)
    queries = [q.strip() for q in open(path) if q.strip()]
    rh = 150
    for n in range(0, len(queries), 10):
        chunk = queries[n:n + 10]
        sheet = Image.new("RGB", (TW * COLS, (rh + 30) * len(chunk)), "white")
        draw = ImageDraw.Draw(sheet)
        for row, q in enumerate(chunk):
            y = row * (rh + 30)
            draw.text((6, y + 3), q, font=font, fill=(200, 80, 0))
            for col, hit in enumerate(search_videos(key, q)):
                im = Image.open(io.BytesIO(requests.get(hit["webformatURL"], timeout=60).content)).convert("RGB")
                im.thumbnail((TW - 6, rh - 4))
                sheet.paste(im, (col * TW + 3, y + 28))
                label = str(hit["id"]) + (" T" if hit.get("tall") else "")
                draw.rectangle([col * TW + 3, y + 28, col * TW + 12 + draw.textlength(label, font=font), y + 52], fill="white")
                draw.text((col * TW + 6, y + 28), label, font=font, fill="black")
        sheet.save(out / f"videos-{n // 10 + 1}.jpg", quality=80)


if __name__ == "__main__":
    if sys.argv[1] == "--queries":
        query_sheets(sys.argv[2])
    else:
        main(sys.argv[1:])
