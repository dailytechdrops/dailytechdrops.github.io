"""Writes a short, original, royalty-free background track (assets/music/*.mp3).

It is generated from scratch (soft chords, a bell arpeggio and a light beat), so there is
nothing to license or credit. Replace or add your own mp3 files in assets/music to override.
"""

import math
import random
import struct
import subprocess
import sys
import wave
from pathlib import Path

SR = 44100
BPM = 112
BEAT = 60 / BPM
# C - G - Am - F, a bright, familiar loop. Notes are MIDI numbers.
CHORDS = [(48, 52, 55, 59), (43, 47, 50, 54), (45, 48, 52, 55), (41, 45, 48, 52)]
ARP = [0, 2, 1, 3, 2, 1, 3, 2]


def hz(m):
    return 440 * 2 ** ((m - 69) / 12)


def render(seed: int, bars: int = 16) -> list[float]:
    rnd = random.Random(seed)
    n = int(bars * 4 * BEAT * SR)
    out = [0.0] * n
    for bar in range(bars):
        chord = CHORDS[bar % 4]
        t0 = bar * 4 * BEAT
        # Pad: the chord held for the bar, with a slow fade in and out.
        for note in chord:
            f = hz(note + 12)
            for i in range(int(4 * BEAT * SR)):
                x = i / SR
                env = min(1, x / 0.4) * min(1, (4 * BEAT - x) / 0.4)
                out[int(t0 * SR) + i] += 0.05 * env * (math.sin(2 * math.pi * f * x) + 0.4 * math.sin(2 * math.pi * 2 * f * x))
        # Bell arpeggio on eighth notes, one octave up.
        for k, idx in enumerate(ARP):
            f = hz(chord[idx] + 24)
            start = int((t0 + k * BEAT / 2) * SR)
            for i in range(int(0.45 * SR)):
                x = i / SR
                if start + i < n:
                    out[start + i] += 0.07 * math.exp(-6 * x) * math.sin(2 * math.pi * f * x)
        # Kick on every beat, soft hat on the off-beats.
        for b in range(4):
            start = int((t0 + b * BEAT) * SR)
            for i in range(int(0.18 * SR)):
                x = i / SR
                if start + i < n:
                    out[start + i] += 0.22 * math.exp(-18 * x) * math.sin(2 * math.pi * (110 - 60 * x * 4) * x)
            hat = int((t0 + b * BEAT + BEAT / 2) * SR)
            for i in range(int(0.04 * SR)):
                if hat + i < n:
                    out[hat + i] += 0.025 * rnd.uniform(-1, 1) * math.exp(-60 * i / SR)
    peak = max(abs(v) for v in out) or 1
    return [v / peak * 0.9 for v in out]


def main() -> None:
    dest = Path(sys.argv[1] if len(sys.argv) > 1 else "assets/music")
    dest.mkdir(parents=True, exist_ok=True)
    wav_path = dest / "sunny-desk.wav"
    samples = render(seed=7)
    with wave.open(str(wav_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<h", int(v * 32767)) for v in samples))
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(wav_path), "-b:a", "128k", str(dest / "sunny-desk.mp3")], check=True)
    wav_path.unlink()


if __name__ == "__main__":
    main()
