"""Renders the vertical reel: one segment per beat (photo with a slow camera move, footage, or a
branded gradient, with an animated caption card and voiceover), then crossfades the beats together
and mixes in music that ducks under the voice. With photos, the last beat is a branded end card."""

import random
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .config import ROOT
from .media_sources import duration, pinned_clip, stock_clip, stock_photo, tts
from .writer import DropContent


# Evens out voices so Piper, Kokoro and ElevenLabs all come out at the same loudness.
LOUDNORM = "loudnorm=I=-16:TP=-1.5:LRA=11"
# Length of the crossfade between beats, in seconds.
FADE = 0.35
# A light, warm, airy grade for stock photos: a touch brighter, softer contrast, warmer.
GRADE = "eq=brightness=0.025:contrast=0.95:saturation=1.05,colorbalance=rm=0.025:gm=0.005:bm=-0.025"


def render_reel(cfg: dict, content: DropContent, workdir: Path, name: str = "") -> Path:
    workdir.mkdir(parents=True, exist_ok=True)
    rc = cfg["reel"]
    used_videos: set[int] = set()
    segments, lengths = [], []
    brand = workdir / "brand.png"
    brand_overlay(cfg, brand)
    photos = _photos(content, workdir)

    for i, beat in enumerate(content.beats):
        is_hook, is_cta = i == 0, i == len(content.beats) - 1
        voice = tts(cfg, beat.voiceover, workdir / f"voice_{i}.mp3")
        seg_len = (duration(voice) + 0.35 if voice else rc["seconds_per_beat_without_voice"]) + FADE
        if is_hook:
            seg_len += 0.2  # a beat of breathing room before the first word lands
        shot = photos[i % len(photos)] if photos else None
        clip = None
        pinned = content.clip_ids[i] if i < len(content.clip_ids) and not is_cta else 0
        if pinned:
            # Real footage of people using this kind of product, picked by hand, beats a still photo.
            clip = pinned_clip(pinned, workdir / f"clip_{i}.mp4")
            shot = None if clip else shot
        if not shot and not clip:
            clip = stock_clip(beat.broll_query, workdir / f"clip_{i}.mp4", used_videos)
        overlay = workdir / f"overlay_{i}.png"
        seg = workdir / f"seg_{i}.mp4"
        if is_cta and photos:
            # The call to action is a clean branded end card around a photo of the product type.
            card = workdir / "endcard.png"
            end_card(cfg, photos[i % len(photos)], name, card)
            _segment(rc, None, None, voice, seg_len, seg, card, motion=i, brand=brand, endcard=True, voice_delay=0.15)
        else:
            label = _short_name(name) if i == 1 else ((content.label or "Today's drop") if is_hook else "")
            natural = (content.look or rc.get("look", "card")) == "natural"
            caption_overlay(cfg, beat.on_screen, overlay, hook=is_hook, cta=is_cta, label=label, natural=natural)
            _segment(rc, clip, overlay, voice, seg_len, seg, shot, motion=i, brand=brand,
                     voice_delay=0.35 if is_hook else 0.15)
        segments.append(seg)
        lengths.append(seg_len)

    joined = workdir / "joined.mp4"
    _join(segments, lengths, joined)
    total = sum(lengths) - FADE * (len(lengths) - 1)

    final = workdir / "reel.mp4"
    music = sorted((ROOT / "assets" / "music").glob("*.mp3"))
    if music:
        # Seeded by the product so voice variants of one reel share a track.
        track = random.Random(content.caption).choice(music)
        vol = rc["music_volume"]
        # Music sits a little higher between lines and dips under the voice, then fades out at the end.
        _ffmpeg([
            "-i", str(joined), "-stream_loop", "-1", "-i", str(track),
            "-filter_complex",
            f"[0:a]asplit=2[v][key];"
            f"[1:a]volume={vol * 1.6:.2f},afade=t=in:d=0.4,afade=t=out:st={total - 0.9:.2f}:d=0.9[m];"
            f"[m][key]sidechaincompress=threshold=0.02:ratio=4:attack=15:release=350[duck];"
            f"[v][duck]amix=inputs=2:duration=first:normalize=0,{LOUDNORM}[a]",
            "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-t", f"{total:.2f}", "-movflags", "+faststart", str(final),
        ])
    else:
        _ffmpeg(["-i", str(joined), "-af", LOUDNORM, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(final)])
    return final


def _photos(content: DropContent, workdir: Path) -> list[Path]:
    """One photo per beat: the pinned picks when the week file has them, otherwise the photo search."""
    if not content.photo_query and not content.photo_ids:
        return []
    shots = []
    for i in range(len(content.beats)):
        shot = stock_photo(content.photo_query, workdir / f"photo_{i}.jpg", i, content.photo_ids)
        if shot:
            shots.append(shot)
    return shots


