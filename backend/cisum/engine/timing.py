"""The beat grid: converts between seconds in the recording and beats in the score."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import numpy as np


@dataclass
class BeatGrid:
    beat_times: np.ndarray  # seconds of beat 0, 1, 2, ...; beat 0 is the first beat of bar 1
    beats_per_bar: int

    def __post_init__(self) -> None:
        self.beat_times = np.asarray(self.beat_times, dtype=float)
        if len(self.beat_times) < 2:
            raise ValueError("a beat grid needs at least two beats")

    @property
    def n_beats(self) -> int:
        return len(self.beat_times)

    def to_beats(self, seconds: float | np.ndarray) -> np.ndarray:
        t = self.beat_times
        idx = np.arange(len(t), dtype=float)
        x = np.asarray(seconds, dtype=float)
        out = np.interp(x, t, idx)
        first_period = t[1] - t[0]
        last_period = t[-1] - t[-2]
        out = np.where(x < t[0], (x - t[0]) / first_period, out)
        out = np.where(x > t[-1], len(t) - 1 + (x - t[-1]) / last_period, out)
        return out

    def to_seconds(self, beats: float | np.ndarray) -> np.ndarray:
        t = self.beat_times
        idx = np.arange(len(t), dtype=float)
        b = np.asarray(beats, dtype=float)
        out = np.interp(b, idx, t)
        out = np.where(b < 0, t[0] + b * (t[1] - t[0]), out)
        out = np.where(b > len(t) - 1, t[-1] + (b - (len(t) - 1)) * (t[-1] - t[-2]), out)
        return out

    @property
    def median_period(self) -> float:
        return float(np.median(np.diff(self.beat_times)))

    def shifted(self, beats: int) -> "BeatGrid":
        """Drop the first `beats` beats (a whole number of bars) so the grid starts later."""
        if beats % self.beats_per_bar:
            raise ValueError("can only shift by whole bars")
        return BeatGrid(self.beat_times[beats:], self.beats_per_bar)

    @classmethod
    def from_tracking(
        cls,
        beats: np.ndarray,
        downbeats: np.ndarray,
        duration: float,
        beats_per_bar: int | None = None,
    ) -> "BeatGrid":
        """Build a regular grid from tracked beats and downbeats.

        Cleans the beat list (removes doubled beats, fills dropouts), settles on one
        meter, extends the grid to cover the whole recording, and pads the start so
        beat 0 is a downbeat (a pickup becomes the end of a mostly empty bar 1).
        """
        b = _clean_beats(np.sort(np.asarray(beats, dtype=float)))
        if len(b) < 4:
            # Too few beats to trust: assume 120 BPM in 4/4 from the start.
            period = 0.5
            b = np.arange(0.0, max(duration, 2.0) + period, period)
            downbeats = b[::4]
        period_start = float(np.median(np.diff(b[: min(len(b), 9)])))
        period_end = float(np.median(np.diff(b[-min(len(b), 9):])))

        # Downbeat phase and meter.
        db = np.asarray(downbeats, dtype=float)
        idx = np.array([int(np.argmin(np.abs(b - t))) for t in db]) if len(db) else np.array([], int)
        if beats_per_bar is None:
            beats_per_bar = _meter_from_downbeats(idx)
        phase = Counter((idx % beats_per_bar).tolist()).most_common(1)[0][0] if len(idx) else 0

        # Extend backwards to cover t=0, keeping the phase aligned.
        n_pre = int(np.ceil(max(0.0, b[0]) / period_start)) if b[0] > 0 else 0
        pre = b[0] - period_start * np.arange(n_pre, 0, -1)
        b = np.concatenate([pre, b])
        phase = (phase + n_pre) % beats_per_bar
        # Pad so index 0 is a downbeat.
        pad = (beats_per_bar - phase) % beats_per_bar if phase else 0
        if pad:
            b = np.concatenate([b[0] - period_start * np.arange(pad, 0, -1), b])
        # Extend forward past the end of the recording and finish the last bar.
        n_post = int(np.ceil(max(0.0, duration - b[-1]) / period_end)) + 1
        b = np.concatenate([b, b[-1] + period_end * np.arange(1, n_post + 1)])
        remainder = (len(b) - 1) % beats_per_bar
        if remainder:
            extra = beats_per_bar - remainder
            b = np.concatenate([b, b[-1] + period_end * np.arange(1, extra + 1)])
        return cls(b, beats_per_bar)


def _clean_beats(b: np.ndarray) -> np.ndarray:
    if len(b) < 3:
        return b
    period = float(np.median(np.diff(b)))
    # Remove beats that come too soon after the previous one.
    kept = [b[0]]
    for t in b[1:]:
        if t - kept[-1] >= 0.5 * period:
            kept.append(t)
    b = np.array(kept)
    # Fill gaps where the tracker dropped beats.
    out = [b[0]]
    for t in b[1:]:
        gap = t - out[-1]
        n = int(round(gap / period))
        if n >= 2 and gap > 1.5 * period:
            step = gap / n
            out.extend(out[-1] + step * np.arange(1, n))
        out.append(t)
    return np.array(out)


def _meter_from_downbeats(idx: np.ndarray) -> int:
    if len(idx) < 2:
        return 4
    diffs = [d for d in np.diff(idx).tolist() if d > 0]
    if not diffs:
        return 4
    common = Counter(diffs).most_common(1)[0][0]
    if common in (3, 6):
        return 3
    return 4
