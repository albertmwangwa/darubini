"""Synthesise the demo video's narration with Kokoro, an open-weights TTS model (Apache 2.0).

Runs in its own environment, so PyTorch stays out of the project's dependencies:

    python -m venv .venv-tts
    .venv-tts/Scripts/python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
    .venv-tts/Scripts/python -m pip install "kokoro>=0.9" soundfile
    .venv-tts/Scripts/python scripts/narrate.py

Reads docs/demo/narration.json and writes one 24 kHz WAV per line to
datasets/processed/demo/voice/, plus durations.json for the renderer.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro import KPipeline

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "docs" / "demo" / "narration.json"
OUT = ROOT / "datasets" / "processed" / "demo" / "voice"
RATE = 24_000


def main() -> int:
    spec = json.loads(SCRIPT.read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    pipe = KPipeline(lang_code="a")  # American English
    durations = {}
    for i, line in enumerate(spec["lines"]):
        chunks = [
            audio for _, _, audio in pipe(line["text"], voice=spec["voice"], speed=spec["speed"])
        ]
        audio = np.concatenate([np.asarray(a, dtype=np.float32) for a in chunks])
        name = f"{i:02d}_{line['scene']}.wav"
        sf.write(OUT / name, audio, RATE)
        durations[name] = round(len(audio) / RATE, 2)
        print(f"{name}: {durations[name]:.2f} s", flush=True)
    (OUT / "durations.json").write_text(json.dumps(durations, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
