"""Stage 3: run every analysis step on the stems and assemble the song model."""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from . import audio, beats as beats_mod, chords as chords_mod, keydetect, pitch, transcribe
from .separate import Stems
from .timing import BeatGrid
from .types import Analysis, ChordSegment, KeySegment, Note, NoteEvent

log = logging.getLogger(__name__)

Progress = Callable[[float, str], None]

MELODY_MIN_PITCH = 55  # G3: the accompaniment's top line below this isn't a usable melody


@dataclass
class AnalyzeOptions:
    beats: str = "auto"  # auto | beat_this | librosa
    melody: str = "auto"  # auto | crepe | pyin
    notes: str = "auto"  # auto | basic_pitch | none
    device: str | None = None
    crepe_model: str | None = None  # full | tiny (default: full on GPU, tiny on CPU)


def analyze(stems: Stems, options: AnalyzeOptions | None = None, progress: Progress | None = None) -> Analysis:
    options = options or AnalyzeOptions()
    report = progress or (lambda f, m: None)
    backends: dict[str, str] = {"separation": stems.backend}

    mix, sr = audio.load(stems.mix, sr=22050)
    audio.check_not_silent(mix)
    duration = len(mix) / sr
    harmonic_src = stems.other or stems.mix
    harmonic, _ = audio.load(harmonic_src, sr=22050)
    tuning = audio.estimate_tuning_cents(harmonic, 22050)

    report(0.05, "Finding the beat…")
    beat_times, downbeat_times, backends["beats"] = beats_mod.track(stems.mix, options.beats, options.device)
    grid = BeatGrid.from_tracking(beat_times, downbeat_times, duration)
    bpb = grid.beats_per_bar
    n_beats = grid.n_beats - 1

    report(0.2, "Listening to the accompaniment…")
    use_bp = options.notes in ("auto", "basic_pitch") and transcribe.available()
    if options.notes == "basic_pitch" and not use_bp:
        raise RuntimeError("Basic Pitch was requested but isn't installed")
    other_s: list[NoteEvent] = []
    bass_s: list[NoteEvent] = []
    if use_bp:
        backends["notes"] = "basic_pitch"
        if stems.other:
            other_s = transcribe.transcribe(stems.other, min_freq=60.0)
        report(0.35, "Following the bass line…")
        if stems.bass:
            bass_s = pitch.monophonic_low(transcribe.transcribe(stems.bass, max_freq=420.0, onset_threshold=0.4))
    else:
        backends["notes"] = "none"
        report(0.35, "Following the bass line…")
        if stems.bass:
            f0, name = pitch.track(stems.bass, options.melody, fmin=30.0, fmax=420.0, device=options.device, crepe_model=options.crepe_model)
            bass_s = pitch.segment_notes(f0, tuning, conf_threshold=0.4, min_note_s=0.1)
            backends["bass"] = name

    report(0.5, "Listening to the melody…")
    melody_s: list[NoteEvent] = []
    melody_source = "none"
    if stems.vocals:
        f0, backends["melody"] = pitch.track(
            stems.vocals, options.melody, fmin=65.0, fmax=1400.0, device=options.device, crepe_model=options.crepe_model
        )
        onsets = pitch.detect_onsets(stems.vocals)
        melody_s = pitch.segment_notes(f0, tuning, onsets=onsets)
        sung = sum(n.duration for n in melody_s)
        if sung >= 0.08 * duration and len(melody_s) >= 8:
            melody_source = "vocals"
        else:
            melody_s = []
    accompaniment_top = pitch.melody_from_polyphony(other_s, low=MELODY_MIN_PITCH)
    if melody_source == "none" and accompaniment_top:
        melody_s, melody_source = accompaniment_top, "accompaniment"
        backends.setdefault("melody", "skyline")
    fill_s = accompaniment_top if melody_source == "vocals" else []

    def to_beats(events: list[NoteEvent]) -> list[Note]:
        if not events:
            return []
        starts = grid.to_beats(np.array([e.start for e in events]))
        ends = grid.to_beats(np.array([e.end for e in events]))
        return [Note(float(s), float(e), ev.pitch, ev.confidence) for s, e, ev in zip(starts, ends, events) if e > s]

    melody, bass, fill, other = to_beats(melody_s), to_beats(bass_s), to_beats(fill_s), to_beats(other_s)

    report(0.75, "Working out the chords and key…")
    if other or bass:
        pc = chords_mod.profiles_from_notes([(other, 1.0), (bass, 1.2)], n_beats)
        bass_pc = chords_mod.profiles_from_notes([(bass, 1.0)], n_beats) if bass else None
        backends["chords"] = "templates:notes"
    else:
        pc, bass_pc = _chroma_profiles(stems, grid, n_beats, tuning)
        backends["chords"] = "templates:chroma"

    key_pc = pc + chords_mod.profiles_from_notes([(melody, 0.7)], n_beats)
    tonic_hint = _tonic_hint(bass_pc if bass_pc is not None else pc, bpb)
    keys = keydetect.detect(key_pc, bpb, tonic_hint)
    backends["key"] = "krumhansl"
    key_for_beat = []
    ki = 0
    for t in range(n_beats):
        while ki + 1 < len(keys) and keys[ki + 1].start <= t:
            ki += 1
        key_for_beat.append(keys[ki].key)
    chord_segments = chords_mod.recognize(pc, bass_pc, bpb, key_for_beat)

    melody_conf = float(np.mean([n.confidence for n in melody])) if melody else 0.0
    analysis = Analysis(
        duration_s=duration,
        tuning_cents=tuning,
        beats_per_bar=bpb,
        beat_times=grid.beat_times.tolist(),
        total_beats=n_beats,
        key=keys,
        chords=chord_segments,
        melody=melody,
        bass=bass,
        fill=fill,
        flags={
            "has_vocals": melody_source == "vocals",
            "melody_source": melody_source,
            "low_confidence_melody": melody_source == "none" or melody_conf < 0.5,
        },
        backends=backends,
    )
    report(0.95, "Tidying up…")
    return trim_empty_bars(analysis)


