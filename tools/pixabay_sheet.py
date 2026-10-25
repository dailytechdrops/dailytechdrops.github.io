"""One-off: contact sheets of Pixabay vertical photos for a few queries."""
import io, os, sys, json
from pathlib import Path
import requests
from PIL import Image, ImageDraw

out = Path("sheets"); out.mkdir(exist_ok=True)
meta = {}
for q in sys.argv[1:]:
    hits = requests.get("https://pixabay.com/api/", params={"key": os.environ["PIXABAY_API_KEY"], "q": q, "image_type": "photo",
                        "orientation": "vertical", "safesearch": "true", "min_height": 1200, "per_page": 24}, timeout=60).json().get("hits", [])
    sheet = Image.new("RGB", (6 * 180, 4 * 260), "white")
    for i, h in enumerate(hits[:24]):
        try:
            im = Image.open(io.BytesIO(requests.get(h.get("largeImageURL") or h["webformatURL"], timeout=60).content)).convert("RGB")
        except Exception:
            continue
        im.thumbnail((180, 240))
        sheet.paste(im, ((i % 6) * 180, (i // 6) * 260))
        ImageDraw.Draw(sheet).text(((i % 6) * 180 + 4, (i // 6) * 260 + 244), f"{i} id{h['id']}", fill="red")
    name = q.replace(" ", "_")
    sheet.save(out / f"{name}.jpg", quality=80)
    meta[q] = [{"i": i, "id": h["id"], "tags": h["tags"], "url": h["largeImageURL"]} for i, h in enumerate(hits[:24])]
(out / "meta.json").write_text(json.dumps(meta, indent=1))
