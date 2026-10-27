"""Draws one tall Pinterest pin (1000x1500) per gift guide into docs/gifts/<slug>.jpg: the guide title on a
cream card over a grid of four product photos (the same hand-picked photos as each product's reel), with the logo.
The guide page uses it as its og:image, so a pin saved from the page shows this artwork."""

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageOps

from .config import ROOT, load_all_weeks, load_config
from .media_sources import stock_photo
from .reel import _card, _font, _logo, _rgba, _wrap
from .shop import load_guides

W, H = 1000, 1500


def _photos(guide: dict, scratch: Path) -> list[tuple[Path, bool]]:
    """The first photo of up to four of the guide's products, in guide order, each flagged True when it is
    one of our own product cutouts (assets/photos), which is shown whole instead of cropped."""
    first = {}
    for item in load_all_weeks():
        c = item.get("content") or {}
        if item["asin"] not in first and (c.get("photo_ids") or c.get("photo_query")):
            first[item["asin"]] = c
    shots, used = [], set()
    for asin in guide["asins"]:
        c = first.get(asin)
        # Sister products often share their first photo; show each photo once.
        key = (c.get("photo_ids") or [c.get("photo_query")])[0] if c else None
        if not c or key in used:
            continue
        used.add(key)
        shot = stock_photo(c.get("photo_query"), scratch / f"{guide['slug']}-{asin}.jpg", 0, c.get("photo_ids"))
        if shot:
            shots.append((shot, not c.get("photo_ids") and str(c.get("photo_query", "")).startswith("assets/photos/")))
        if len(shots) == 4:
            break
    return shots


def render_pin(cfg: dict, guide: dict, photos: list[tuple[Path, bool]], out: Path) -> None:
    rc = cfg["reel"]
    bg, ink, muted, accent = (_rgba(rc[k], 255) for k in ("background_color", "ink_color", "muted_color", "accent_color"))
    img = Image.new("RGBA", (W, H), bg)
    # Photo grid: 2x2 tiles, or one wide photo per row when there are fewer.
    gap, top, bottom = 18, 500, H - 150
    tiles = photos[:4]
    if tiles:
        cols = 2 if len(tiles) >= 2 else 1
        rows = (len(tiles) + cols - 1) // cols
        tw, th = (W - 2 * 50 - (cols - 1) * gap) // cols, (bottom - top - (rows - 1) * gap) // rows
        for i, (p, cutout) in enumerate(tiles):
            x, y = 50 + (i % cols) * (tw + gap), top + (i // cols) * (th + gap)
            src = Image.open(p).convert("RGBA")
            if cutout:
                flat = Image.new("RGBA", src.size, (255, 255, 255, 255))
                flat.alpha_composite(src)
                flat = flat.convert("RGB")
                # Trim the plain background around the product so it fills the tile.
                edge = Image.new("RGB", flat.size, flat.getpixel((0, 0)))
                box = ImageChops.difference(flat, edge).convert("L").point(lambda v: 255 if v > 24 else 0).getbbox()
                flat = flat.crop(box) if box else flat
                ph = ImageOps.pad(flat, (int(tw * 0.86), int(th * 0.86)), Image.LANCZOS, color=(255, 255, 255))
                ph = ImageOps.pad(ph, (tw, th), color=(255, 255, 255)).convert("RGBA")
            else:
                ph = ImageOps.fit(src.convert("RGB"), (tw, th), Image.LANCZOS).convert("RGBA")
            mask = Image.new("L", (tw, th), 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, tw, th], radius=28, fill=255)
            _card(img, [x, y, x + tw, y + th], radius=28, fill=(255, 255, 255, 255), shadow=50)
            img.paste(ph, (x, y), mask)
    draw = ImageDraw.Draw(img)
    # Orange tag, then the title in the brand's warm brown.
    tag_font = _font(rc["font"], 30)
    tag = "HOLIDAY GIFT GUIDE"
    tl = draw.textlength(tag, font=tag_font)
    draw.rounded_rectangle([(W - tl) / 2 - 26, 90, (W + tl) / 2 + 26, 146], radius=28, fill=accent)
    draw.text(((W - tl) / 2, 100), tag, font=tag_font, fill=(255, 255, 255, 255))
    size = 84
    title_font = _font(rc["font"], size)
    lines = _wrap(draw, guide["title"], title_font, W - 140)
    while len(lines) > 3 and size > 56:
        size -= 6
        title_font = _font(rc["font"], size)
        lines = _wrap(draw, guide["title"], title_font, W - 140)
    y = 180 if len(lines) > 2 else 205
    for line in lines:
        draw.text(((W - draw.textlength(line, font=title_font)) / 2, y), line, font=title_font, fill=ink)
        y += int(size * 1.12)
    sub_font = _font(rc["body_font"], 34)
    sub = "Tech gifts they will actually use"
    draw.text(((W - draw.textlength(sub, font=sub_font)) / 2, min(y + 14, top - 60)), sub, font=sub_font, fill=muted)
    # Footer: logo and shop name.
    logo = 64
    foot_font = _font(rc["body_font"], 32)
    foot = "Daily Tech Drops  ·  shop the full guide"
    fw = logo + 16 + draw.textlength(foot, font=foot_font)
    x0 = (W - fw) / 2
    img.alpha_composite(_logo(logo), (int(x0), H - 112))
    draw.text((x0 + logo + 16, H - 100), foot, font=foot_font, fill=ink)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out, quality=88)


def render_all() -> int:
    cfg = load_config()
    scratch = ROOT / "output" / "pins"
    scratch.mkdir(parents=True, exist_ok=True)
    for guide in load_guides():
        out = ROOT / "docs" / "gifts" / f"{guide['slug']}.jpg"
        photos = _photos(guide, scratch)
        if not photos:
            print(f"No photos for {guide['slug']} (needs PIXABAY_API_KEY); skipped")
            continue
        render_pin(cfg, guide, photos, out)
        print(f"Saved {out.relative_to(ROOT)}")
    return 0