def _chroma_profiles(stems: Stems, grid: BeatGrid, n_beats: int, tuning: float) -> tuple[np.ndarray, np.ndarray | None]:
    import librosa

    hop = 512
    y, sr = audio.load(stems.other or stems.mix, sr=22050)
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop, tuning=tuning / 100.0)
    frame_beats = grid.to_beats(librosa.frames_to_time(np.arange(chroma.shape[1]), sr=sr, hop_length=hop))
    # Weight frames by loudness so silence doesn't count as a chord.
    rms = librosa.feature.rms(y=y, hop_length=hop)[0][: chroma.shape[1]]
    pc = chords_mod.profiles_from_chroma(chroma * rms[None, :], frame_beats, n_beats)
    bass_pc = None
    if stems.bass:
        yb, _ = audio.load(stems.bass, sr=22050)
        cb = librosa.feature.chroma_cqt(
            y=yb, sr=sr, hop_length=hop, fmin=librosa.note_to_hz("C1"), n_octaves=3, tuning=tuning / 100.0
        )
        rb = librosa.feature.rms(y=yb, hop_length=hop)[0][: cb.shape[1]]
        fb = grid.to_beats(librosa.frames_to_time(np.arange(cb.shape[1]), sr=sr, hop_length=hop))
        bass_pc = chords_mod.profiles_from_chroma(cb * rb[None, :], fb, n_beats)
    return pc, bass_pc


def _tonic_hint(pc: np.ndarray, bpb: int) -> np.ndarray:
    """Pitch classes of the first and last two bars that contain anything."""
    energy = pc.sum(axis=1)
    active = np.flatnonzero(energy > 1e-6)
    if len(active) == 0:
        return np.zeros(12)
    first, last = active[0], active[-1]
    span = 2 * bpb
    return pc[first : first + span].sum(axis=0) + pc[max(0, last - span + 1) : last + 1].sum(axis=0)


def trim_empty_bars(a: Analysis) -> Analysis:
    """Drop silent bars at the start and end so the score starts with music."""
    bpb = a.beats_per_bar
    starts = [n.start for n in a.melody + a.bass + a.fill] + [c.start for c in a.chords if c.label.root is not None]
    ends = [n.end for n in a.melody + a.bass + a.fill] + [c.end for c in a.chords if c.label.root is not None]
    if not starts:
        return a
    # Detections often land a little before the beat; a quarter beat of slack keeps
    # a note at 3.9 from opening an empty bar.
    first_bar = max(0, int(math.floor((min(starts) + 0.25) / bpb)))
    shift = first_bar * bpb
    last_beat = max(ends) - shift
    total = int(math.ceil((last_beat - 0.25) / bpb)) * bpb
    total = max(bpb, min(total, len(a.beat_times) - 1 - shift))

    def move(notes: list[Note]) -> list[Note]:
        out = []
        for n in notes:
            s, e = n.start - shift, min(n.end - shift, total)
            if e > max(s, 0.0):
                out.append(Note(max(s, 0.0), e, n.pitch, n.confidence))
        return out

    chords = []
    for c in a.chords:
        s, e = max(0.0, c.start - shift), min(float(total), c.end - shift)
        if e > s:
            chords.append(ChordSegment(s, e, c.label, c.confidence, c.edited))
    if chords and chords[-1].end < total:
        chords[-1].end = float(total)
    keys = []
    for k in a.key:
        s = max(0.0, k.start - shift)
        if s >= total:
            continue
        if keys and keys[-1].start == s:
            keys[-1] = KeySegment(s, k.key, k.confidence)  # the later key is the one in force at s
        else:
            keys.append(KeySegment(s, k.key, k.confidence))
    if not keys:
        keys = [KeySegment(0.0, a.key[-1].key, a.key[-1].confidence)]
    keys[0].start = 0.0

    return Analysis(
        duration_s=a.duration_s,
        tuning_cents=a.tuning_cents,
        beats_per_bar=bpb,
        beat_unit=a.beat_unit,
        beat_times=a.beat_times[shift:],
        total_beats=total,
        key=keys,
        chords=chords_mod.merge_adjacent(chords),
        melody=move(a.melody),
        bass=move(a.bass),
        fill=move(a.fill),
        version=a.version,
        flags=a.flags,
        backends=a.backends,
    )
