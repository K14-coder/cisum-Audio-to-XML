"""Stage 4, arrangement: turn the song model into a two-hand piano part.

Rule-based and deterministic, so it runs in well under a second and can be re-run
whenever the user changes the level, the key, or fixes a chord.

Right hand: the melody, simplified to the level's rhythmic grid and moved into a
comfortable octave, with chord notes added underneath on strong beats at higher
levels. Where the singer rests for a while, the right hand plays the accompaniment's
top line or chord notes so the music doesn't go silent.

Left hand: driven by the chords. Easy plays roots, Medium voice-led block chords,
Hard broken-chord patterns that follow the real bass line where it's clear.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction

import numpy as np

from .theory import ChordLabel, Key, QUALITIES, best_transposition
from .types import LEVELS, Analysis, Event, Note, Score, ScoreChord

F = Fraction


@dataclass(frozen=True)
class LevelSpec:
    grid: Fraction  # rhythmic resolution of the melody
    triplets: bool  # allow triplet beats in the melody
    rh_harmony: int  # chord notes added under the melody on strong beats
    harmony_beats: str  # "none" | "half_bar" | "every"
    lh_style: str  # "root" | "block" | "broken"
    rh_max_notes: int
    lh_max_notes: int
    hand_span: int  # semitones between the lowest and highest note of one hand
    legato_gap: Fraction  # gaps up to this long are closed by holding the previous note


LEVEL_SPECS = {
    "easy": LevelSpec(F(1, 2), False, 0, "none", "root", 1, 1, 7, F(1)),
    "medium": LevelSpec(F(1, 4), False, 1, "half_bar", "block", 2, 3, 12, F(1, 2)),
    "hard": LevelSpec(F(1, 4), True, 2, "every", "broken", 3, 3, 12, F(1, 4)),
}

RH_RANGE = (60, 84)  # C4..C6: where the melody should sit
RH_HARMONY_FLOOR = 60  # chord notes added under the melody stay at or above middle C
FILL_GAP_BARS = 2  # melody rests at least this long get filled (intro and ending: one bar)
LH_ROOT_RANGE = (48, 59)  # easy: single bass notes C3..B3
LH_BLOCK_RANGE = (43, 59)  # medium: block chords, kept below middle C
LH_BROKEN_LOW = (36, 47)  # hard: low note of broken chords C2..B2


@dataclass
class _LineNote:
    start: Fraction
    end: Fraction
    pitch: int
    confidence: float


def resolve_transpose(analysis: Analysis, level: str, transpose: int | str | None) -> int:
    if transpose is None:
        transpose = "auto" if level == "easy" else 0
    if transpose == "auto":
        return best_transposition(analysis.main_key)
    t = int(transpose)
    if not -12 <= t <= 12:
        raise ValueError("transpose must be between -12 and 12 semitones")
    return t


def arrange(
    analysis: Analysis,
    level: str = "medium",
    transpose: int | str | None = None,
    title: str = "Untitled",
    artist: str | None = None,
) -> Score:
    if level not in LEVELS:
        raise ValueError(f"level must be one of {LEVELS}")
    spec = LEVEL_SPECS[level]
    t = resolve_transpose(analysis, level, transpose)
    bpb = analysis.beats_per_bar
    total = int(math.ceil(analysis.total_beats / bpb)) * bpb

    chords = [
        ScoreChord(_frac(c.start), _frac(c.end), c.label.transpose(t), c.confidence)
        for c in analysis.chords
        if c.end > c.start
    ]
    melody = [Note(n.start, n.end, n.pitch + t, n.confidence) for n in analysis.melody]
    fill = [Note(n.start, n.end, n.pitch + t, n.confidence) for n in analysis.fill]
    bass = [Note(n.start, n.end, n.pitch + t, n.confidence) for n in analysis.bass]

    line = quantize_line(melody, spec, total)
    line = fit_range(line, *RH_RANGE)
    rh = [Event("rh", n.start, n.end - n.start, (n.pitch,)) for n in line]
    rh += fill_gaps(line, chords, fill, spec, bpb, total, level)
    rh = _normalize(rh)
    rh = add_harmony(rh, chords, spec, bpb)
    lh = left_hand(chords, bass, spec, bpb, total)
    rh, lh = enforce_playability(rh, lh, spec)

    keys = [(F(int(round(k.start))), k.key.transpose(t)) for k in analysis.key]
    tempo = _tempo_changes(analysis)
    return Score(
        title=title,
        level=level,
        transpose=t,
        beats_per_bar=bpb,
        beat_unit=analysis.beat_unit,
        key=keys[0][1] if keys else Key(0, "major").transpose(t),
        bpm=float(np.median([b for _, b in tempo])) if tempo else analysis.bpm,
        tempo=tempo,
        total_beats=total,
        events=sorted(rh + lh, key=lambda e: (e.start, e.hand)),
        chords=_merge_score_chords([c for c in chords if c.label.root is not None and c.start < total]),
        key_changes=[(s, k) for s, k in keys[1:] if s % bpb == 0 and 0 < s < total],
        artist=artist,
    )


def _frac(x: float, limit: int = 12) -> Fraction:
    return F(x).limit_denominator(limit)


# ---------------------------------------------------------------- melody

def quantize_line(notes: Sequence[Note], spec: LevelSpec, total: int) -> list[_LineNote]:
    """Snap a monophonic line to the level's grid, one note at a time."""
    if not notes:
        return []
    triplet_beats = _triplet_beats(notes) if spec.triplets else set()

    def snap(x: float) -> Fraction:
        beat = math.floor(x)
        g = F(1, 3) if beat in triplet_beats else spec.grid
        steps = round((x - beat) / g)
        return beat + steps * g

    candidates: dict[Fraction, _LineNote] = {}
    for n in notes:
        s = snap(n.start)
        e = snap(n.end)
        unit = F(1, 3) if math.floor(n.start) in triplet_beats else spec.grid
        if e <= s:
            e = s + unit
        if s < 0 or s >= total:
            continue
        e = min(e, F(total))
        cand = _LineNote(s, e, n.pitch, n.confidence)
        prev = candidates.get(s)
        # Two notes snapped to one slot: keep the longer, more confident one.
        if prev is None or (n.end - n.start) * n.confidence > float(prev.end - prev.start) * prev.confidence:
            candidates[s] = cand
    line = [candidates[k] for k in sorted(candidates)]
    out: list[_LineNote] = []
    for i, n in enumerate(line):
        nxt = line[i + 1].start if i + 1 < len(line) else F(total)
        end = min(n.end, nxt)
        if nxt > end and nxt - end <= spec.legato_gap:
            end = nxt
        if end > n.start:
            out.append(_LineNote(n.start, end, n.pitch, n.confidence))
    return out


