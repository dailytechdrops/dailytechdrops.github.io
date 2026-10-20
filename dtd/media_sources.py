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
    # STOCK_SOURCE forces one source, so the same reel can be rendered from each and compared.
    source = env("STOCK_SOURCE")
    if source == "graphics":
        return None
    if source == "pexels" or (not source and env("PEXELS_API_KEY")):
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
