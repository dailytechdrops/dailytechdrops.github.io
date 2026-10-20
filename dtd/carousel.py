"""Renders the photo carousel as 1080x1350 (4:5) slides."""

from pathlib import Path

from PIL import Image, ImageDraw

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

    for i, slide in enumerate(content.carousel):
        first, last = i == 0, i == total - 1
        img = Image.new("RGB", (W, H), bg)
        draw = ImageDraw.Draw(img)
        # Accent bar and footer give every slide the same frame.
        draw.rectangle([0, 0, W, 18], fill=accent)
        small = _font(rc["body_font"], 34)
        draw.text((80, H - 110), "@" + cfg["brand"]["handle"], font=small, fill=muted)
        counter = f"{i + 1}/{total}"
        draw.text((W - 80 - draw.textlength(counter, font=small), H - 110), counter, font=small, fill=muted)

        title_font = _font(rc["font"], 104 if first else 86)
        title_lines = _wrap(draw, slide.title.upper() if (first or last) else slide.title, title_font, W - 160)
        y = 300 if first else 260
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