def _segment(rc: dict, clip: Path | None, overlay: Path | None, voice: Path | None, seg_len: float, out: Path,
             photo: Path | None = None, motion: int = 0, brand: Path | None = None, endcard: bool = False,
             voice_delay: float = 0.15) -> None:
    w, h, fps = rc["width"], rc["height"], rc["fps"]
    frames = int(seg_len * fps) + 1
    args = []
    if photo:
        # A slow, smooth camera move across the still. The photo is first cover-cropped to the frame at
        # 3x size so the move never jitters; even beats push in, odd beats ease out while drifting sideways.
        big_w, big_h = w * 3, h * 3
        p = f"(on/{frames})"
        ease = f"(1-pow(1-{p},2))"
        if endcard:
            zoom, x, y = f"1+0.035*{ease}", "iw/2-iw/zoom/2", "ih/2-ih/zoom/2"
        elif motion % 2 == 0:
            zoom, x, y = f"1.02+0.10*{ease}", "iw/2-iw/zoom/2", f"ih/2-ih/zoom/2-ih*0.015*{ease}"
        else:
            zoom = f"1.12-0.07*{ease}"
            drift = 1 if motion % 4 == 1 else -1
            x, y = f"iw/2-iw/zoom/2+{drift}*iw*0.02*({ease}-0.5)", "ih/2-ih/zoom/2"
        args += ["-i", str(photo)]
        grade = "" if endcard else f",{GRADE}"
        bg = (f"[0:v]scale={big_w}:{big_h}:force_original_aspect_ratio=increase:flags=lanczos,crop={big_w}:{big_h},"
              f"zoompan=z='{zoom}':x='{x}':y='{y}':d={frames}:s={w}x{h}:fps={fps},setsar=1{grade}[bg]")
    elif clip:
        args += ["-stream_loop", "-1", "-i", str(clip)]
        bg = f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps={fps},{GRADE}[bg]"
    else:
        args += ["-f", "lavfi", "-i", f"gradients=s={w}x{h}:c0=0xFBF6EE:c1=0xF6D9BF:x0=0:y0=0:x1={w}:y1={h}:speed=0.015:r={fps}"]
        bg = "[0:v]setsar=1[bg]"

    chain = [bg]
    last, n = "bg", 1
    if brand:
        args += ["-loop", "1", "-i", str(brand)]
        chain.append(f"[{last}][{n}:v]overlay=0:0[b]")
        last, n = "b", n + 1
    if overlay:
        # The caption card fades in and rises into place just after the cut.
        args += ["-loop", "1", "-i", str(overlay)]
        st, d = 0.25, 0.45
        rise = f"if(lt(t,{st}),36,if(lt(t,{st + d}),36*pow(1-(t-{st})/{d},3),0))"
        chain.append(f"[{n}:v]format=rgba,fade=t=in:st={st}:d={d}:alpha=1[cap]")
        chain.append(f"[{last}][cap]overlay=x=0:y='{rise}':eval=frame[c]")
        last, n = "c", n + 1
    chain.append(f"[{last}]format=yuv420p[v]")

    if voice:
        args += ["-i", str(voice)]
    else:
        args += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    ms = int(voice_delay * 1000)
    chain.append(f"[{n}:a]aformat=sample_rates=44100:channel_layouts=stereo,adelay={ms}|{ms},apad[a]")
    args += [
        "-filter_complex", ";".join(chain),
        "-map", "[v]", "-map", "[a]", "-t", f"{seg_len:.2f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-r", str(fps),
        "-c:a", "pcm_s16le", str(out.with_suffix(".mov")),
    ]
    _ffmpeg(args)
    out.with_suffix(".mov").rename(out)


def _join(segments: list[Path], lengths: list[float], out: Path) -> None:
    """Crossfades the beats into one clip (video and voice)."""
    args = []
    for s in segments:
        args += ["-i", str(s)]
    chain, v, a, offset = [], "0:v", "0:a", 0.0
    for i in range(1, len(segments)):
        offset += lengths[i - 1] - FADE
        chain.append(f"[{v}][{i}:v]xfade=transition=fade:duration={FADE}:offset={offset:.3f}[v{i}]")
        chain.append(f"[{a}][{i}:a]acrossfade=d={FADE}:c1=tri:c2=tri[a{i}]")
        v, a = f"v{i}", f"a{i}"
    if not chain:
        chain = ["[0:v]null[v0]", "[0:a]anull[a0]"]
        v, a = "v0", "a0"
    args += [
        "-filter_complex", ";".join(chain), "-map", f"[{v}]", "-map", f"[{a}]",
        "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-g", "60", "-c:a", "pcm_s16le", str(out.with_suffix(".mov")),
    ]
    _ffmpeg(args)
    out.with_suffix(".mov").rename(out)