def _triplet_beats(notes: Sequence[Note]) -> set[int]:
    """Beats whose onsets fit a triplet grid clearly better than a sixteenth grid."""
    by_beat: dict[int, list[float]] = {}
    for n in notes:
        by_beat.setdefault(math.floor(n.start), []).append(n.start)
    out = set()
    for beat, onsets in by_beat.items():
        frac = [x - beat for x in onsets]
        if len(frac) < 2:
            continue
        err16 = sum(abs(f - round(f * 4) / 4) for f in frac)
        err3 = sum(abs(f - round(f * 3) / 3) for f in frac)
        if err3 < 0.5 * err16 and err16 > 0.08:
            out.add(beat)
    return out


def fit_range(line: list[_LineNote], low: int, high: int) -> list[_LineNote]:
    """Move the melody by whole octaves into the right hand's range, phrase by phrase
    only where a phrase still sticks out."""
    if not line:
        return line
    pitches = np.array([n.pitch for n in line])
    center = (low + high) / 2 - 2

    def score(k: int) -> tuple[int, float]:
        p = pitches + 12 * k
        return int(((p >= low) & (p <= high)).sum()), -abs(float(np.median(p)) - center)

    best = max(range(-3, 4), key=score)
    shifted = [_LineNote(n.start, n.end, n.pitch + 12 * best, n.confidence) for n in line]

    phrases: list[list[_LineNote]] = [[shifted[0]]]
    for prev, n in zip(shifted, shifted[1:]):
        if n.start - prev.end >= 2:
            phrases.append([])
        phrases[-1].append(n)
    out: list[_LineNote] = []
    for phrase in phrases:
        lo = min(n.pitch for n in phrase)
        hi = max(n.pitch for n in phrase)
        k = 0
        if lo < low - 3 and hi + 12 <= high + 7:
            k = 12
        elif hi > high + 4 and lo - 12 >= low - 5:
            k = -12
        out.extend(_LineNote(n.start, n.end, n.pitch + k, n.confidence) for n in phrase)
    return out


