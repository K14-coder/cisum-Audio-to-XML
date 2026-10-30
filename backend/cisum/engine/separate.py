"""Stage 2, separation: split the mix into vocals, bass, other and drums.

Backends:
  demucs  Hybrid Transformer Demucs (MIT). Best quality; needs torch and downloads
          its weights on first use.
  hpss    Harmonic/percussive split with librosa. No vocals stem, so the melody is
          taken from the accompaniment. Used when Demucs isn't available.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from . import audio

log = logging.getLogger(__name__)

STEM_NAMES = ("vocals", "bass", "other", "drums")
_demucs_cache: dict[str, object] = {}


@dataclass
class Stems:
    mix: Path
    vocals: Path | None
    bass: Path | None
    other: Path | None
    drums: Path | None
    backend: str


def available_backends() -> list[str]:
    out = []
    try:
        import demucs.pretrained  # noqa: F401

        out.append("demucs")
    except Exception:
        pass
    out.append("hpss")
    return out


def separate(mix_wav: Path, out_dir: Path, backend: str = "auto", model: str = "htdemucs", device: str | None = None) -> Stems:
    out_dir.mkdir(parents=True, exist_ok=True)
    if backend in ("auto", "demucs"):
        try:
            return _separate_demucs(mix_wav, out_dir, model, device)
        except Exception as e:
            if backend == "demucs":
                raise
            log.warning("Demucs unavailable (%s); falling back to HPSS", e)
    if backend in ("auto", "hpss"):
        return _separate_hpss(mix_wav, out_dir)
    raise ValueError(f"unknown separation backend {backend!r}")


def stems_from_dir(mix_wav: Path, stems_dir: Path) -> Stems:
    """Use stems that already exist on disk (vocals.wav, bass.wav, ...). For tests and
    for users who separated the song themselves."""
    found = {name: (stems_dir / f"{name}.wav") for name in STEM_NAMES}
    return Stems(
        mix=mix_wav,
        **{name: (p if p.exists() else None) for name, p in found.items()},
        backend="provided",
    )


def _separate_demucs(mix_wav: Path, out_dir: Path, model_name: str, device: str | None) -> Stems:
    import torch
    from demucs.apply import apply_model
    from demucs.pretrained import get_model

    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    model = _demucs_cache.get(model_name)
    if model is None:
        model = get_model(model_name)
        model.eval()
        _demucs_cache[model_name] = model

    y, sr = audio.load(mix_wav, sr=model.samplerate, mono=False)
    if y.shape[0] == 1:
        y = np.repeat(y, 2, axis=0)
    wav = torch.from_numpy(y[: model.audio_channels])
    ref = wav.mean(0)
    mean, std = ref.mean(), ref.std() + 1e-8
    with torch.no_grad():
        sources = apply_model(
            model, ((wav - mean) / std)[None], device=device, shifts=1, split=True, overlap=0.25, progress=False
        )[0]
    sources = sources * std + mean

    paths: dict[str, Path] = {}
    for name, source in zip(model.sources, sources):
        p = out_dir / f"{name}.wav"
        sf.write(str(p), source.cpu().numpy().T, sr, subtype="PCM_16")
        paths[name] = p
    return Stems(
        mix=mix_wav,
        vocals=paths.get("vocals"),
        bass=paths.get("bass"),
        other=paths.get("other"),
        drums=paths.get("drums"),
        backend=f"demucs:{model_name}",
    )


def _separate_hpss(mix_wav: Path, out_dir: Path) -> Stems:
    import librosa
    from scipy.signal import butter, sosfiltfilt

    y, sr = audio.load(mix_wav, mono=True)
    harmonic, percussive = librosa.effects.hpss(y, margin=(1.0, 3.0))
    sos = butter(6, 220.0, btype="lowpass", fs=sr, output="sos")
    bass = sosfiltfilt(sos, harmonic).astype(np.float32)

    paths = {}
    for name, sig in (("other", harmonic), ("bass", bass), ("drums", percussive)):
        p = out_dir / f"{name}.wav"
        sf.write(str(p), sig, sr, subtype="PCM_16")
        paths[name] = p
    return Stems(mix=mix_wav, vocals=None, bass=paths["bass"], other=paths["other"], drums=paths["drums"], backend="hpss")
