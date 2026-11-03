"""Hands-free control: Muse Voice Transcribe turns speech into capture commands.

A technician holding a phone to the eyepiece has no free hand. They hold the talk
button and say "next field", "finish", "retake", or "note ..." followed by an
observation; the phone uploads whatever audio it recorded and the server converts
it to the 16 kHz mono WAV the API needs.

Kiswahili is not on Muse Voice Transcribe's published language list, so the
Kiswahili commands are passed as vocabulary keywords and matched loosely.
"""

from __future__ import annotations

import io
import re
import unicodedata
import wave
from dataclasses import dataclass
from typing import Literal

import numpy as np

#: The API accepts mono 16-bit PCM at 16 or 24 kHz, and at most 10 minutes.
SAMPLE_RATE = 16_000
MAX_SECONDS = 60

VoiceAction = Literal["next", "finish", "retake", "note", "none"]

#: Phrases per action, English then Kiswahili, matched after normalisation.
#: Longer phrases first, so "next field" wins over a bare "next".
PHRASES: dict[VoiceAction, tuple[str, ...]] = {
    "retake": ("retake", "take again", "again", "piga tena", "rudia"),
    "finish": ("finish slide", "finish", "done", "stop counting", "maliza", "imekwisha", "basi"),
    "next": ("next field", "next", "move on", "sehemu inayofuata", "inayofuata", "endelea"),
}
NOTE_WORDS = ("note", "kumbuka", "andika")

#: Vocabulary bias sent with every recording.
KEYWORDS = sorted({p for ps in PHRASES.values() for p in ps} | set(NOTE_WORDS))


@dataclass(frozen=True)
class VoiceCommand:
    """What a transcript asks for; ``note`` holds the text of a spoken note."""

    action: VoiceAction
    transcript: str
    note: str | None = None


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return " ".join(re.sub(r"[^a-z ]+", " ", text.lower()).split())


def parse_command(transcript: str) -> VoiceCommand:
    """Map a transcript to a capture command.

    A note must start with a note word ("note", "kumbuka", "andika"); everything
    after it is kept as spoken. Otherwise the first command phrase found wins.
    """
    words = _normalise(transcript)
    first, _, rest = words.partition(" ")
    if first in NOTE_WORDS:
        # Keep the note as spoken, minus the leading note word and punctuation.
        spoken = re.sub(r"^\W*\w+[\s,:.-]*", "", transcript.strip(), count=1).strip()
        if rest and spoken:
            return VoiceCommand("note", transcript, spoken)
        return VoiceCommand("none", transcript)
    padded = f" {words} "
    hits = [
        (padded.find(f" {p} "), -len(p), action)
        for action, phrases in PHRASES.items()
        for p in phrases
        if f" {p} " in padded
    ]
    if not hits:
        return VoiceCommand("none", transcript)
    return VoiceCommand(min(hits)[2], transcript)


def to_wav(data: bytes) -> bytes:
    """Decode any audio PyAV reads (WAV, M4A, WebM/Opus, ...) to 16 kHz mono WAV.

    Raises ``ValueError`` when there is no audio stream, or it is longer than
    ``MAX_SECONDS``.
    """
    from darubini.video import _av

    av = _av()
    try:
        container = av.open(io.BytesIO(data))
    except Exception as exc:  # PyAV raises many error types for unreadable input
        raise ValueError("not an audio file") from exc
    with container:
        if not container.streams.audio:
            raise ValueError("no audio stream")
        resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        chunks: list[np.ndarray] = []
        total = 0
        for frame in container.decode(audio=0):
            for out in resampler.resample(frame):
                pcm = out.to_ndarray().reshape(-1)
                chunks.append(pcm)
                total += len(pcm)
                if total > MAX_SECONDS * SAMPLE_RATE:
                    raise ValueError(f"recording longer than {MAX_SECONDS} s")
        for out in resampler.resample(None):
            chunks.append(out.to_ndarray().reshape(-1))
    pcm16 = np.concatenate(chunks).astype("<i2") if chunks else np.zeros(0, "<i2")
    if not len(pcm16):
        raise ValueError("empty recording")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm16.tobytes())
    return buf.getvalue()
