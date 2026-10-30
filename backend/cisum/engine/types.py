"""Data model shared by every stage.

Raw detections (`NoteEvent`) are in seconds. Everything from the analysis on
(`Note`, `ChordSegment`, `KeySegment`, `Score`) is in beats counted from the
start of bar 1, which is what notation needs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

import numpy as np

from .theory import ChordLabel, Key, QUALITIES, name_to_pc

ANALYSIS_SCHEMA = 1
LEVELS = ("easy", "medium", "hard")


@dataclass
class NoteEvent:
    """A detected note in seconds."""

    start: float
    end: float
    pitch: int
    confidence: float = 1.0
    velocity: float = 0.8

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Note:
    """A note in beats."""

    start: float
    end: float
    pitch: int
    confidence: float = 1.0

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": round(self.start, 4),
            "end": round(self.end, 4),
            "pitch": int(self.pitch),
            "confidence": round(float(self.confidence), 3),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Note":
        return cls(float(d["start"]), float(d["end"]), int(d["pitch"]), float(d.get("confidence", 1.0)))


@dataclass
class ChordSegment:
    start: float
    end: float
    label: ChordLabel
    confidence: float = 1.0
    edited: bool = False

    def to_dict(self, key: Key | None) -> dict[str, Any]:
        d: dict[str, Any] = {
            "start": round(self.start, 4),
            "end": round(self.end, 4),
            "symbol": self.label.symbol(key),
            "root": self.label.root,
            "quality": self.label.quality,
            "bass": None if self.label.root is None else self.label.bass_pc(),
            "confidence": round(float(self.confidence), 3),
        }
        if self.edited:
            d["edited"] = True
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ChordSegment":
        root = d.get("root")
        if root is None:
            label = ChordLabel(None)
        else:
            quality = d.get("quality") or "maj"
            if quality not in QUALITIES:
                raise ValueError(f"unknown chord quality {quality!r}")
            bass = d.get("bass")
            label = ChordLabel(int(root), quality, None if bass is None or bass == root else int(bass))
        return cls(float(d["start"]), float(d["end"]), label, float(d.get("confidence", 1.0)), bool(d.get("edited", False)))


@dataclass
class KeySegment:
    start: float
    key: Key
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": round(self.start, 4),
            "tonic": self.key.tonic_name,
            "mode": self.key.mode,
            "name": self.key.name,
            "confidence": round(float(self.confidence), 3),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "KeySegment":
        return cls(float(d["start"]), Key(name_to_pc(d["tonic"]), d["mode"]), float(d.get("confidence", 1.0)))


@dataclass
class Analysis:
    """The song model: computed once per upload, edited by users, read by the arranger."""

    duration_s: float
    tuning_cents: float
    beats_per_bar: int
    beat_times: list[float]
    total_beats: int
    key: list[KeySegment]
    chords: list[ChordSegment]
    melody: list[Note]
    bass: list[Note]
    fill: list[Note]
    beat_unit: int = 4
    version: int = 1
    flags: dict[str, Any] = field(default_factory=dict)
    backends: dict[str, str] = field(default_factory=dict)

    def key_at(self, beat: float) -> Key:
        current = self.key[0].key if self.key else Key(0, "major")
        for seg in self.key:
            if seg.start <= beat + 1e-9:
                current = seg.key
        return current

    @property
    def main_key(self) -> Key:
        """The key that covers the most beats."""
        if not self.key:
            return Key(0, "major")
        spans: dict[Key, float] = {}
        for i, seg in enumerate(self.key):
            end = self.key[i + 1].start if i + 1 < len(self.key) else self.total_beats
            spans[seg.key] = spans.get(seg.key, 0.0) + max(0.0, end - seg.start)
        return max(spans, key=lambda k: spans[k])

    def bar_tempos(self) -> list[float]:
        """BPM of every bar, from the beat grid."""
        t = np.asarray(self.beat_times)
        bpb = self.beats_per_bar
        out = []
        for bar in range(self.total_beats // bpb):
            a, b = bar * bpb, min((bar + 1) * bpb, len(t) - 1)
            if b <= a:
                break
            span = t[b] - t[a]
            out.append(60.0 * (b - a) / span if span > 0 else 120.0)
        return out or [120.0]

    @property
    def bpm(self) -> float:
        return float(np.median(self.bar_tempos()))

    def to_dict(self) -> dict[str, Any]:
        tempos = self.bar_tempos()
        tempo_changes = []
        for i, bpm in enumerate(tempos):
            if not tempo_changes or abs(bpm - tempo_changes[-1]["bpm"]) >= 0.5:
                tempo_changes.append({"bar": i + 1, "bpm": round(bpm, 1)})
        return {
            "schema": ANALYSIS_SCHEMA,
            "version": self.version,
            "duration_s": round(self.duration_s, 3),
            "tuning_cents": round(self.tuning_cents, 1),
            "meter": {"beats_per_bar": self.beats_per_bar, "beat_unit": self.beat_unit},
            "bpm": round(self.bpm, 1),
            "tempo": tempo_changes,
            "beat_times": [round(t, 4) for t in self.beat_times],
            "total_beats": self.total_beats,
            "key": [k.to_dict() for k in self.key],
            "chords": [c.to_dict(self.key_at(c.start)) for c in self.chords],
            "melody": [n.to_dict() for n in self.melody],
            "bass": [n.to_dict() for n in self.bass],
            "fill": [n.to_dict() for n in self.fill],
            "flags": dict(self.flags),
            "backends": dict(self.backends),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Analysis":
        if d.get("schema") != ANALYSIS_SCHEMA:
            raise ValueError(f"unsupported analysis schema {d.get('schema')!r}")
        return cls(
            duration_s=float(d["duration_s"]),
            tuning_cents=float(d.get("tuning_cents", 0.0)),
            beats_per_bar=int(d["meter"]["beats_per_bar"]),
            beat_unit=int(d["meter"].get("beat_unit", 4)),
            beat_times=[float(t) for t in d["beat_times"]],
            total_beats=int(d["total_beats"]),
            key=[KeySegment.from_dict(k) for k in d["key"]],
            chords=[ChordSegment.from_dict(c) for c in d["chords"]],
            melody=[Note.from_dict(n) for n in d["melody"]],
            bass=[Note.from_dict(n) for n in d["bass"]],
            fill=[Note.from_dict(n) for n in d.get("fill", [])],
            version=int(d.get("version", 1)),
            flags=dict(d.get("flags", {})),
            backends=dict(d.get("backends", {})),
        )


@dataclass
class Event:
    """Notes struck together by one hand. Within a hand, events never overlap."""

    hand: str  # "rh" | "lh"
    start: Fraction
    duration: Fraction
    pitches: tuple[int, ...]

    @property
    def end(self) -> Fraction:
        return self.start + self.duration


@dataclass
class ScoreChord:
    start: Fraction
    end: Fraction
    label: ChordLabel
    confidence: float


@dataclass
class Score:
    title: str
    level: str
    transpose: int
    beats_per_bar: int
    beat_unit: int
    key: Key
    bpm: float
    tempo: list[tuple[float, float]]  # (beat, bpm) changes
    total_beats: int
    events: list[Event]
    chords: list[ScoreChord]
    key_changes: list[tuple[Fraction, Key]] = field(default_factory=list)  # after the first key
    artist: str | None = None

    def hand(self, hand: str) -> list[Event]:
        return [e for e in self.events if e.hand == hand]

    def key_at(self, beat: Fraction | float) -> Key:
        current = self.key
        for start, k in self.key_changes:
            if start <= beat:
                current = k
        return current