def fill_gaps(
    line: list[_LineNote],
    chords: Sequence[ScoreChord],
    fill: Sequence[Note],
    spec: LevelSpec,
    bpb: int,
    total: int,
    level: str,
) -> list[Event]:
    """Right-hand material for long stretches without melody (intros, solos, bridges)."""
    edges = [F(0)] + [x for n in line for x in (n.start, n.end)] + [F(total)]
    gaps = [(edges[i], edges[i + 1]) for i in range(0, len(edges), 2)]
    chords = [c for c in chords if c.label.root is not None]
    events: list[Event] = []
    ref_pitch = line[0].pitch if line else 67
    for gi, (gap_start, gap_end) in enumerate(gaps):
        a = F(math.ceil(gap_start / bpb) * bpb)
        b = F(math.floor(gap_end / bpb) * bpb)
        if gi == len(gaps) - 1:
            b = F(total)  # the ending: hold through the final bar
        outer = gi == 0 or gi == len(gaps) - 1 or not line
        if b - a < (bpb if outer else FILL_GAP_BARS * bpb):
            continue
        prev = [n for n in line if n.end <= gap_start]
        ref = prev[-1].pitch if prev else ref_pitch
        if level == "hard" and fill:
            region = [Note(n.start, n.end, n.pitch, n.confidence) for n in fill if a <= n.start < b]
            plain = LevelSpec(F(1, 2), False, 0, "none", spec.lh_style, 1, 1, 12, F(1, 2))
            q = fit_range(quantize_line(region, plain, total), *RH_RANGE)
            q = [n for n in q if a <= n.start < b]
            if len(q) >= 2:
                for n in q:
                    events.append(Event("rh", n.start, min(n.end, b) - n.start, (n.pitch,)))
                continue
        for chord, s, e in _chord_pieces(chords, a, b, bpb):
            if level == "easy":
                p = _nearest_chord_tone(chord, ref, 60, 76)
                events.append(Event("rh", s, e - s, (p,)))
                ref = p
            else:
                voicing = _close_voicing_top_near(chord, ref, 64, 76)
                events.append(Event("rh", s, e - s, tuple(voicing)))
                ref = voicing[-1]
    return events


def add_harmony(rh: list[Event], chords: Sequence[ScoreChord], spec: LevelSpec, bpb: int) -> list[Event]:
    if spec.rh_harmony == 0:
        return rh
    out = []
    for ev in rh:
        if len(ev.pitches) != 1 or ev.start.denominator != 1:
            out.append(ev)
            continue
        pos = int(ev.start) % bpb
        strong = spec.harmony_beats == "every" or pos == 0 or (bpb == 4 and pos == 2)
        chord = _chord_at(chords, ev.start)
        if not strong or chord is None or chord.label.root is None:
            out.append(ev)
            continue
        mel = ev.pitches[0]
        tones = set(chord.label.pcs())
        candidates = [p for p in range(mel - 12, mel - 2) if p % 12 in tones and p % 12 != mel % 12 and p >= RH_HARMONY_FLOOR]
        if not candidates:
            out.append(ev)
            continue
        preferred = sorted(candidates, key=lambda p: (0 if (mel - p) in (3, 4, 8, 9) else 1, -p))
        chosen = [preferred[0]]
        if spec.rh_harmony >= 2:
            rest = [p for p in sorted(candidates, reverse=True) if p % 12 != chosen[0] % 12 and p < chosen[0]]
            if rest:
                chosen.append(rest[0])
        out.append(Event("rh", ev.start, ev.duration, tuple(sorted(chosen + [mel]))))
    return out


# ---------------------------------------------------------------- left hand

def left_hand(chords: Sequence[ScoreChord], bass: Sequence[Note], spec: LevelSpec, bpb: int, total: int) -> list[Event]:
    events: list[Event] = []
    prev_voicing: list[int] | None = None
    confident_bass = [n for n in bass if n.confidence >= 0.5]
    for chord, a, b in _chord_pieces([c for c in chords if c.label.root is not None], F(0), F(total), bpb):
        label = chord.label
        length = b - a
        if spec.lh_style == "root":
            p = _place(label.bass_pc(), *LH_ROOT_RANGE)
            events.append(Event("lh", a, length, (p,)))
        elif spec.lh_style == "block":
            voicing = _voice_lead(label, prev_voicing, *LH_BLOCK_RANGE)
            prev_voicing = voicing
            for s, e in _block_rhythm(a, b, bpb):
                events.append(Event("lh", s, e - s, tuple(voicing)))
        else:
            events.extend(_broken(label, a, b, bpb, confident_bass))
    return events


