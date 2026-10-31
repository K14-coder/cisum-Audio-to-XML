"""Stage 3e, key: Krumhansl-Kessler key profiles, per section so modulations show up."""

from __future__ import annotations

import numpy as np

from .theory import Key
from .types import KeySegment

KK_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KK_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
KEYS = [Key(t, "major") for t in range(12)] + [Key(t, "minor") for t in range(12)]

WINDOW_BARS = 16
HOP_BARS = 4
MIN_SEGMENT_BARS = 8
CHANGE_PENALTY = 2.5  # in units of 10 x correlation


def key_scores(hist: np.ndarray) -> np.ndarray:
    """Pearson correlation of a 12-bin histogram with all 24 key profiles."""
    h = np.asarray(hist, dtype=float)
    if h.sum() <= 0:
        return np.zeros(24)
    out = np.zeros(24)
    for i, key in enumerate(KEYS):
        profile = np.roll(KK_MAJOR if key.mode == "major" else KK_MINOR, key.tonic)
        out[i] = np.corrcoef(h, profile)[0, 1]
    return np.nan_to_num(out)


def detect(
    pc: np.ndarray,
    beats_per_bar: int,
    tonic_hint: np.ndarray | None = None,
) -> list[KeySegment]:
    """`pc` is pitch-class energy per beat. `tonic_hint` (12 bins) nudges the choice
    between relative keys, e.g. the bass notes of the first and last bars."""
    n_beats = pc.shape[0]
    hint = np.zeros(24)
    if tonic_hint is not None and tonic_hint.sum() > 0:
        th = tonic_hint / tonic_hint.sum()
        hint = np.array([0.08 * th[k.tonic] for k in KEYS])

    total = key_scores(pc.sum(axis=0)) + hint
    global_idx = int(np.argmax(total))
    n_bars = max(1, n_beats // beats_per_bar)
    if n_bars < WINDOW_BARS + HOP_BARS:
        return [KeySegment(0.0, KEYS[global_idx], _margin(total, global_idx))]

    # Windowed scores, then Viterbi with a stiff change penalty.
    starts = list(range(0, max(1, n_bars - WINDOW_BARS + 1), HOP_BARS))
    em = np.zeros((len(starts), 24))
    for w, bar in enumerate(starts):
        a, b = bar * beats_per_bar, (bar + WINDOW_BARS) * beats_per_bar
        em[w] = key_scores(pc[a:b].sum(axis=0)) + hint + 0.05 * (np.arange(24) == global_idx)
    em *= 10.0
    delta = em[0].copy()
    back = np.zeros(em.shape, dtype=int)
    for w in range(1, len(starts)):
        best = int(np.argmax(delta))
        change = delta[best] - CHANGE_PENALTY
        take = change > delta
        back[w] = np.where(take, best, np.arange(24))
        delta = np.where(take, change, delta) + em[w]
    path = np.zeros(len(starts), dtype=int)
    path[-1] = int(np.argmax(delta))
    for w in range(len(starts) - 1, 0, -1):
        path[w - 1] = back[w, path[w]]

    # Each bar takes the key of the window centred nearest to it.
    centers = np.array(starts) + WINDOW_BARS / 2
    bar_keys = [int(path[int(np.argmin(np.abs(centers - (bar + 0.5))))]) for bar in range(n_bars)]
    segments: list[tuple[int, int, int]] = []  # (first bar, last bar exclusive, key index)
    for bar, k in enumerate(bar_keys):
        if segments and segments[-1][2] == k:
            segments[-1] = (segments[-1][0], bar + 1, k)
        else:
            segments.append((bar, bar + 1, k))
    # Fold away short segments.
    changed = True
    while changed and len(segments) > 1:
        changed = False
        for i, (a, b, k) in enumerate(segments):
            if b - a < MIN_SEGMENT_BARS:
                j = i - 1 if i > 0 else i + 1
                ja, jb, jk = segments[j]
                segments[j] = (min(a, ja), max(b, jb), jk)
                del segments[i]
                changed = True
                break
        merged: list[tuple[int, int, int]] = []
        for seg in segments:
            if merged and merged[-1][2] == seg[2]:
                merged[-1] = (merged[-1][0], seg[1], seg[2])
            else:
                merged.append(seg)
        segments = merged

    out = []
    for a, b, k in segments:
        scores = key_scores(pc[a * beats_per_bar : b * beats_per_bar].sum(axis=0)) + hint
        out.append(KeySegment(float(a * beats_per_bar), KEYS[k], _margin(scores, k)))
    out[0].start = 0.0
    return out


def _margin(scores: np.ndarray, idx: int) -> float:
    others = np.delete(scores, idx)
    margin = float(scores[idx] - others.max()) if len(others) else 1.0
    return float(np.clip(0.5 + 2.5 * margin, 0.0, 1.0))
