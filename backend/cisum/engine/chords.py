"""Stage 3d, chords: one label per beat from pitch-class profiles, smoothed with Viterbi.

For every beat we total how strongly each of the 12 pitch classes sounds (from
transcribed notes, or from chroma when no transcriber is installed), score that
profile against chord templates, then pick the most likely chord sequence. Changing
chord costs more off the downbeat, so labels don't flicker and tend to move on bar
lines the way real songs do.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from .theory import ChordLabel, Key, QUALITIES, diatonic_chords
from .types import ChordSegment, Note

DETECT_QUALITIES = ("maj", "min", "7", "maj7", "min7", "sus2", "sus4", "dim")
QUALITY_PRIOR = {"maj": 0.0, "min": 0.0, "7": -0.03, "maj7": -0.04, "min7": -0.03, "sus2": -0.09, "sus4": -0.08, "dim": -0.08}
# Families share a third, so "C" and "Cmaj7" agreeing still counts as a confident C.
FAMILY = {"maj": "M", "7": "M", "maj7": "M", "6": "M", "min": "m", "min7": "m", "min6": "m", "sus2": "s", "sus4": "s", "dim": "d", "aug": "a"}

EMISSION_SCALE = 10.0
CHANGE_PENALTY = {"downbeat": 0.6, "half_bar": 1.2, "other": 2.2}
N_SWITCH_PENALTY = 0.3
KEY_BONUS = 0.04


def _states() -> list[ChordLabel]:
    states = [ChordLabel(r, q) for q in DETECT_QUALITIES for r in range(12)]
    states.append(ChordLabel(None))
    return states


def _template_matrix(states: Sequence[ChordLabel]) -> np.ndarray:
    T = np.zeros((len(states), 12))
    for i, s in enumerate(states):
        if s.root is None:
            continue
        intervals = QUALITIES[s.quality][0]
        weights = {0: 1.0, 3: 0.85, 4: 0.85, 7: 0.8, 6: 0.8, 8: 0.8, 10: 0.65, 11: 0.65, 9: 0.65, 2: 0.7, 5: 0.7}
        for iv in intervals:
            T[i, (s.root + iv) % 12] = weights.get(iv, 0.7)
        T[i] /= np.linalg.norm(T[i])
    return T


def profiles_from_notes(
    groups: Sequence[tuple[Sequence[Note], float]], n_beats: int
) -> np.ndarray:
    """Duration-weighted pitch-class energy per beat. `groups` is [(notes, weight), ...]."""
    pc = np.zeros((n_beats, 12))
    for notes, weight in groups:
        for n in notes:
            a = max(0.0, n.start)
            b = min(float(n_beats), n.end)
            if b <= a:
                continue
            w = weight * (0.5 + 0.5 * min(1.0, n.confidence))
            for beat in range(int(np.floor(a)), int(np.ceil(b))):
                overlap = min(b, beat + 1) - max(a, beat)
                if overlap > 0:
                    pc[beat, n.pitch % 12] += overlap * w
    return pc


def profiles_from_chroma(chroma: np.ndarray, frame_beats: np.ndarray, n_beats: int) -> np.ndarray:
    """Average chroma frames into beats. `frame_beats` is each frame's beat position."""
    pc = np.zeros((n_beats, 12))
    counts = np.zeros(n_beats)
    idx = np.floor(frame_beats).astype(int)
    ok = (idx >= 0) & (idx < n_beats)
    np.add.at(pc, idx[ok], chroma[:, ok].T)
    np.add.at(counts, idx[ok], 1)
    return pc / np.maximum(counts, 1)[:, None]