def _chord_pieces(chords: Sequence[ScoreChord], a: Fraction, b: Fraction, bpb: int):
    """Chords clipped to [a, b) and split at bar lines."""
    for c in chords:
        s, e = max(c.start, a), min(c.end, b)
        while s < e:
            bar_end = F((math.floor(s / bpb) + 1) * bpb)
            piece_end = min(e, bar_end)
            yield c, s, piece_end
            s = piece_end


def _block_rhythm(a: Fraction, b: Fraction, bpb: int) -> list[tuple[Fraction, Fraction]]:
    if bpb == 4 and a % 4 == 0 and b - a == 4:
        return [(a, a + 2), (a + 2, b)]
    return [(a, b)]


def _broken(label: ChordLabel, a: Fraction, b: Fraction, bpb: int, bass: Sequence[Note]) -> list[Event]:
    intervals = QUALITIES[label.quality][0]
    third = intervals[1]
    fifth = intervals[2]
    low = _place(label.bass_pc(), *LH_BROKEN_LOW)
    root = _place(label.root, *LH_BROKEN_LOW)
    if root > low + 7:
        root -= 12
    elif root < low - 7:
        root += 12
    degree = {"1": low, "5": root + fifth, "8": root + 12, "10": root + 12 + third}
    # Follow the real bass where it clearly plays a note at the start of this piece.
    for n in bass:
        if abs(n.start - float(a)) <= 0.25 and n.end - n.start >= 0.4:
            degree["1"] = _place(n.pitch % 12, *LH_BROKEN_LOW)
            break
    pattern = ["1", "5", "8", "10", "8", "5", "8", "5"] if bpb == 4 else ["1", "5", "8", "10", "8", "5"]
    length = b - a
    if length < 1:
        return [Event("lh", a, length, (degree["1"],))]
    step = F(1, 2)
    n_steps = int(length / step)
    events = []
    for i in range(n_steps):
        s = a + i * step
        e = b if i == n_steps - 1 else s + step
        events.append(Event("lh", s, e - s, (degree[pattern[i % len(pattern)]],)))
    return events


def _place(pc: int, low: int, high: int) -> int:
    p = low + ((pc - low) % 12)
    return p if p <= high else p - 12


def _voicing_pcs(label: ChordLabel) -> list[int]:
    intervals = QUALITIES[label.quality][0]
    if len(intervals) == 4:
        intervals = (intervals[0], intervals[1], intervals[3])  # drop the fifth of four-note chords
    return [(label.root + i) % 12 for i in intervals]


def _voice_lead(label: ChordLabel, prev: list[int] | None, low: int, high: int) -> list[int]:
    pcs = _voicing_pcs(label)
    bass_pc = label.bass_pc()
    candidates: list[list[int]] = []
    for rot in range(len(pcs)):
        order = pcs[rot:] + pcs[:rot]
        for base in range(low, low + 12):
            if base % 12 != order[0]:
                continue
            voicing = [base]
            for pc in order[1:]:
                nxt = voicing[-1] + ((pc - voicing[-1]) % 12 or 12)
                voicing.append(nxt)
            if voicing[-1] <= high:
                candidates.append(voicing)
    if label.bass is not None:
        with_bass = [v for v in candidates if v[0] % 12 == bass_pc]
        if with_bass:
            candidates = with_bass
        else:
            candidates = [[v[0] - ((v[0] - bass_pc) % 12 or 12)] + v[:2] for v in candidates]
    if not candidates:
        return [_place(pcs[0], low, low + 11)]
    if prev is None:
        return min(candidates, key=lambda v: abs(float(np.mean(v)) - 54))
    return min(candidates, key=lambda v: sum(abs(x - y) for x, y in zip(sorted(v), sorted(prev))) + 0.01 * abs(v[0] - 50))


def _nearest_chord_tone(chord: ScoreChord, ref: int, low: int, high: int) -> int:
    tones = set(chord.label.pcs())
    options = [p for p in range(low, high + 1) if p % 12 in tones]
    return min(options, key=lambda p: (abs(p - ref), p)) if options else ref


def _close_voicing_top_near(chord: ScoreChord, ref: int, low: int, high: int) -> list[int]:
    pcs = _voicing_pcs(chord.label)
    best: list[int] | None = None
    for top in range(low, high + 1):
        if top % 12 not in pcs:
            continue
        voicing = [top]
        for _ in range(len(pcs) - 1):
            below = [p for p in range(voicing[0] - 1, voicing[0] - 12, -1) if p % 12 in pcs and p % 12 not in {v % 12 for v in voicing}]
            if below:
                voicing.insert(0, below[0])
        if best is None or abs(top - ref) < abs(best[-1] - ref):
            best = voicing
    return best or [ref]


