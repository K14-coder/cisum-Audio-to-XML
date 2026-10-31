"""Fast tests for the analysis and arrangement building blocks (no audio models)."""

from fractions import Fraction as F

import numpy as np
import pytest

from cisum.engine import chords, keydetect
from cisum.engine.arrange import LEVEL_SPECS, arrange
from cisum.engine.notate import decompose
from cisum.engine.pitch import F0Track, monophonic_high, segment_notes
from cisum.engine.theory import ChordLabel, Key
from cisum.engine.timing import BeatGrid
from cisum.engine.types import Analysis, ChordSegment, KeySegment, Note, NoteEvent


# ---------------------------------------------------------------- beat grid

def test_grid_pads_pickup_and_fills_dropouts():
    period = 0.5
    true_beats = np.arange(1.0, 20.0, period)
    downbeats = true_beats[1::4]  # the first tracked beat is a pickup
    beats = np.delete(true_beats, [10, 11])  # tracker dropped two beats
    grid = BeatGrid.from_tracking(beats, downbeats, duration=21.0)
    assert grid.beats_per_bar == 4
    assert np.allclose(np.diff(grid.beat_times), period)
    # Beat 0 is a downbeat: the tracked downbeat at t=1.5 sits on a multiple of 4.
    b = float(grid.to_beats(1.5))
    assert abs(b - round(b)) < 1e-6 and round(b) % 4 == 0
    assert grid.beat_times[0] <= 0.0 and grid.beat_times[-1] >= 21.0
    assert (grid.n_beats - 1) % 4 == 0


def test_grid_round_trip():
    grid = BeatGrid(np.array([0.0, 0.5, 1.1, 1.6, 2.0]), 4)
    x = np.array([0.25, 0.8, 1.9])
    assert np.allclose(grid.to_seconds(grid.to_beats(x)), x)


def test_three_four_meter():
    beats = np.arange(0.0, 30.0, 0.5)
    grid = BeatGrid.from_tracking(beats, beats[::3], duration=30.0)
    assert grid.beats_per_bar == 3


# ---------------------------------------------------------------- melody segmentation

def test_segmentation_ignores_vibrato_and_splits_repeated_notes():
    hop = 0.01
    t = np.arange(0, 2.0, hop)
    midi = np.where(t < 1.0, 69.0, 72.0) + 0.35 * np.sin(2 * np.pi * 5.5 * t)
    midi[(t > 0.98) & (t < 1.02)] = np.nan  # short break between notes
    conf = np.where(np.isnan(midi), 0.0, 0.9)
    notes = segment_notes(F0Track(t, midi, conf, hop), onsets=np.array([0.5]))
    assert [n.pitch for n in notes] == [69, 69, 72]
    assert abs(notes[1].start - 0.5) < 0.02


def test_segmentation_corrects_tuning():
    hop = 0.01
    t = np.arange(0, 1.0, hop)
    midi = np.full_like(t, 69.45)  # 45 cents sharp
    notes = segment_notes(F0Track(t, midi, np.full_like(t, 0.9), hop), tuning_cents=45.0)
    assert [n.pitch for n in notes] == [69]


def test_skyline_keeps_top_line():
    notes = [NoteEvent(0, 2, 60), NoteEvent(0, 1, 67), NoteEvent(1, 2, 64)]
    line = monophonic_high(notes)
    assert [(n.start, n.end, n.pitch) for n in line] == [(0, 1, 67), (1, 2, 64)]


# ---------------------------------------------------------------- chords and key

def _triad_profile(root, minor=False):
    v = np.zeros(12)
    for iv in (0, 3 if minor else 4, 7):
        v[(root + iv) % 12] = 1.0
    return v


def test_chord_recognition_on_profiles():
    seq = [(7, False), (4, True), (0, False), (2, False)] * 2  # G Em C D
    pc = np.concatenate([np.tile(_triad_profile(r, m), (4, 1)) for r, m in seq])
    pc += 0.05 * np.random.default_rng(0).random(pc.shape)
    pc[5, 9] += 0.8  # a passing note mid-bar shouldn't become a chord change
    bass = np.zeros_like(pc)
    for i, (r, _) in enumerate(seq):
        bass[i * 4 : i * 4 + 4, r] = 1.0
    segs = chords.recognize(pc, bass, 4, [Key(7, "major")] * len(pc))
    symbols = [s.label.symbol(Key(7, "major")) for s in segs]
    assert symbols == ["G", "Em", "C", "D", "G", "Em", "C", "D"]
    assert all(s.start % 4 == 0 for s in segs)