def brand_overlay(cfg: dict, out: Path) -> None:
    """The small logo and handle at the top, inside Instagram's safe zone, on every beat."""
    rc = cfg["reel"]
    w, h = rc["width"], rc["height"]
    ink = _rgba(rc.get("ink_color", "#3B2F27"), 255)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    font = _font(rc["body_font"], 34)
    handle = "@" + cfg["brand"]["handle"]
    draw = ImageDraw.Draw(img)
    tw = draw.textlength(handle, font=font)
    icon = 52
    pill_w = icon + 14 + tw + 36
    x0, y0 = (w - pill_w) / 2, 150
    _card(img, [x0, y0, x0 + pill_w, y0 + 68], radius=34, fill=(255, 255, 255, 230), shadow=40)
    img.alpha_composite(_logo(icon), (int(x0 + 10), int(y0 + 8)))
    draw = ImageDraw.Draw(img)
    draw.text((x0 + 10 + icon + 14, y0 + 13), handle, font=font, fill=ink)
    img.save(out)


def caption_overlay(cfg: dict, text: str, out: Path, hook: bool = False, cta: bool = False, label: str = "",
                    natural: bool = False) -> None:
    """A soft white card with the beat's line in sentence case, and a small orange tag above it.
    The natural look drops the card: white text with a soft shadow in the upper third, the way
    people caption their own videos, so the footage stays the subject."""
    rc = cfg["reel"]
    if natural:
        _natural_caption(rc, text, out, hook or cta, label)
        return
    w, h = rc["width"], rc["height"]
    accent = _rgba(rc["accent_color"], 255)
    ink = _rgba(rc.get("ink_color", "#3B2F27"), 255)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    size = 80 if (hook or cta) else 70
    font = _font(rc["font"], size)
    lines = _wrap(draw, text, font, w - 260)
    line_h = int(size * 1.18)
    block_h = line_h * len(lines)
    pad_x, pad_y = 56, 46
    widest = max(draw.textlength(l, font=font) for l in lines)
    card_w = max(widest + pad_x * 2, 560)
    # Lower middle of the frame: clear of the handle at the top and Instagram's caption at the bottom.
    centre = int(h * 0.60)
    top = centre - (block_h + pad_y * 2) // 2
    box = [(w - card_w) / 2, top, (w + card_w) / 2, top + block_h + pad_y * 2]
    _card(img, box, radius=40, fill=(255, 255, 255, 240), shadow=70)
    draw = ImageDraw.Draw(img)
    for n, line in enumerate(lines):
        lw = draw.textlength(line, font=font)
        draw.text(((w - lw) / 2, box[1] + pad_y + 4 + n * line_h - size * 0.06), line, font=font, fill=ink)

    if label:
        # A small orange tag sitting on the card's top edge: "Today's drop" or the product name.
        tag_font = _font(rc["font"], 32)
        label = label.upper()
        while draw.textlength(label, font=tag_font) > w - 300 and tag_font.size > 22:
            tag_font = _font(rc["font"], tag_font.size - 2)
        lw = draw.textlength(label, font=tag_font)
        th = tag_font.size + 26
        tag = [(w - lw) / 2 - 28, box[1] - th / 2, (w + lw) / 2 + 28, box[1] + th / 2]
        draw.rounded_rectangle(tag, radius=th / 2, fill=accent)
        draw.text(((w - lw) / 2, tag[1] + 11), label, font=tag_font, fill=(255, 255, 255, 255))
    else:
        # Otherwise a thin orange rule at the top of the card ties the beat to the brand.
        draw.rounded_rectangle([w / 2 - 40, box[1] + 22, w / 2 + 40, box[1] + 30], radius=4, fill=accent)
    img.save(out)


def _natural_caption(rc: dict, text: str, out: Path, big: bool, label: str) -> None:
    w, h = rc["width"], rc["height"]
    size = 76 if big else 66
    font = _font(rc["font"], size)
    text_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(text_layer)
    lines = _wrap(draw, text, font, w - 200)
    line_h = int(size * 1.16)
    top = int(h * 0.22)
    for n, line in enumerate(lines):
        lw = draw.textlength(line, font=font)
        draw.text(((w - lw) / 2, top + n * line_h), line, font=font, fill=(255, 255, 255, 255))
    # A soft dark glow behind the letters keeps them readable on bright footage without a box.
    alpha = text_layer.getchannel("A")
    glow = Image.new("RGBA", (w, h), (30, 22, 16, 0))
    glow.putalpha(alpha.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(14)).point(lambda a: int(a * 0.55)))
    img = Image.alpha_composite(glow, text_layer)
    if label:
        # The product name as a small, quiet line under the caption, not a badge.
        tag_font = _font(rc["body_font"], 36)
        d = ImageDraw.Draw(img)
        lw = d.textlength(label, font=tag_font)
        y = top + len(lines) * line_h + 18
        pill = [(w - lw) / 2 - 24, y, (w + lw) / 2 + 24, y + tag_font.size + 22]
        d.rounded_rectangle(pill, radius=(pill[3] - pill[1]) / 2, fill=_rgba(rc["accent_color"], 230))
        d.text(((w - lw) / 2, y + 9), label, font=tag_font, fill=(255, 255, 255, 255))
    img.save(out)