def _chord_at(chords: Sequence[ScoreChord], beat: Fraction) -> ScoreChord | None:
    for c in chords:
        if c.start <= beat < c.end:
            return c
    return None


# ---------------------------------------------------------------- playability

def enforce_playability(rh: list[Event], lh: list[Event], spec: LevelSpec) -> tuple[list[Event], list[Event]]:
    rh = [_limit(ev, spec.rh_max_notes, spec.hand_span, keep_top=True) for ev in rh]
    lh = [_limit(ev, spec.lh_max_notes, spec.hand_span, keep_top=False) for ev in lh]
    rh = _normalize([e for e in rh if e.pitches])

    starts = [e.start for e in rh]
    fixed: list[Event] = []
    for ev in lh:
        rh_low = _lowest_rh_during(rh, starts, ev.start, ev.end)
        pitches = list(ev.pitches)
        if rh_low is not None and max(pitches) >= rh_low:
            below = [p for p in pitches if p < rh_low]
            lowered = [p - 12 for p in pitches]
            if len(below) >= min(2, len(pitches)):
                pitches = below  # drop the notes that clash with the right hand
            elif min(lowered) >= 28 and max(lowered) < rh_low:
                pitches = lowered
            elif below:
                pitches = below
            else:
                p = min(ev.pitches)
                while p >= rh_low:
                    p -= 12
                pitches = [p] if p >= 21 else []
        if pitches:
            fixed.append(Event("lh", ev.start, ev.duration, tuple(sorted(pitches))))
    return rh, _normalize(fixed)


def _limit(ev: Event, max_notes: int, span: int, keep_top: bool) -> Event:
    ps = sorted(set(ev.pitches), reverse=keep_top)  # most important first
    kept = [ps[0]]
    for p in ps[1:]:
        if len(kept) >= max_notes:
            break
        if abs(p - kept[0]) <= span:
            kept.append(p)
    return Event(ev.hand, ev.start, ev.duration, tuple(sorted(kept)))


def _lowest_rh_during(rh: list[Event], starts: list[Fraction], a: Fraction, b: Fraction) -> int | None:
    import bisect

    i = max(0, bisect.bisect_right(starts, a) - 1)
    low = None
    while i < len(rh) and rh[i].start < b:
        if rh[i].end > a:
            m = min(rh[i].pitches)
            low = m if low is None else min(low, m)
        i += 1
    return low


def _normalize(events: list[Event]) -> list[Event]:
    """Sort, merge events that start together, and cut overlaps so a hand never
    holds one note into the next."""
    by_start: dict[Fraction, Event] = {}
    for e in events:
        if e.duration <= 0:
            continue
        if e.start in by_start:
            prev = by_start[e.start]
            by_start[e.start] = Event(e.hand, e.start, max(prev.duration, e.duration), tuple(sorted(set(prev.pitches) | set(e.pitches))))
        else:
            by_start[e.start] = e
    ordered = [by_start[k] for k in sorted(by_start)]
    out = []
    for i, e in enumerate(ordered):
        end = e.end
        if i + 1 < len(ordered):
            end = min(end, ordered[i + 1].start)
        if end > e.start:
            out.append(Event(e.hand, e.start, end - e.start, e.pitches))
    return out


# ---------------------------------------------------------------- score metadata

def _tempo_changes(analysis: Analysis) -> list[tuple[float, float]]:
    tempos = np.array(analysis.bar_tempos())
    if len(tempos) == 0:
        return [(0.0, 120.0)]
    median = float(np.median(tempos))
    if float(np.std(tempos)) / median < 0.02:
        return [(0.0, round(median, 1))]
    from scipy.ndimage import median_filter

    smooth = median_filter(tempos, size=3, mode="nearest")
    out: list[tuple[float, float]] = []
    for bar, bpm in enumerate(smooth):
        if not out or abs(bpm - out[-1][1]) >= 1.0:
            out.append((float(bar * analysis.beats_per_bar), round(float(bpm), 1)))
    return out


def _merge_score_chords(chords: list[ScoreChord]) -> list[ScoreChord]:
    out: list[ScoreChord] = []
    for c in chords:
        if out and out[-1].label == c.label and out[-1].end == c.start:
            out[-1] = ScoreChord(out[-1].start, c.end, c.label, min(out[-1].confidence, c.confidence))
        else:
            out.append(c)
    return out
