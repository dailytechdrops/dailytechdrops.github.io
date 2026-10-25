"""Voiceover (Piper or Kokoro, both free, or ElevenLabs) and stock footage (Pexels or
Pixabay, both free). Without a voice or a footage key the reel uses silent beats over branded
gradient backgrounds."""

import json
import subprocess
import wave
from pathlib import Path

import requests

from .config import ROOT, env


def tts(cfg: dict, text: str, out: Path) -> Path | None:
    provider = cfg["voice"]["provider"]
    if provider == "piper":
        return _piper(cfg, text, out.with_suffix(".wav"))
    if provider == "kokoro":
        return _kokoro(cfg, text, out.with_suffix(".wav"))
    key = env("ELEVENLABS_API_KEY")
    if provider != "elevenlabs" or not key:
        return None
    r = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{cfg['voice']['voice_id']}",
        params={"output_format": "mp3_44100_128"},
        headers={"xi-api-key": key, "Content-Type": "application/json"},
        json={"text": text, "model_id": cfg["voice"]["model_id"]},
        timeout=120,
    )
    r.raise_for_status()
    out.write_bytes(r.content)
    return out


_piper_voices: dict = {}


def _piper(cfg: dict, text: str, out: Path) -> Path | None:
    model = ROOT / "voices" / f"{cfg['voice']['piper_voice']}.onnx"
    if not model.exists():
        print(f"Piper voice not found at {model}; rendering without voiceover")
        return None
    from piper import PiperVoice, SynthesisConfig

    if model not in _piper_voices:
        _piper_voices[model] = PiperVoice.load(model)
    with wave.open(str(out), "wb") as wav:
        _piper_voices[model].synthesize_wav(text, wav, syn_config=SynthesisConfig(length_scale=cfg["voice"]["piper_speed"]))
    return out


_kokoro_pipeline = None


def _kokoro(cfg: dict, text: str, out: Path) -> Path | None:
    # Kokoro is an open-source voice that sounds more natural than Piper. It needs
    # the kokoro, soundfile and torch packages, installed only when it is used.
    global _kokoro_pipeline
    try:
        import numpy as np
        import soundfile as sf
        from kokoro import KPipeline
    except ImportError:
        print("Kokoro is not installed; falling back to Piper")
        return _piper(cfg, text, out)
    if _kokoro_pipeline is None:
        _kokoro_pipeline = KPipeline(lang_code="a")
    v = cfg["voice"]
    chunks = [audio for _, _, audio in _kokoro_pipeline(text, voice=v.get("kokoro_voice", "af_heart"), speed=v.get("kokoro_speed", 1.05))]
    sf.write(str(out), np.concatenate(chunks), 24000)
    return out


def stock_clip(query: str, out: Path, used: set[int]) -> Path | None:
    if env("PEXELS_API_KEY"):
        return _pexels(query, out, used)
    if env("PIXABAY_API_KEY"):
        return _pixabay(query, out, used)
    return None


def _pixabay(query: str, out: Path, used: set[int]) -> Path | None:
    r = requests.get(
        "https://pixabay.com/api/videos/",
        params={"key": env("PIXABAY_API_KEY"), "q": query[:100], "per_page": 20, "safesearch": "true", "video_type": "film"},
        timeout=60,
    )
    r.raise_for_status()
    # Skip chroma-key plates, silhouettes and CGI loops; they look off-brand.
    junk = ("green screen", "greenscreen", "chroma", "alpha", "silhouette", "3d", "animation", "render", "background loop")
    hits = [h for h in r.json().get("hits", []) if h["id"] not in used and not any(j in h.get("tags", "").lower() for j in junk)]
    # Results come most relevant first. Take the first tall clip among the top few,
    # otherwise the most relevant sharp one (most Pixabay clips are landscape).
    candidates = []
    for h in hits:
        for size in ("large", "medium"):
            v = h.get("videos", {}).get(size) or {}
            if v.get("url") and v.get("height", 0) >= 720:
                candidates.append((v["height"] > v["width"], h["id"], v["url"]))
                break
    if not candidates:
        return None
    _, vid, url = next((c for c in candidates[:5] if c[0]), candidates[0])
    data = requests.get(url, timeout=180)
    data.raise_for_status()
    out.write_bytes(data.content)
    used.add(vid)
    return out


# Pixabay tags that mean the picture shows a different brand, or an old or black and white look.
_BAD_TAGS = {"apple", "macbook", "iphone", "vintage", "retro", "old", "antique", "black and white", "monochrome", "buzzer", "padlock", "car", "vehicle", "electric car", "charging station", "flower", "flowers", "mountain", "hiking", "bottle", "drink", "virus", "malware", "biohazard", "danger", "hacker", "cinnamon", "spice", "food"}


def stock_photo(query: str, out: Path, n: int = 0) -> Path | None:
    """A tall, sharp stock photo of the product type (Pixabay, free), or None.

    Pixabay's own order is loose, so the 40 best matches are re-ranked by how many query words
    show up in their tags, and ones tagged with another brand or an old look are pushed down.

    A query naming a folder under assets/photos/ uses our own product photos instead, in name order."""
    own = ROOT / query if query and query.startswith("assets/photos/") else None
    if own and own.is_dir():
        from PIL import Image, ImageOps
        files = sorted(p for p in own.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"})
        if not files:
            return None
        ImageOps.exif_transpose(Image.open(files[n % len(files)])).convert("RGB").save(out, quality=92)
        return out
    if not (query and env("PIXABAY_API_KEY")):
        return None
    r = requests.get(
        "https://pixabay.com/api/",
        params={"key": env("PIXABAY_API_KEY"), "q": query[:100], "image_type": "photo", "orientation": "vertical",
                "safesearch": "true", "min_height": 1200, "per_page": 40},
        timeout=60,
    )
    r.raise_for_status()
    hits = r.json().get("hits", [])
    if not hits:
        return None
    words = [w for w in query.lower().split() if len(w) > 2]

    def score(item: tuple[int, dict]) -> tuple[int, int]:
        i, hit = item
        tags = hit.get("tags", "").lower()
        points = sum(w in tags for w in words) - 3 * sum(b in tags for b in _BAD_TAGS)
        return (-points, i)

    ranked = [h for _, h in sorted(enumerate(hits), key=score)]
    hit = ranked[n % len(ranked)]
    data = requests.get(hit.get("largeImageURL") or hit["webformatURL"], timeout=120)
    data.raise_for_status()
    out.write_bytes(data.content)
    return out


def _pexels(query: str, out: Path, used: set[int]) -> Path | None:
    key = env("PEXELS_API_KEY")
    r = requests.get(
        "https://api.pexels.com/videos/search",
        params={"query": query, "orientation": "portrait", "per_page": 10, "size": "medium"},
        headers={"Authorization": key},
        timeout=60,
    )
    r.raise_for_status()
    for video in r.json().get("videos", []):
        if video["id"] in used:
            continue
        files = [f for f in video["video_files"] if f.get("height") and f["height"] >= 1280 and f["height"] > f["width"]]
        if not files:
            continue
        best = min(files, key=lambda f: abs(f["height"] - 1920))
        data = requests.get(best["link"], timeout=180)
        data.raise_for_status()
        out.write_bytes(data.content)
        used.add(video["id"])
        return out
    return None


def duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(result.stdout)["format"]["duration"])
