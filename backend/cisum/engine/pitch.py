"""Stage 3b, melody: track the pitch of a monophonic stem and cut it into notes.

Backends:
  crepe  torchcrepe (MIT), a neural pitch tracker. Weights ship with the package.
  pyin   Probabilistic YIN from librosa. Slower and less robust, no extra installs.

The same segmentation turns either pitch curve into notes, so it is also used for
the bass line when no note transcriber is installed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import audio
from .types import NoteEvent

log = logging.getLogger(__name__)


@dataclass
class F0Track:
    times: np.ndarray  # seconds, frame centers
    midi: np.ndarray  # fractional MIDI pitch, nan where unvoiced
    confidence: np.ndarray  # 0..1
    hop_s: float


def available_backends() -> list[str]:
    out = []
    try:
        import torchcrepe  # noqa: F401

        out.append("crepe")
    except Exception:
        pass
    out.append("pyin")
    return out


def track(
    path: Path,
    backend: str = "auto",
    fmin: float = 65.0,
    fmax: float = 1400.0,
    device: str | None = None,
    crepe_model: str | None = None,
) -> tuple[F0Track, str]:
    if backend in ("auto", "crepe"):
        try:
            return _track_crepe(path, fmin, fmax, device, crepe_model)
        except Exception as e:
            if backend == "crepe":
                raise
            log.warning("torchcrepe unavailable (%s); falling back to pYIN", e)
    if backend in ("auto", "pyin"):
        return _track_pyin(path, fmin, fmax), "pyin"
    raise ValueError(f"unknown pitch backend {backend!r}")


def _track_crepe(path: Path, fmin: float, fmax: float, device: str | None, model: str | None) -> tuple[F0Track, str]:
    import torch
    import torchcrepe

    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    if model is None:
        model = "full" if device.startswith("cuda") else "tiny"
    sr, hop = 16000, 160
    y, _ = audio.load(path, sr=sr)
    x = torch.from_numpy(y)[None]
    with torch.no_grad():
        pitch, periodicity = torchcrepe.predict(
            x,
            sr,
            hop,
            fmin,
            fmax,
            model=model,
            decoder=torchcrepe.decode.viterbi,
            return_periodicity=True,
            batch_size=1024,
            device=device,
            pad=True,
        )
    periodicity = torchcrepe.filter.median(periodicity, 3)
    pitch = torchcrepe.filter.mean(pitch, 3)
    hz = pitch[0].cpu().numpy().astype(float)
    conf = periodicity[0].cpu().numpy().astype(float)
    conf[_quiet_frames(y, hop, len(conf))] = 0.0
    with np.errstate(divide="ignore", invalid="ignore"):
        midi = 69.0 + 12.0 * np.log2(hz / 440.0)
    midi[~np.isfinite(midi)] = np.nan
    times = np.arange(len(hz)) * hop / sr
    return F0Track(times, midi, np.nan_to_num(conf), hop / sr), f"crepe:{model}"


def _quiet_frames(y: np.ndarray, hop: int, n_frames: int, floor_db: float = 40.0) -> np.ndarray:
    """Frames more than `floor_db` below the stem's loud passages. Relative to the
    stem itself because separated stems come out at very different levels."""
    import librosa

    rms = librosa.feature.rms(y=y, frame_length=4 * hop, hop_length=hop, center=True)[0]
    rms = np.pad(rms, (0, max(0, n_frames - len(rms))), mode="edge")[:n_frames]
    db = 20 * np.log10(rms + 1e-9)
    loud = np.percentile(db, 95)
    return db < loud - floor_db


def _track_pyin(path: Path, fmin: float, fmax: float) -> F0Track:
    import librosa

    sr, hop = 22050, 256
    y, _ = audio.load(path, sr=sr)
    f0, voiced, prob = librosa.pyin(y, fmin=fmin, fmax=fmax, sr=sr, frame_length=2048, hop_length=hop)
    with np.errstate(divide="ignore", invalid="ignore"):
        midi = 69.0 + 12.0 * np.log2(f0 / 440.0)
    midi[~voiced] = np.nan
    times = librosa.frames_to_time(np.arange(len(f0)), sr=sr, hop_length=hop)
    conf = np.where(voiced, np.nan_to_num(prob), 0.0)
    return F0Track(times, midi, conf, hop / sr)


def detect_onsets(path: Path, dip_ratio: float = 0.5) -> np.ndarray:
    """Re-attacks in a vocal stem: onsets preceded by a clear dip in loudness (a new
    syllable), not the wobble that vibrato causes in spectral flux."""
    import librosa

    y, sr = audio.load(path, sr=22050)
    hop = 220
    candidates = librosa.onset.onset_detect(y=y, sr=sr, hop_length=hop, units="time", backtrack=False)
    rms = librosa.feature.rms(y=y, frame_length=1024, hop_length=hop, center=True)[0]
    times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop)
    keep = []
    for t in candidates:
        before = rms[(times >= t - 0.07) & (times <= t + 0.01)]
        after = rms[(times >= t + 0.02) & (times <= t + 0.15)]
        if len(before) and len(after) and before.min() < dip_ratio * np.median(after):
            keep.append(t)
    return np.array(keep)


def segment_notes(
    f0: F0Track,
    tuning_cents: float = 0.0,
    onsets: np.ndarray | None = None,
    conf_threshold: float = 0.5,
    min_note_s: float = 0.08,
    min_segment_s: float = 0.09,
    hysteresis: float = 0.7,
    smooth_s: float = 0.07,
) -> list[NoteEvent]:
    """Turn a pitch curve into discrete notes.

    1. Keep confident frames, correct tuning, median-smooth each voiced run.
    2. Quantize to semitones with hysteresis so vibrato doesn't flicker between notes.
    3. Absorb segments shorter than `min_segment_s` into their closest neighbour.
    4. Split held notes at onsets (a re-sung syllable on the same pitch).
    """
    from scipy.ndimage import median_filter

    midi = f0.midi - tuning_cents / 100.0
    voiced = np.isfinite(midi) & (f0.confidence >= conf_threshold)
    hop = f0.hop_s
    kernel = max(1, int(round(smooth_s / hop)) | 1)
    min_seg = max(1, int(round(min_segment_s / hop)))

    notes: list[NoteEvent] = []
    for start, end in _runs(voiced):
        seg = midi[start:end]
        if len(seg) >= kernel:
            seg = median_filter(seg, size=kernel, mode="nearest")
        q = _hysteresis_round(seg, hysteresis)
        pieces = _rle(q)
        pieces = _absorb_short(pieces, seg, min_seg)
        for a, b, _ in pieces:
            pitch = int(round(float(np.median(seg[a:b]))))
            conf = float(np.mean(f0.confidence[start + a : start + b]))
            t0 = f0.times[start + a]
            t1 = f0.times[start + b - 1] + hop
            notes.append(NoteEvent(float(t0), float(t1), pitch, conf))

    notes = _merge_same_pitch(notes, gap_s=0.03)
    if onsets is not None and len(onsets):
        notes = _split_at_onsets(notes, onsets, min_note_s)
    return [n for n in notes if n.duration >= min_note_s]


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    padded = np.concatenate([[False], mask, [False]])
    d = np.diff(padded.astype(int))
    starts = np.flatnonzero(d == 1)
    ends = np.flatnonzero(d == -1)
    return list(zip(starts.tolist(), ends.tolist()))


def _hysteresis_round(x: np.ndarray, width: float) -> np.ndarray:
    out = np.empty(len(x), dtype=int)
    current = int(round(float(x[0])))
    for i, v in enumerate(x):
        if abs(v - current) > width:
            current = int(round(float(v)))
        out[i] = current
    return out


def _rle(q: np.ndarray) -> list[list[int]]:
    pieces: list[list[int]] = []
    start = 0
    for i in range(1, len(q) + 1):
        if i == len(q) or q[i] != q[start]:
            pieces.append([start, i, int(q[start])])
            start = i
    return pieces


def _absorb_short(pieces: list[list[int]], seg: np.ndarray, min_len: int) -> list[list[int]]:
    pieces = [p[:] for p in pieces]
    while len(pieces) > 1:
        lengths = [b - a for a, b, _ in pieces]
        i = int(np.argmin(lengths))
        if lengths[i] >= min_len:
            break
        a, b, p = pieces[i]
        candidates = []
        if i > 0:
            candidates.append((abs(pieces[i - 1][2] - p), 0, i - 1))
        if i + 1 < len(pieces):
            candidates.append((abs(pieces[i + 1][2] - p), 1, i + 1))
        _, _, j = min(candidates)
        if j < i:
            pieces[j][1] = b
        else:
            pieces[j][0] = a
        del pieces[i]
        # Neighbours that now share a pitch become one note.
        merged: list[list[int]] = []
        for piece in pieces:
            if merged and merged[-1][2] == piece[2] and merged[-1][1] == piece[0]:
                merged[-1][1] = piece[1]
            else:
                merged.append(piece)
        pieces = merged
    if len(pieces) == 1 and pieces[0][1] - pieces[0][0] < min_len:
        return []
    return pieces


def _merge_same_pitch(notes: list[NoteEvent], gap_s: float) -> list[NoteEvent]:
    out: list[NoteEvent] = []
    for n in sorted(notes, key=lambda n: n.start):
        if out and out[-1].pitch == n.pitch and n.start - out[-1].end <= gap_s:
            prev = out[-1]
            total = prev.duration + n.duration
            prev.confidence = (prev.confidence * prev.duration + n.confidence * n.duration) / max(total, 1e-9)
            prev.end = max(prev.end, n.end)
        else:
            out.append(NoteEvent(n.start, n.end, n.pitch, n.confidence, n.velocity))
    return out


def _split_at_onsets(notes: list[NoteEvent], onsets: np.ndarray, min_note_s: float) -> list[NoteEvent]:
    out: list[NoteEvent] = []
    for n in notes:
        cuts = [t for t in onsets if n.start + min_note_s < t < n.end - min_note_s]
        start = n.start
        for t in cuts:
            if t - start >= min_note_s:
                out.append(NoteEvent(start, float(t), n.pitch, n.confidence, n.velocity))
                start = float(t)
        out.append(NoteEvent(start, n.end, n.pitch, n.confidence, n.velocity))
    return out


def monophonic_low(notes: list[NoteEvent], min_note_s: float = 0.06) -> list[NoteEvent]:
    """Keep the lowest sounding note at every moment (the bass line from a polyphonic transcription)."""
    return _skyline(notes, lowest=True, min_note_s=min_note_s)


def monophonic_high(notes: list[NoteEvent], min_note_s: float = 0.06) -> list[NoteEvent]:
    """Keep the highest sounding note at every moment (the "skyline" melody)."""
    return _skyline(notes, lowest=False, min_note_s=min_note_s)


def melody_from_polyphony(notes: list[NoteEvent], low: int = 55, high: int = 96, min_note_s: float = 0.08) -> list[NoteEvent]:
    """Best-effort melody from a polyphonic transcription when there's no vocal stem.

    Transcribers often report a sung note's overtone an octave up as a second note,
    and the plain skyline then jumps between octaves. Drop those duplicates, take the
    top line, then pull isolated octave jumps back toward the surrounding line.
    """
    band = [n for n in notes if low <= n.pitch <= high and n.duration >= min_note_s]
    band = drop_octave_duplicates(band)
    return smooth_octaves(_skyline(band, lowest=False, min_note_s=min_note_s))


def drop_octave_duplicates(notes: list[NoteEvent], overlap: float = 0.6) -> list[NoteEvent]:
    by_pitch: dict[int, list[NoteEvent]] = {}
    for n in notes:
        by_pitch.setdefault(n.pitch, []).append(n)
    keep = []
    for n in notes:
        doubled = False
        for interval in (12, 19, 24):  # octave, octave + fifth, two octaves
            for m in by_pitch.get(n.pitch - interval, []):
                shared = min(n.end, m.end) - max(n.start, m.start)
                if shared >= overlap * n.duration and m.velocity >= 0.5 * n.velocity:
                    doubled = True
                    break
            if doubled:
                break
        if not doubled:
            keep.append(n)
    return keep


def smooth_octaves(line: list[NoteEvent], window: int = 4, max_jump: int = 7) -> list[NoteEvent]:
    """Move notes by octaves when they sit far from the median of their neighbours."""
    if len(line) < 3:
        return line
    original = [n.pitch for n in line]
    out = []
    for i, n in enumerate(line):
        neighbours = original[max(0, i - window) : i] + original[i + 1 : i + 1 + window]
        center = float(np.median(neighbours))
        p = n.pitch
        while p - center > max_jump and p - 12 >= 0:
            p -= 12
        while center - p > max_jump:
            p += 12
        out.append(NoteEvent(n.start, n.end, p, n.confidence, n.velocity))
    return out


def _skyline(notes: list[NoteEvent], lowest: bool, min_note_s: float) -> list[NoteEvent]:
    if not notes:
        return []
    # Sweep over start/end points; ends sort before starts at the same instant.
    points = sorted(
        [(n.start, 1, i) for i, n in enumerate(notes)] + [(n.end, 0, i) for i, n in enumerate(notes)],
        key=lambda p: (p[0], p[1]),
    )
    active: set[int] = set()
    out: list[NoteEvent] = []
    last_idx = -1
    prev_t: float | None = None
    for t, kind, i in points:
        if prev_t is not None and t > prev_t and active:
            pick_idx = (min if lowest else max)(active, key=lambda j: (notes[j].pitch, -j if lowest else j))
            pick = notes[pick_idx]
            if out and pick_idx == last_idx and abs(out[-1].end - prev_t) < 1e-9:
                out[-1].end = t  # same note continuing
            else:
                out.append(NoteEvent(prev_t, t, pick.pitch, pick.confidence, pick.velocity))
                last_idx = pick_idx
        if kind == 1:
            active.add(i)
        else:
            active.discard(i)
        prev_t = t
    return [n for n in out if n.duration >= min_note_s]