def end_card(cfg: dict, photo: Path, name: str, out: Path) -> None:
    """The last beat: warm cream card, framed product photo, product name and the comment call to action."""
    rc = cfg["reel"]
    w, h = rc["width"], rc["height"]
    accent = _rgba(rc["accent_color"], 255)
    ink = _rgba(rc.get("ink_color", "#3B2F27"), 255)
    muted = _rgba(rc.get("muted_color", "#7A6A5D"), 255)
    keyword = cfg["instagram"]["comment_keyword"]

    bg = Image.new("RGBA", (w, h), _rgba(rc.get("background_color", "#FBF6EE"), 255))
    glow = Image.new("L", (w, h), 0)
    ImageDraw.Draw(glow).ellipse([-200, 300, w + 200, 1500], fill=110)
    glow = glow.filter(ImageFilter.GaussianBlur(220))
    bg.paste(Image.new("RGBA", (w, h), (246, 217, 191, 255)), (0, 0), glow)

    fw, fh = 760, 860
    fx, fy = (w - fw) // 2, 290
    _card(bg, [fx - 14, fy - 14, fx + fw + 14, fy + fh + 14], radius=48, fill=(255, 255, 255, 255), shadow=60)
    pic = ImageOps.fit(Image.open(photo).convert("RGB"), (fw, fh), Image.LANCZOS, centering=(0.5, 0.45))
    mask = Image.new("L", (fw, fh), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, fw, fh], radius=36, fill=255)
    bg.paste(pic, (fx, fy), mask)

    draw = ImageDraw.Draw(bg)
    y = fy + fh + 60
    title = _font(rc["font"], 54)
    for line in _wrap(draw, _short_name(name) or "Today's drop", title, w - 220)[:2]:
        lw = draw.textlength(line, font=title)
        draw.text(((w - lw) / 2, y), line, font=title, fill=ink)
        y += 66
    y += 26
    cta = _font(rc["font"], 64)
    msg = f"Comment {keyword}"
    cw = draw.textlength(msg, font=cta)
    pill = [(w - cw) / 2 - 56, y, (w + cw) / 2 + 56, y + 116]
    _card(bg, pill, radius=58, fill=accent, shadow=50)
    draw = ImageDraw.Draw(bg)
    draw.text(((w - cw) / 2, y + 22), msg, font=cta, fill=(255, 255, 255, 255))
    sub = _font(rc["body_font"], 40)
    line = "and I will DM you the link"
    sw = draw.textlength(line, font=sub)
    draw.text(((w - sw) / 2, pill[3] + 26), line, font=sub, fill=muted)
    bg.convert("RGB").save(out, quality=95)


def _short_name(name: str) -> str:
    """The product name without the pack size or model notes in brackets."""
    return name.split(" (")[0].strip()


def _card(img: Image.Image, box: list, radius: int, fill: tuple, shadow: int = 60) -> None:
    """A rounded card with a soft warm shadow under it, drawn onto img."""
    x0, y0, x1, y1 = (int(v) for v in box)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle([x0, y0 + 10, x1, y1 + 14], radius=radius, fill=(90, 60, 40, shadow))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(18)))
    ImageDraw.Draw(img).rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill)


def _logo(size: int) -> Image.Image:
    logo = ImageOps.fit(Image.open(ROOT / "assets" / "logo.png").convert("RGBA"), (size * 4, size * 4), Image.LANCZOS)
    mask = Image.new("L", logo.size, 0)
    ImageDraw.Draw(mask).ellipse([0, 0, *logo.size], fill=255)
    logo.putalpha(mask)
    return logo.resize((size, size), Image.LANCZOS)


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        test = f"{line} {word}".strip()
        if draw.textlength(test, font=font) <= max_w or not line:
            line = test
        else:
            lines.append(line)
            line = word
    return lines + [line] if line else lines


def _font(rel: str, size: int):
    path = ROOT / rel
    if path.exists():
        return ImageFont.truetype(str(path), size)
    return ImageFont.truetype("DejaVuSans-Bold.ttf", size)


def _rgba(hex_color: str, alpha: int) -> tuple:
    c = hex_color.lstrip("#")
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), alpha)


def _ffmpeg(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)
