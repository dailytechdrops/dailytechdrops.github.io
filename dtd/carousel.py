"""Renders the photo carousel as 1080x1350 (4:5) slides."""

from pathlib import Path

from PIL import Image, ImageDraw

from .media_sources import stock_photo
from .reel import _font, _rgba, _wrap
from .writer import DropContent

W, H = 1080, 1350


def render_carousel(cfg: dict, content: DropContent, workdir: Path) -> list[Path]:
    workdir.mkdir(parents=True, exist_ok=True)
    rc = cfg["reel"]
    accent = _rgba(rc["accent_color"], 255)
    bg = _rgba(rc.get("background_color", "#FBF6EE"), 255)[:3]
    ink = _rgba(rc.get("ink_color", "#3B2F27"), 255)[:3]
    muted = _rgba(rc.get("muted_color", "#7A6A5D"), 255)[:3]
    total = len(content.carousel)
    paths = []
    photo = stock_photo(content.photo_query, workdir / "photo.jpg") if content.photo_query else None

    for i, slide in enumerate(content.carousel):
        first, last = i == 0, i == total - 1
        if photo:
            shot = stock_photo(content.photo_query, workdir / f"photo_{i}.jpg", i) or photo
            path = workdir / f"slide_{i + 1}.jpg"
            _photo_slide(rc, cfg["brand"]["handle"], slide, shot, i, total, path)
            paths.append(path)
            continue
        img = Image.new("RGB", (W, H), bg)
        draw = ImageDraw.Draw(img)
        # Accent bar and footer give every slide the same frame.
        draw.rectangle([0, 0, W, 18], fill=accent)
        small = _font(rc["body_font"], 34)
        draw.text((80, H - 110), "@" + cfg["brand"]["handle"], font=small, fill=muted)
        counter = f"{i + 1}/{total}"
        draw.text((W - 80 - draw.textlength(counter, font=small), H - 110), counter, font=small, fill=muted)

        shot = first and photo is not None
        title_font = _font(rc["font"], 80 if shot else 104 if first else 86)
        title_lines = _wrap(draw, slide.title.upper() if (first or last) else slide.title, title_font, W - 160)
        y = 580 if shot else 300 if first else 260
        if shot:
            pic = Image.open(photo).convert("RGB")
            bw, bh = W - 160, 470
            scale = max(bw / pic.width, bh / pic.height)
            pic = pic.resize((int(pic.width * scale), int(pic.height * scale)))
            left, top = (pic.width - bw) // 2, (pic.height - bh) // 2
            mask = Image.new("L", (bw, bh), 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, bw, bh], radius=36, fill=255)
            img.paste(pic.crop((left, top, left + bw, top + bh)), (80, 60), mask)
            tiny = _font(rc["body_font"], 26)
            draw.text((W - 80 - draw.textlength("Stock photo", font=tiny) - 14, 60 + bh - 40), "Stock photo", font=tiny, fill=(255, 255, 255))
        if last:
            box_h = len(title_lines) * 112 + 60
            draw.rounded_rectangle([60, y - 40, W - 60, y - 40 + box_h], radius=36, fill=accent)
        for line in title_lines:
            draw.text((80, y), line, font=title_font, fill=(255, 255, 255) if last else ink)
            y += int(title_font.size * 1.15)

        if not last:
            draw.rectangle([80, y + 30, 230, y + 40], fill=accent)
        body_font = _font(rc["body_font"], 50)
        y += 90
        for line in _wrap(draw, slide.body, body_font, W - 160):
            draw.text((80, y), line, font=body_font, fill=muted if last else ink)
            y += 68

        if first:
            hint = "Swipe"
            draw.text((W - 80 - draw.textlength(hint, font=small) - 50, H - 220), hint, font=small, fill=accent)
            draw.polygon([(W - 110, H - 214), (W - 80, H - 197), (W - 110, H - 180)], fill=accent)

        path = workdir / f"slide_{i + 1}.jpg"
        img.save(path, quality=92)
        paths.append(path)
    return paths


def _photo_slide(rc: dict, handle: str, slide, photo: Path, i: int, total: int, out: Path) -> None:
    """Full-bleed stock photo with the headline on a light card, so slides read as photos, not text."""
    accent = _rgba(rc["accent_color"], 255)
    ink = _rgba(rc.get("ink_color", "#3B2F27"), 255)[:3]
    muted = _rgba(rc.get("muted_color", "#7A6A5D"), 255)[:3]
    first, last = i == 0, i == total - 1
    pic = Image.open(photo).convert("RGB")
    scale = max(W / pic.width, H / pic.height)
    pic = pic.resize((int(pic.width * scale) + 1, int(pic.height * scale) + 1))
    left, top = (pic.width - W) // 2, (pic.height - H) // 2
    img = pic.crop((left, top, left + W, top + H)).convert("RGBA")
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    title_font = _font(rc["font"], 78 if first else 68)
    body_font = _font(rc["body_font"], 42)
    title_lines = _wrap(d, slide.title.upper() if (first or last) else slide.title, title_font, W - 220)
    body_lines = _wrap(d, slide.body, body_font, W - 220)
    t_h, b_h = int(title_font.size * 1.15) * len(title_lines), 58 * len(body_lines)
    card_h = 60 + t_h + 30 + b_h + 50
    y0 = H - 150 - card_h
    fill = accent if last else (251, 246, 238, 238)
    d.rounded_rectangle([60, y0, W - 60, y0 + card_h], radius=40, fill=fill)
    y = y0 + 60
    for line in title_lines:
        d.text((100, y), line, font=title_font, fill=(255, 255, 255, 255) if last else ink)
        y += int(title_font.size * 1.15)
    y += 30
    for line in body_lines:
        d.text((100, y), line, font=body_font, fill=(255, 255, 255, 255) if last else muted)
        y += 58

    small = _font(rc["body_font"], 32)
    d.rounded_rectangle([60, 56, 60 + d.textlength("@" + handle, font=small) + 48, 112], radius=28, fill=(255, 255, 255, 225))
    d.text((84, 64), "@" + handle, font=small, fill=ink)
    counter = f"{i + 1}/{total}"
    d.text((W - 80 - d.textlength(counter, font=small), 64), counter, font=small, fill=(255, 255, 255, 255))
    if first:
        tiny = _font(rc["body_font"], 24)
        d.text((W - 60 - d.textlength("Stock photo", font=tiny), y0 - 36), "Stock photo", font=tiny, fill=(255, 255, 255, 255))
    img.alpha_composite(layer)
    img.convert("RGB").save(out, quality=92)
