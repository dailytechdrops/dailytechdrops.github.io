"""Builds a list reel whose product beats are AI story clips (Runway) instead of still photos.

Same look as a list reel: hook frame with all products, one beat per product with its "1 of 3" caption,
end card with all of them, music only. Each product beat plays the matching clip from the story folder
(shot1.mp4 for product 1, ...), trimmed to its calmest part.

    python tools/story_reel.py weeks/2026-10-31.yaml "2026-11-05 11:30" out/desk-pain assets/reels/desk-pain.mp4 \
        --start 0.5,0.5,0.5 --beat 2.6

The result is set as the entry's content.reel_file, so the post run uploads it as is.
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dtd.config import ROOT, load_config, load_week  # noqa: E402
from dtd.reel import (FADE, LIST_END, LIST_HOOK, _finish, _segment, brand_overlay, caption_overlay,  # noqa: E402
                      end_card, product_collage, studio_frame)
from dtd.writer import write_content  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("week")
    ap.add_argument("slot")
    ap.add_argument("clips", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--start", default="", help="seconds into each clip to start, comma separated")
    ap.add_argument("--beat", type=float, default=2.6, help="seconds per product beat")
    ap.add_argument("--slow", type=float, default=1.0, help="slow each clip down by this factor")
    ap.add_argument("--hook", default="", help="optional clip for the hook beat (e.g. shot1), start seconds after a colon")
    ap.add_argument("--shots", default="", help="clip per product beat, comma separated (default shot1,shot2,...)")
    a = ap.parse_args()

    cfg = load_config()
    item = next(i for i in load_week(ROOT / a.week) if str(i["slot"]) == a.slot)
    content = write_content(cfg, item)
    rc = cfg["reel"]
    work = ROOT / "output" / "story-work" / a.out.stem
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    brand = work / "brand.png"
    brand_overlay(cfg, brand)
    beats = content.beats
    photos = [ROOT / b.product_photo for b in beats[1:-1] if b.product_photo]
    starts = [float(s) for s in a.start.split(",")] if a.start else []
    shots = a.shots.split(",") if a.shots else [f"shot{k}" for k in range(1, len(beats) - 1)]
    segments, lengths = [], []
    for i, beat in enumerate(beats):
        seg, frame, overlay = work / f"seg_{i}.mp4", work / f"frame_{i}.png", work / f"overlay_{i}.png"
        if i == len(beats) - 1:
            collage = work / "collage.png"
            product_collage(photos, collage)
            end_card(cfg, collage, content.label or item["name"], frame, contain=True, links=True)
            _segment(rc, None, None, None, LIST_END + FADE, seg, frame, motion=i, brand=brand, endcard=True)
            lengths.append(LIST_END + FADE)
        elif i == 0 and a.hook:
            name, _, st = a.hook.partition(":")
            clip = work / "clip_0.mp4"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", st or "0", "-i", str(a.clips / f"{name}.mp4"),
                            "-vf", f"setpts={a.slow}*PTS", "-an", "-t", f"{a.beat + FADE + 0.2:.2f}", "-c:v", "libx264",
                            "-crf", "14", str(clip)], check=True)
            caption_overlay(cfg, beat.on_screen, overlay, hook=True, label=content.label or "", centre=0.30)
            _segment(rc, clip, overlay, None, a.beat + FADE, seg, brand=brand)
            lengths.append(a.beat + FADE)
        elif i == 0:
            studio_frame(cfg, None, frame, variant=0, seed=f"{item['name']}|0", collage=photos)
            caption_overlay(cfg, beat.on_screen, overlay, hook=True, label=content.label or "", centre=0.30)
            _segment(rc, None, overlay, None, LIST_HOOK + FADE, seg, frame, motion=0, brand=brand, grade=False)
            lengths.append(LIST_HOOK + FADE)
        elif shots[i - 1] == "photo":
            # No usable clip for this product: its studio photo beat, as in a plain list reel.
            studio_frame(cfg, ROOT / beat.product_photo, frame, variant=0, seed=f"{item['name']}|{i}")
            caption_overlay(cfg, beat.on_screen, overlay, label=f"{i} of {len(beats) - 2}", centre=0.30)
            _segment(rc, None, overlay, None, a.beat + FADE, seg, frame, motion=i, brand=brand, grade=False)
            lengths.append(a.beat + FADE)
        else:
            seg_len = a.beat + FADE
            start = starts[i - 1] if i - 1 < len(starts) else 0.0
            clip = work / f"clip_{i}.mp4"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start}", "-i", str(a.clips / f"{shots[i - 1]}.mp4"),
                            "-vf", f"setpts={a.slow}*PTS", "-an", "-t", f"{seg_len + 0.2:.2f}", "-c:v", "libx264",
                            "-crf", "14", str(clip)], check=True)
            caption_overlay(cfg, beat.on_screen, overlay, label=f"{i} of {len(beats) - 2}", centre=0.30)
            _segment(rc, clip, overlay, None, seg_len, seg, brand=brand)
            lengths.append(seg_len)
        segments.append(seg)
    final = _finish(rc, content, work, segments, lengths)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(final, a.out)
    print(f"wrote {a.out} ({sum(lengths) - FADE * (len(lengths) - 1):.1f}s)")


if __name__ == "__main__":
    main()
