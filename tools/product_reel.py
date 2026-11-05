"""Builds a single-product reel from Runway story shots (stories/<name>.yaml): about 5 beats of 2 to 3 seconds.

The story file's `reel:` section lists the beats: each is an AI clip (kind clip) or a photo scene (kind photo) with a
first-person voiceover line (what Kevin would say if he filmed it) and optional caption text. With no caption the beat
shows no on-screen text. The end card shows the product photo and Comment SHOP. Voice comes from the configured free
voice (Kokoro, config.yaml voice:) and is mixed over ducked music.

    python tools/product_reel.py anker-station [--out assets/reels/anker-station.mp4] [--shots out/anker-station]
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dtd.config import ROOT, load_config  # noqa: E402
from dtd.media_sources import duration, tts  # noqa: E402
from dtd.reel import FADE, LIST_END, _finish, _segment, brand_overlay, caption_overlay, end_card  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("name", help="story name in stories/")
    ap.add_argument("--shots", type=Path, default=None, help="folder with shotN.mp4/jpg (default out/<name>)")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--no-voice", action="store_true")
    a = ap.parse_args()

    spec = yaml.safe_load((ROOT / "stories" / f"{a.name}.yaml").read_text())
    reel = spec["reel"]
    shots = a.shots or ROOT / "out" / a.name
    out = a.out or ROOT / "out" / f"{a.name}-voiced.mp4"
    cfg = load_config()
    rc = cfg["reel"]
    work = ROOT / "output" / "product-work" / a.name
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    brand = work / "brand.png"
    brand_overlay(cfg, brand)
    base = reel.get("beat_seconds", 2.2)
    segments, lengths = [], []
    for i, beat in enumerate(reel["beats"]):
        seg = work / f"seg_{i}.mp4"
        voice = None if a.no_voice else tts(cfg, beat["voiceover"], work / f"voice_{i}.mp3")
        length = (max(duration(voice) + 0.15, 1.5) if voice else base) + FADE
        if i == 0:
            length += 0.15   # a beat before the first word lands
        overlay = None
        if beat.get("caption"):
            overlay = work / f"overlay_{i}.png"
            caption_overlay(cfg, beat["caption"], overlay, hook=(i == 0), centre=0.30)
        if beat.get("kind", "clip") == "clip":
            clip = work / f"clip_{i}.mp4"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(beat.get("start", 0.3)), "-i",
                            str(shots / f"{beat['shot']}.mp4"), "-an", "-t", f"{length + 0.2:.2f}", "-c:v", "libx264",
                            "-crf", "14", str(clip)], check=True)
            _segment(rc, clip, overlay, voice, length, seg, brand=brand)
        else:
            photo = ROOT / beat["photo"] if beat.get("photo") else shots / f"{beat['shot']}.jpg"
            _segment(rc, None, overlay, voice, length, seg, photo=photo, motion=i, brand=brand)
        segments.append(seg)
        lengths.append(length)
    frame, seg = work / "end.png", work / "seg_end.mp4"
    end_card(cfg, ROOT / reel["product_photo"], reel["name"], frame, contain=True)
    voice = None if a.no_voice else tts(cfg, reel["end_voiceover"], work / "voice_end.mp3")
    end_len = (max(duration(voice) + 0.3, 2.2) if voice else LIST_END) + FADE
    _segment(rc, None, None, voice, end_len, seg, frame, motion=len(segments), brand=brand, endcard=True)
    segments.append(seg)
    lengths.append(end_len)
    final = _finish(rc, SimpleNamespace(caption=reel["name"]), work, segments, lengths)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(final, out)
    print(f"wrote {out} ({sum(lengths) - FADE * (len(lengths) - 1):.1f}s)")


if __name__ == "__main__":
    main()
