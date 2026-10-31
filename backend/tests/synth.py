"""Render a small original test song with known ground truth.

Writes vocals/bass/other/drums stems plus the mix, so tests can either feed the
stems straight in (perfect separation) or run the full pipeline on the mix.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 44100
BPM = 96.0
LEAD_IN_S = 0.6  # silence before bar 1
G, Em, C, D = (7, "maj"), (4, "min"), (0, "maj"), (2, "maj")
TRIADS = {"maj": (0, 4, 7), "min": (0, 3, 7)}

# Original eight-bar tune over a I-vi-IV-V loop in G major: (MIDI pitch or None for rest, beats).
TUNE = [
    [(71, 1), (74, 1), (74, 0.5), (72, 0.5), (71, 1)],
    [(67, 1.5), (69, 0.5), (71, 1), (67, 1)],
    [(72, 1), (76, 1), (74, 0.5), (72, 0.5), (67, 1)],
    [(69, 2), (66, 1), (None, 1)],
    [(74, 0.5), (74, 0.5), (71, 1), (67, 1), (71, 1)],
    [(76, 1), (74, 1), (71, 2)],
    [(67, 1), (69, 1), (72, 1), (76, 1)],
    [(74, 3), (None, 1)],
]
INTRO = [G, D]
LOOP = [G, Em, C, D]
OUTRO = [G]


@dataclass
class SynthSong:
    mix: Path
    stems_dir: Path
    beat_period: float
    bar_chords: list[tuple[int, str]]  # one chord per bar, bar 1 first
    melody: list[tuple[float, float, int]]  # (start beat, end beat, pitch) from the start of bar 1
    key: tuple[int, str]
    beats_per_bar: int = 4


def render(out_dir: Path) -> SynthSong:
    out_dir.mkdir(parents=True, exist_ok=True)
    period = 60.0 / BPM
    bars = INTRO + LOOP * 4 + OUTRO
    n_beats = len(bars) * 4
    total_s = LEAD_IN_S + n_beats * period + 1.5
    n = int(total_s * SR)
    vocals, bass, other, drums = (np.zeros(n) for _ in range(4))
    rng = np.random.default_rng(7)

    def t0(beat: float) -> int:
        return int((LEAD_IN_S + beat * period) * SR)

    # Accompaniment pad: triads around G3..D4, struck every two beats.
    for bar, (root, quality) in enumerate(bars):
        for half in (0, 2):
            start = bar * 4 + half
            pitches = [48 + ((root + iv - 48) % 12) + (12 if (root + iv) % 12 < 7 else 0) for iv in TRIADS[quality]]
            for p in pitches:
                _add(other, t0(start), _tone(p, 2 * period, harmonics=6, decay=1.2, rng=rng), 0.22)
        # Bass: root on 1, fifth on 3.
        _add(bass, t0(bar * 4), _tone(36 + (root % 12), 2 * period * 0.95, harmonics=4, decay=2.0, rng=rng), 0.5)
        _add(bass, t0(bar * 4 + 2), _tone(36 + ((root + 7) % 12), 2 * period * 0.95, harmonics=4, decay=2.0, rng=rng), 0.45)
        # Drums: kick 1 & 3, snare 2 & 4, closed hat on eighths.
        for beat in range(4):
            if beat in (0, 2):
                _add(drums, t0(bar * 4 + beat), _kick(), 0.9)
            else:
                _add(drums, t0(bar * 4 + beat), _snare(rng), 0.5)
            for e in (0, 0.5):
                _add(drums, t0(bar * 4 + beat + e), _hat(rng), 0.15)

    melody: list[tuple[float, float, int]] = []
    first = len(INTRO) * 4
    for rep in range(2):
        beat = first + rep * 32
        for bar in TUNE:
            for pitch, dur in bar:
                if pitch is not None:
                    melody.append((beat, beat + dur, pitch))
                    _add(vocals, t0(beat), _voice(pitch, dur * period - 0.04), 0.35)
                beat += dur

    mix = 0.9 * vocals + 0.7 * other + 0.8 * bass + 0.6 * drums
    peak = np.max(np.abs(mix)) + 1e-9
    stems_dir = out_dir / "stems"
    stems_dir.mkdir(exist_ok=True)
    for name, sig, gain in (("vocals", vocals, 0.9), ("other", other, 0.7), ("bass", bass, 0.8), ("drums", drums, 0.6)):
        sf.write(str(stems_dir / f"{name}.wav"), np.stack([sig, sig], axis=1) * gain / peak, SR, subtype="PCM_16")
    mix_path = out_dir / "mix.wav"
    stereo = np.stack([mix, mix * 0.98], axis=1) / peak
    sf.write(str(mix_path), stereo, SR, subtype="PCM_16")
    return SynthSong(mix_path, stems_dir, period, bars, melody, (7, "major"))


def _add(buf: np.ndarray, at: int, sig: np.ndarray, gain: float) -> None:
    end = min(len(buf), at + len(sig))
    if end > at:
        buf[at:end] += gain * sig[: end - at]


def _hz(p: float) -> float:
    return 440.0 * 2 ** ((p - 69) / 12)


def _tone(pitch: int, dur: float, harmonics: int, decay: float, rng) -> np.ndarray:
    t = np.arange(int(dur * SR)) / SR
    f = _hz(pitch)
    sig = sum((0.6 ** k) * np.sin(2 * np.pi * f * (k + 1) * t + rng.uniform(0, 2 * np.pi)) for k in range(harmonics))
    env = np.minimum(1.0, t / 0.01) * np.exp(-t * decay)
    env[-int(0.02 * SR):] *= np.linspace(1, 0, int(0.02 * SR))
    return sig * env


def _voice(pitch: int, dur: float) -> np.ndarray:
    t = np.arange(int(max(dur, 0.05) * SR)) / SR
    vib = 0.3 * np.sin(2 * np.pi * 5.5 * t) * np.clip((t - 0.15) / 0.2, 0, 1)  # semitones
    phase = 2 * np.pi * np.cumsum(_hz(pitch) * 2 ** (vib / 12)) / SR
    sig = sum((1.0 / (k + 1)) * np.sin((k + 1) * phase) for k in range(8))
    env = np.minimum(1.0, t / 0.03) * np.minimum(1.0, (t[-1] - t) / 0.05 + 1e-3)
    return sig * env


def _kick() -> np.ndarray:
    t = np.arange(int(0.15 * SR)) / SR
    f = 40 + 80 * np.exp(-t * 30)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 25)


def _snare(rng) -> np.ndarray:
    from scipy.signal import butter, sosfilt

    t = np.arange(int(0.15 * SR)) / SR
    noise = sosfilt(butter(2, [800, 6000], btype="band", fs=SR, output="sos"), rng.standard_normal(len(t)))
    return noise * np.exp(-t * 30)


def _hat(rng) -> np.ndarray:
    from scipy.signal import butter, sosfilt

    t = np.arange(int(0.04 * SR)) / SR
    noise = sosfilt(butter(2, 7000, btype="high", fs=SR, output="sos"), rng.standard_normal(len(t)))
    return noise * np.exp(-t * 80)


if __name__ == "__main__":
    import sys

    target = Path(sys.argv[1] if len(sys.argv) > 1 else "out/song")
    song = render(target)
    print(f"wrote {song.mix} and stems in {song.stems_dir}")
