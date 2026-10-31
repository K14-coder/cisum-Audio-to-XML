"""Stage 3a, rhythm: beats, downbeats and meter.

Backends:
  beat_this  "Beat This!" (MIT), a transformer beat and downbeat tracker. Downloads
             its checkpoint on first use.
  librosa    Dynamic-programming beat tracker plus a downbeat estimate from where
             chords change and where the kick drum lands.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from . import audio

log = logging.getLogger(__name__)
_beat_this_cache: dict[str, object] = {}


def available_backends() -> list[str]:
    out = []
    try:
        import beat_this.inference  # noqa: F401

        out.append("beat_this")
    except Exception:
        pass
    out.append("librosa")
    return out


def track(mix_wav: Path, backend: str = "auto", device: str | None = None) -> tuple[np.ndarray, np.ndarray, str]:
    """Return (beat_times, downbeat_times, backend_name) in seconds."""
    if backend in ("auto", "beat_this"):
        try:
            beats, downbeats = _track_beat_this(mix_wav, device)
            if len(beats) >= 4:
                return beats, downbeats, "beat_this"
            raise RuntimeError("too few beats detected")
        except Exception as e:
            if backend == "beat_this":
                raise
            log.warning("Beat This! unavailable (%s); falling back to librosa", e)
    if backend in ("auto", "librosa"):
        y, sr = audio.load(mix_wav, sr=22050)
        beats, downbeats = _track_librosa(y, sr)
        return beats, downbeats, "librosa"
    raise ValueError(f"unknown beat backend {backend!r}")


def _track_beat_this(mix_wav: Path, device: str | None) -> tuple[np.ndarray, np.ndarray]:
    import torch
    from beat_this.inference import File2Beats

    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    f2b = _beat_this_cache.get(device)
    if f2b is None:
        f2b = File2Beats(checkpoint_path="final0", device=device, dbn=False)
        _beat_this_cache[device] = f2b
    beats, downbeats = f2b(str(mix_wav))
    return np.asarray(beats, dtype=float), np.asarray(downbeats, dtype=float)


def _track_librosa(y: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    import librosa

    hop = 512
    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop, aggregate=np.median)
    _, beat_frames = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr, hop_length=hop, tightness=100)
    beats = librosa.frames_to_time(beat_frames, sr=sr, hop_length=hop)
    if len(beats) < 4:
        return beats, beats[:1]
    downbeats = estimate_downbeats(y, sr, beats)
    return beats, downbeats


def estimate_downbeats(y: np.ndarray, sr: int, beats: np.ndarray) -> np.ndarray:
    """Pick meter (3 or 4) and phase where harmony changes and low-end onsets line up."""
    import librosa

    hop = 512
    frames = librosa.time_to_frames(beats, sr=sr, hop_length=hop)
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop)
    n_frames = chroma.shape[1]
    frames = np.clip(frames, 0, n_frames - 1)
    bounds = np.concatenate([frames, [n_frames]])
    beat_chroma = np.stack(
        [chroma[:, a : max(b, a + 1)].mean(axis=1) for a, b in zip(bounds[:-1], bounds[1:])], axis=1
    )
    beat_chroma /= np.linalg.norm(beat_chroma, axis=0, keepdims=True) + 1e-9
    change = np.zeros(len(beats))
    change[1:] = 1.0 - np.sum(beat_chroma[:, 1:] * beat_chroma[:, :-1], axis=0)

    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=hop))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    low = librosa.onset.onset_strength(S=librosa.amplitude_to_db(S[freqs < 150]), sr=sr, hop_length=hop)
    low_at_beat = low[np.clip(frames, 0, len(low) - 1)]

    def z(x: np.ndarray) -> np.ndarray:
        return (x - x.mean()) / (x.std() + 1e-9)

    feature = z(change) + 0.5 * z(low_at_beat)
    best = (4, 0, -np.inf)
    for meter, prior in ((4, 0.15), (3, 0.0)):
        for phase in range(meter):
            on = feature[phase::meter]
            off = np.delete(feature, np.arange(phase, len(feature), meter))
            if len(on) < 2 or len(off) < 2:
                continue
            score = on.mean() - off.mean() + prior
            if score > best[2]:
                best = (meter, phase, score)
    meter, phase, _ = best
    return beats[phase::meter]
