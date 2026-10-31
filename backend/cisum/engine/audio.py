"""Stage 1, ingest: check the upload is real audio, decode it, measure tuning."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

SAMPLE_RATE = 44100


class AudioError(Exception):
    """A problem with the user's file. `code` is stable and shown to clients."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class AudioInfo:
    duration_s: float
    codec: str
    sample_rate: int
    channels: int


def probe(path: str | Path) -> AudioInfo:
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError as e:  # pragma: no cover - deployment problem
        raise RuntimeError("ffprobe is not installed") from e
    if proc.returncode != 0:
        raise AudioError("not_audio", "This file couldn't be read as audio.")
    info = json.loads(proc.stdout or "{}")
    audio = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    if not audio:
        raise AudioError("not_audio", "This file doesn't contain any audio.")
    stream = audio[0]
    duration = stream.get("duration") or info.get("format", {}).get("duration")
    try:
        duration_s = float(duration)
    except (TypeError, ValueError):
        duration_s = 0.0
    return AudioInfo(
        duration_s=duration_s,
        codec=str(stream.get("codec_name", "unknown")),
        sample_rate=int(stream.get("sample_rate") or 0),
        channels=int(stream.get("channels") or 0),
    )


def decode(src: str | Path, dst: str | Path, normalize: bool = True) -> Path:
    """Decode any input to a 44.1 kHz stereo 16-bit WAV, optionally loudness-normalized."""
    dst = Path(dst)
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src), "-vn"]
    if normalize:
        cmd += ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]
    cmd += ["-ac", "2", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", str(dst)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0 or not dst.exists():
        raise AudioError("decode_failed", "This audio file couldn't be decoded.")
    return dst


def load(path: str | Path, sr: int | None = None, mono: bool = True) -> tuple[np.ndarray, int]:
    """Load audio as float32. Mono returns shape (n,), stereo (channels, n)."""
    data, file_sr = sf.read(str(path), dtype="float32", always_2d=True)
    y = data.T  # (channels, n)
    if mono:
        y = y.mean(axis=0)
    if sr is not None and sr != file_sr:
        import librosa

        y = librosa.resample(y, orig_sr=file_sr, target_sr=sr)
        file_sr = sr
    return np.ascontiguousarray(y, dtype=np.float32), file_sr


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_not_silent(y: np.ndarray) -> None:
    if y.size == 0 or float(np.sqrt(np.mean(np.square(y)))) < 1e-4:
        raise AudioError("silent", "This recording is silent.")


def estimate_tuning_cents(y: np.ndarray, sr: int) -> float:
    """How far the recording sits from A440, in cents (-50..50)."""
    import librosa

    # Ten seconds from the middle is plenty and keeps this fast on long songs.
    n = len(y)
    span = min(n, sr * 20)
    mid = y[(n - span) // 2 : (n + span) // 2]
    try:
        return float(librosa.estimate_tuning(y=mid, sr=sr)) * 100.0
    except Exception:
        return 0.0