def recognize(
    pc: np.ndarray,
    bass: np.ndarray | None,
    beats_per_bar: int,
    key_for_beat: Sequence[Key] | None = None,
) -> list[ChordSegment]:
    """Label every beat and merge runs into chord segments (in beats)."""
    n_beats = pc.shape[0]
    if n_beats == 0:
        return []
    states = _states()
    T = _template_matrix(states)
    n_state = len(states)
    none_idx = n_state - 1

    energy = pc.sum(axis=1)
    active = energy[energy > 1e-9]
    ref = float(np.median(active)) if len(active) else 1.0
    rel = energy / max(ref, 1e-9)
    norm = pc / (np.linalg.norm(pc, axis=1, keepdims=True) + 1e-9)
    score = norm @ T.T  # (beats, states)

    prior = np.array([QUALITY_PRIOR.get(s.quality, 0.0) if s.root is not None else 0.0 for s in states])
    score += prior
    if bass is not None:
        bn = bass / (bass.sum(axis=1, keepdims=True) + 1e-9)
        for i, s in enumerate(states):
            if s.root is None:
                continue
            others = [p for p in s.pcs() if p != s.root]
            score[:, i] += 0.2 * bn[:, s.root] + 0.05 * bn[:, others].sum(axis=1)
    if key_for_beat is not None:
        cache: dict[Key, np.ndarray] = {}
        for t, key in enumerate(key_for_beat[:n_beats]):
            if key not in cache:
                dia = diatonic_chords(key)
                cache[key] = np.array([KEY_BONUS if (s.root, s.quality) in dia else 0.0 for s in states])
            score[t] += cache[key]
    # Cosine similarity ignores loudness, so a beat with a sliver of sound would match a
    # chord perfectly; scale chord evidence down on near-silent beats.
    score[:, :none_idx] *= np.clip(rel / 0.25, 0.0, 1.0)[:, None]
    score[:, none_idx] = np.clip(1.0 - rel / 0.12, 0.0, 1.0) * 0.95

    path = _viterbi(score * EMISSION_SCALE, beats_per_bar, none_idx)
    confidence = _confidence(score, states, path)

    segments: list[ChordSegment] = []
    start = 0
    for t in range(1, n_beats + 1):
        if t == n_beats or path[t] != path[start]:
            label = states[path[start]]
            conf = float(np.mean(confidence[start:t]))
            if label.root is not None and bass is not None:
                label = _with_inversion(label, bass[start:t])
            segments.append(ChordSegment(float(start), float(t), label, conf))
            start = t
    return segments


def _viterbi(em: np.ndarray, beats_per_bar: int, none_idx: int) -> np.ndarray:
    n_beats, n_state = em.shape
    delta = em[0].copy()
    back = np.zeros((n_beats, n_state), dtype=np.int32)
    back[0] = np.arange(n_state)
    is_none = np.zeros(n_state, dtype=bool)
    is_none[none_idx] = True
    for t in range(1, n_beats):
        pos = t % beats_per_bar
        if pos == 0:
            pen = CHANGE_PENALTY["downbeat"]
        elif beats_per_bar == 4 and pos == 2:
            pen = CHANGE_PENALTY["half_bar"]
        else:
            pen = CHANGE_PENALTY["other"]
        best_prev = int(np.argmax(delta))
        change = delta[best_prev] - pen - np.where(is_none | is_none[best_prev], N_SWITCH_PENALTY, 0.0)
        stay = delta
        take_change = change > stay
        back[t] = np.where(take_change, best_prev, np.arange(n_state))
        delta = np.where(take_change, change, stay) + em[t]
    path = np.zeros(n_beats, dtype=np.int32)
    path[-1] = int(np.argmax(delta))
    for t in range(n_beats - 1, 0, -1):
        path[t - 1] = back[t, path[t]]
    return path


def _confidence(score: np.ndarray, states: Sequence[ChordLabel], path: np.ndarray) -> np.ndarray:
    logits = score * 20.0
    logits -= logits.max(axis=1, keepdims=True)
    p = np.exp(logits)
    p /= p.sum(axis=1, keepdims=True)
    family_key = [(s.root, FAMILY.get(s.quality, "?")) if s.root is not None else (None, "N") for s in states]
    out = np.zeros(len(path))
    for t, j in enumerate(path):
        fam = family_key[j]
        out[t] = sum(p[t, i] for i, f in enumerate(family_key) if f == fam)
    return out


def _with_inversion(label: ChordLabel, bass: np.ndarray) -> ChordLabel:
    total = bass.sum(axis=0)
    s = total.sum()
    if s <= 1e-9:
        return label
    b = total / s
    top = int(np.argmax(b))
    if top != label.root and top in label.pcs() and b[top] > 0.5 and b[label.root] < 0.2:
        return ChordLabel(label.root, label.quality, top)
    return label


def merge_adjacent(segments: list[ChordSegment]) -> list[ChordSegment]:
    out: list[ChordSegment] = []
    for seg in segments:
        if out and out[-1].label == seg.label and abs(out[-1].end - seg.start) < 1e-6:
            prev = out[-1]
            total = (prev.end - prev.start) + (seg.end - seg.start)
            prev.confidence = (prev.confidence * (prev.end - prev.start) + seg.confidence * (seg.end - seg.start)) / total
            prev.end = seg.end
            prev.edited = prev.edited or seg.edited
        else:
            out.append(ChordSegment(seg.start, seg.end, seg.label, seg.confidence, seg.edited))
    return out