def test_silence_is_no_chord():
    pc = np.zeros((8, 12))
    pc[4:] = _triad_profile(0)
    segs = chords.recognize(pc, None, 4)
    assert segs[0].label.is_none and segs[-1].label == ChordLabel(0, "maj")


def test_key_detection():
    pc = np.zeros((64, 12))
    for i in range(64):
        root = [7, 4, 0, 2][(i // 4) % 4]
        pc[i] = _triad_profile(root, minor=(root == 4))
    keys = keydetect.detect(pc, 4)
    assert keys[0].key == Key(7, "major")


# ---------------------------------------------------------------- arrangement

def _analysis() -> Analysis:
    bpb = 4
    prog = [ChordLabel(7, "maj"), ChordLabel(4, "min"), ChordLabel(0, "maj"), ChordLabel(2, "maj", 6)]
    chord_segs = [ChordSegment(i * 4.0, i * 4.0 + 4, prog[i % 4], 0.9) for i in range(8)]
    rng = np.random.default_rng(1)
    melody = []
    beat = 8.0  # two bars of intro
    while beat < 30:
        dur = float(rng.choice([0.5, 1.0, 1.5]))
        melody.append(Note(beat + float(rng.normal(0, 0.05)), beat + dur - 0.05, int(rng.choice([67, 69, 71, 72, 74, 76])), 0.9))
        beat += dur
    return Analysis(
        duration_s=20.0,
        tuning_cents=0.0,
        beats_per_bar=bpb,
        beat_times=[i * 0.6 for i in range(34)],
        total_beats=32,
        key=[KeySegment(0.0, Key(2, "major"))],
        chords=chord_segs,
        melody=melody,
        bass=[Note(i * 4.0, i * 4.0 + 2, 43, 0.9) for i in range(8)],
        fill=[],
    )


@pytest.mark.parametrize("level", ["easy", "medium", "hard"])
def test_arrangement_is_playable(level):
    a = _analysis()
    score = arrange(a, level, None, "T")
    spec = LEVEL_SPECS[level]
    assert score.total_beats % score.beats_per_bar == 0
    for hand, max_notes in (("rh", spec.rh_max_notes), ("lh", spec.lh_max_notes)):
        events = score.hand(hand)
        assert events, hand
        for prev, ev in zip(events, events[1:]):
            assert prev.end <= ev.start, "a hand never overlaps itself"
        for ev in events:
            assert 1 <= len(ev.pitches) <= max_notes
            assert max(ev.pitches) - min(ev.pitches) <= spec.hand_span
            assert ev.duration > 0
    rh = score.hand("rh")
    for ev in score.hand("lh"):
        overlapping = [r for r in rh if r.start < ev.end and r.end > ev.start]
        if overlapping:
            assert max(ev.pitches) < min(min(r.pitches) for r in overlapping), "left hand stays below the right"


def test_easy_uses_eighth_grid_and_easy_key():
    score = arrange(_analysis(), "easy", None, "T")
    assert score.key.accidentals <= 1
    for ev in score.hand("rh"):
        assert (ev.start * 2).denominator == 1


def test_explicit_transpose_and_slash_chord():
    score = arrange(_analysis(), "medium", 2, "T")
    assert score.transpose == 2
    assert score.key == Key(4, "major")
    symbols = [c.label.symbol(score.key) for c in score.chords]
    assert symbols[:4] == ["A", "F#m", "D", "E/G#"]


def test_rh_fills_intro():
    score = arrange(_analysis(), "medium", 0, "T")
    assert any(ev.start < 8 for ev in score.hand("rh")), "the two-bar intro gets right-hand chords"


# ---------------------------------------------------------------- rhythm spelling

@pytest.mark.parametrize(
    "offset, duration, expected",
    [
        (F(0), F(4), [F(4)]),
        (F(0), F(3), [F(3)]),
        (F(1), F(2), [F(2)]),
        (F(1, 2), F(1), [F(1)]),
        (F(1, 4), F(1), [F(3, 4), F(1, 4)]),
        (F(0), F(5, 2), [F(2), F(1, 2)]),
        (F(1, 3), F(7, 6), [F(2, 3), F(1, 2)]),
        (F(0), F(1, 3), [F(1, 3)]),
    ],
)
def test_decompose(offset, duration, expected):
    pieces = decompose(offset, duration, 4)
    assert [d for _, d in pieces] == expected
    assert sum(d for _, d in pieces) == duration
