"""Builds a single-product reel from Runway story shots (stories/<name>.yaml): 5 beats of about 2 seconds.

Beats are a mix of AI clips and photo scenes (a still with a slow camera move), each with a short caption, then the
end card with the real product photo and Comment SHOP. Photo scenes cost no clip credits.

    python tools/product_reel.py out/anker-station assets/products/anker-525-charging-station.jpg "Anker 525 charging station" \
        assets/reels/anker-station.mp4 \
        "clip:shot1:0.3:Too many chargers on your desk?" "photo:shot2::Cables everywhere. Outlets full." \
        "photo:shot3::Meet the one that fixes it" "clip:shot4:0.3:Clean desk. Everything charging."
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dtd.config import ROOT, load_config  # noqa: E402
from dtd.reel import FADE, LIST_END, _finish, _segment, brand_overlay, caption_overlay, end_card  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("shots", type=Path)
    ap.add_argument("product_photo", type=Path)
    ap.add_argument("name")
    ap.add_argument("out", type=Path)
    ap.add_argument("beats", nargs="+", help="kind:shot:start_seconds:caption  (kind = clip or photo)")
    ap.add_argument("--beat", type=float, default=2.2, help="seconds per beat")
    ap.add_argument("--slow", type=float, default=1.0)
    a = ap.parse_args()

    cfg = load_config()
    rc = cfg["reel"]
    work = ROOT / "output" / "product-work" / a.out.stem
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    brand = work / "brand.png"
    brand_overlay(cfg, brand)
    segments, lengths = [], []
    for i, spec in enumerate(a.beats):
        kind, shot, start, text = spec.split(":", 3)
        seg, overlay = work / f"seg_{i}.mp4", work / f"overlay_{i}.png"
        caption_overlay(cfg, text, overlay, hook=(i == 0), centre=0.30)
        length = a.beat + FADE
        if kind == "clip":
            clip = work / f"clip_{i}.mp4"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", start or "0", "-i", str(a.shots / f"{shot}.mp4"),
                            "-vf", f"setpts={a.slow}*PTS", "-an", "-t", f"{length + 0.2:.2f}", "-c:v", "libx264",
                            "-crf", "14", str(clip)], check=True)
            _segment(rc, clip, overlay, None, length, seg, brand=brand)
        else:
            _segment(rc, None, overlay, None, length, seg, photo=a.shots / f"{shot}.jpg", motion=i, brand=brand)
        segments.append(seg)
        lengths.append(length)
    frame, seg = work / "end.png", work / "seg_end.mp4"
    end_card(cfg, a.product_photo, a.name, frame, contain=True)
    _segment(rc, None, None, None, LIST_END + FADE, seg, frame, motion=len(a.beats), brand=brand, endcard=True)
    segments.append(seg)
    lengths.append(LIST_END + FADE)
    final = _finish(rc, SimpleNamespace(caption=a.name), work, segments, lengths)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(final, a.out)
    print(f"wrote {a.out} ({sum(lengths) - FADE * (len(lengths) - 1):.1f}s)")


if __name__ == "__main__":
    main()
