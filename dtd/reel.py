"""Renders the vertical reel: one segment per beat (footage or branded
gradient, caption overlay, voiceover), then joins them and mixes in music."""

import random
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import ROOT
from .media_sources import duration, stock_clip, tts
from .writer import DropContent


def render_reel(cfg: dict, content: DropContent, workdir: Path) -> Path:
    workdir.mkdir(parents=True, exist_ok=True)
    rc = cfg["reel"]
    used_videos: set[int] = set()
    segments = []

    for i, beat in enumerate(content.beats):
        is_hook, is_cta = i == 0, i == len(content.beats) - 1
        voice = tts(cfg, beat.voiceover, workdir / f"voice_{i}.mp3")
        seg_len = duration(voice) + 0.35 if voice else rc["seconds_per_beat_without_voice"]
        clip = stock_clip(beat.broll_query, workdir / f"clip_{i}.mp4", used_videos)
        overlay = workdir / f"overlay_{i}.png"
        caption_overlay(cfg, beat.on_screen, overlay, hook=is_hook, cta=is_cta)
        seg = workdir / f"seg_{i}.mp4"
        _segment(rc, clip, overlay, voice, seg_len, seg)
        segments.append(seg)

    joined = workdir / "joined.mp4"
    listing = workdir / "segments.txt"
    listing.write_text("".join(f"file '{s.name}'\n" for s in segments))
    _ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(joined)])

    final = workdir / "reel.mp4"
    music = sorted((ROOT / "assets" / "music").glob("*.mp3"))
    if music:
        # Seeded by the product so voice variants of one reel share a track.
        track = random.Random(content.caption).choice(music)
        _ffmpeg([
            "-i", str(joined), "-stream_loop", "-1", "-i", str(track),
            "-filter_complex", f"[1:a]volume={rc['music_volume']}[m];[0:a][m]amix=inputs=2:duration=first:normalize=0[a]",
            "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
            "-movflags", "+faststart", str(final),
        ])
    else:
        _ffmpeg(["-i", str(joined), "-c", "copy", "-movflags", "+faststart", str(final)])
    return final


def _segment(rc: dict, clip: Path | None, overlay: Path, voice: Path | None, seg_len: float, out: Path) -> None:
    w, h, fps = rc["width"], rc["height"], rc["fps"]
    args = []
    if clip:
        args += ["-stream_loop", "-1", "-i", str(clip)]
        bg = f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps={fps}[bg]"
    else:
        args += ["-f", "lavfi", "-i", f"gradients=s={w}x{h}:c0=0xFBF6EE:c1=0xF6D9BF:x0=0:y0=0:x1={w}:y1={h}:speed=0.015:r={fps}"]
        bg = "[0:v]setsar=1[bg]"
    args += ["-loop", "1", "-i", str(overlay)]
    if voice:
        args += ["-i", str(voice)]
    else:
        args += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    args += [
        "-filter_complex", f"{bg};[bg][1:v]overlay=0:0,format=yuv420p[v];[2:a]apad,aformat=sample_rates=44100:channel_layouts=stereo[a]",
        "-map", "[v]", "-map", "[a]", "-t", f"{seg_len:.2f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(fps),
        "-c:a", "aac", "-b:a", "160k", str(out),
    ]
    _ffmpeg(args)


def caption_overlay(cfg: dict, text: str, out: Path, hook: bool = False, cta: bool = False) -> None:
    rc = cfg["reel"]
    w, h = rc["width"], rc["height"]
    accent = rc["accent_color"]
    ink = _rgba(rc.get("ink_color", "#3B2F27"), 255)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Handle watermark, top center, inside Instagram's safe zone.
    small = _font(rc["body_font"], 38)
    handle = "@" + cfg["brand"]["handle"]
    tw = draw.textlength(handle, font=small)
    draw.rounded_rectangle([(w - tw) / 2 - 24, 140, (w + tw) / 2 + 24, 204], radius=32, fill=(255, 255, 255, 215))
    draw.text(((w - tw) / 2, 150), handle, font=small, fill=ink)

    size = 92 if cta else 84 if hook else 70
    font = _font(rc["font"], size)
    lines = _wrap(draw, text.upper() if (hook or cta) else text, font, w - 200)
    line_h = int(size * 1.22)
    block_h = line_h * len(lines)
    top = (h - block_h) // 2 if cta else int(h * 0.60) - block_h // 2

    pad = 34
    widest = max(draw.textlength(l, font=font) for l in lines)
    box = [(w - widest) / 2 - pad, top - pad, (w + widest) / 2 + pad, top + block_h + pad * 0.6]
    # Light theme: orange for the hook and call to action, white cards otherwise.
    fill = _rgba(accent, 245) if (hook or cta) else (255, 255, 255, 235)
    text_fill = (255, 255, 255, 255) if (hook or cta) else ink
    draw.rounded_rectangle(box, radius=28, fill=fill)
    for n, line in enumerate(lines):
        lw = draw.textlength(line, font=font)
        draw.text(((w - lw) / 2, top + n * line_h), line, font=font, fill=text_fill)

    if cta:
        sub = _font(rc["body_font"], 46)
        msg = "I will DM you the link"
        sw = draw.textlength(msg, font=sub)
        draw.rounded_rectangle([(w - sw) / 2 - 30, box[3] + 30, (w + sw) / 2 + 30, box[3] + 116], radius=43, fill=(255, 255, 255, 235))
        draw.text(((w - sw) / 2, box[3] + 44), msg, font=sub, fill=ink)
    img.save(out)


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
