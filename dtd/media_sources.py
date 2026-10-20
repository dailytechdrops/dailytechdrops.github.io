"""Voiceover (Piper, free, or ElevenLabs) and stock footage (Pexels, free).
Without a voice or a Pexels key the reel uses silent beats over branded
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


_piper_voice = None


def _piper(cfg: dict, text: str, out: Path) -> Path | None:
    global _piper_voice
    model = ROOT / "voices" / f"{cfg['voice']['piper_voice']}.onnx"
    if not model.exists():
        print(f"Piper voice not found at {model}; rendering without voiceover")
        return None
    from piper import PiperVoice, SynthesisConfig

    if _piper_voice is None:
        _piper_voice = PiperVoice.load(model)
    with wave.open(str(out), "wb") as wav:
        _piper_voice.synthesize_wav(text, wav, syn_config=SynthesisConfig(length_scale=cfg["voice"]["piper_speed"]))
    return out


def stock_clip(query: str, out: Path, used: set[int]) -> Path | None:
    key = env("PEXELS_API_KEY")
    if not key:
        return None
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
