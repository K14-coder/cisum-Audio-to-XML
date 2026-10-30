"""Stage 5, notation: write the arrangement as MusicXML, MIDI, PDF and score JSON."""

from __future__ import annotations

import io
import math
import re
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from pathlib import Path
from typing import Any

from .theory import Key, key_letter_alters, midi_name, midi_spelling
from .types import Score

F = Fraction

# Durations a single note can show (with at most one dot), in beats, longest first.
_STRAIGHT = [F(4), F(3), F(2), F(3, 2), F(1), F(3, 4), F(1, 2), F(1, 4)]
_TRIPLET = [F(2, 3), F(1, 3), F(1, 6)]

LEVEL_LABEL = {"easy": "Easy piano", "medium": "Intermediate piano", "hard": "Advanced piano"}


# ---------------------------------------------------------------- rhythm spelling

def decompose(offset: Fraction, duration: Fraction, beats_per_bar: int) -> list[tuple[Fraction, Fraction]]:
    """Split a span inside one bar into note values that can each be written as a
    single (possibly dotted or triplet) note, tied together. Offsets are within the bar."""
    pieces: list[tuple[Fraction, Fraction]] = []
    pos, remaining = offset, duration
    while remaining > 0:
        value = _largest_value(pos, remaining, beats_per_bar)
        pieces.append((pos, value))
        pos += value
        remaining -= value
    return pieces


def _largest_value(pos: Fraction, remaining: Fraction, bpb: int) -> Fraction:
    beat_end = F(math.floor(pos) + 1)
    target = min(pos + remaining, beat_end)

    def is_triplet(x: Fraction) -> bool:
        return (x * 4).denominator != 1 and (x * 6).denominator == 1

    if is_triplet(pos) or is_triplet(target):
        for v in _TRIPLET:
            if v <= remaining and pos + v <= beat_end:
                return v
        return min(remaining, beat_end - pos)
    for v in _STRAIGHT:
        if v > remaining or pos + v > bpb:
            continue
        if v >= 2 and pos.denominator != 1:
            continue
        if v == 4 and pos != 0:
            continue
        if v in (F(1), F(3, 2)) and (pos * 2).denominator != 1:
            continue
        if v < 1 and pos + v > beat_end:
            continue  # sub-beat values don't cross the beat
        return v
    # Triplet remainder starting on a straight position (e.g. on the beat).
    for v in _TRIPLET:
        if v <= remaining and pos + v <= beat_end:
            return v
    return remaining


# ---------------------------------------------------------------- music21

def to_music21(score: Score):
    from music21 import clef, expressions, harmony, key as m21key, layout, metadata, meter, stream, tempo

    bpb = score.beats_per_bar
    n_bars = max(1, math.ceil(score.total_beats / bpb))
    s = stream.Score()
    s.metadata = metadata.Metadata()
    s.metadata.title = score.title
    s.metadata.addContributor(metadata.Contributor(role="arranger", name=f"{LEVEL_LABEL.get(score.level, 'Piano')} arrangement"))
    if score.artist:
        s.metadata.composer = score.artist
    rh = stream.PartStaff(id="RH")
    lh = stream.PartStaff(id="LH")
    key_changes = {int(start // bpb): k for start, k in score.key_changes}

    for part, hand in ((rh, "rh"), (lh, "lh")):
        events = sorted(score.hand(hand), key=lambda e: e.start)
        ei = 0
        for bar in range(n_bars):
            m = stream.Measure(number=bar + 1)
            bar_key = score.key_at(F(bar * bpb))
            if bar == 0:
                m.insert(0, clef.TrebleClef() if hand == "rh" else clef.BassClef())
                m.insert(0, m21key.KeySignature(score.key.fifths))
                m.insert(0, meter.TimeSignature(f"{bpb}/{score.beat_unit}"))
                if hand == "rh":
                    m.insert(0, tempo.MetronomeMark(number=int(round(score.bpm))))
                elif score.level == "hard":
                    m.insert(0, expressions.TextExpression("Ped. ad lib."))
            elif bar in key_changes:
                m.insert(0, m21key.KeySignature(key_changes[bar].fifths))
            bar_start, bar_end = F(bar * bpb), F((bar + 1) * bpb)
            while ei < len(events) and events[ei].end <= bar_start:
                ei += 1
            j = ei
            cursor = bar_start
            while j < len(events) and events[j].start < bar_end:
                ev = events[j]
                a, b = max(ev.start, bar_start), min(ev.end, bar_end)
                if a > cursor:
                    _rests(m, cursor - bar_start, a - cursor, bpb)
                pieces = decompose(a - bar_start, b - a, bpb)
                for i, (off, dur) in enumerate(pieces):
                    tie_in = i > 0 or ev.start < bar_start
                    tie_out = i < len(pieces) - 1 or ev.end > bar_end
                    m.insert(off, _make_note(ev.pitches, dur, bar_key, tie_in, tie_out))
                cursor = b
                j += 1
            if cursor < bar_end:
                _rests(m, cursor - bar_start, bar_end - cursor, bpb)
            part.append(m)
        _spell_accidentals(part, score)

    measures = list(rh.getElementsByClass(stream.Measure))
    for ch in score.chords:
        bar = int(ch.start // bpb)
        if 0 <= bar < len(measures):
            measures[bar].insert(ch.start - bar * bpb, harmony.ChordSymbol(_m21_figure(ch.label.symbol(score.key_at(ch.start)))))

    for part in (rh, lh):
        part.makeBeams(inPlace=True)
        for meas in part.getElementsByClass(stream.Measure):
            stream.makeNotation.makeTupletBrackets(meas.notesAndRests.stream(), inPlace=True)
    s.insert(0, rh)
    s.insert(0, lh)
    s.insert(0, layout.StaffGroup([rh, lh], name="Piano", abbreviation="Pno.", symbol="brace"))
    return s


def _make_note(pitches: tuple[int, ...], dur: Fraction, key: Key, tie_in: bool, tie_out: bool):
    from music21 import chord, duration, note, pitch, tie

    objs = []
    for p in pitches:
        letter, alter, octave = midi_spelling(p, key)
        objs.append(pitch.Pitch(step=letter, octave=octave, accidental=alter if alter else None))
    n = note.Note(objs[0]) if len(objs) == 1 else chord.Chord(objs)
    n.duration = duration.Duration(dur)
    if tie_in and tie_out:
        n.tie = tie.Tie("continue")
    elif tie_out:
        n.tie = tie.Tie("start")
    elif tie_in:
        n.tie = tie.Tie("stop")
    return n


def _rests(m, offset: Fraction, length: Fraction, bpb: int) -> None:
    from music21 import duration, note

    if offset == 0 and length == bpb:
        r = note.Rest()
        r.duration = duration.Duration(length)
        m.insert(offset, r)
        return
    for off, dur in decompose(offset, length, bpb):
        r = note.Rest()
        r.duration = duration.Duration(dur)
        m.insert(off, r)


def _spell_accidentals(part, score: Score) -> None:
    """Show an accidental only when a note differs from the key signature or from an
    earlier note on the same line in the bar. Tied continuations never show one."""
    from music21 import pitch, stream

    bpb = score.beats_per_bar
    for bar, m in enumerate(part.getElementsByClass(stream.Measure)):
        sig = key_letter_alters(score.key_at(F(bar * bpb)))
        state: dict[tuple[str, int], int] = {}
        for el in m.notes:
            ps = el.pitches
            continuation = el.tie is not None and el.tie.type in ("stop", "continue")
            for p in ps:
                alter = int(p.alter)
                slot = (p.step, p.octave)
                current = state.get(slot, sig[p.step])
                if continuation:
                    state[slot] = alter
                    if p.accidental is not None:
                        p.accidental.displayStatus = False
                    continue
                if alter != current:
                    p.accidental = pitch.Accidental(alter)
                    p.accidental.displayStatus = True
                elif p.accidental is not None:
                    p.accidental.displayStatus = False
                state[slot] = alter


def _m21_figure(symbol: str) -> str:
    """music21 writes flats in chord symbols as '-' (B-m7, D/F#, A-/C)."""
    return re.sub(r"([A-G])b", r"\1-", symbol)


def write_musicxml(score: Score, path: Path) -> Path:
    s = to_music21(score)
    out = Path(s.write("musicxml", fp=str(path)))
    # music21 repeats the title as the movement title, which viewers print as a subtitle.
    xml = out.read_text(encoding="utf-8")
    xml = re.sub(r"\s*<movement-title>[^<]*</movement-title>", "", xml, count=1)
    out.write_text(xml, encoding="utf-8")
    return out


# ---------------------------------------------------------------- MIDI

def write_midi(score: Score, path: Path, ticks_per_beat: int = 480) -> Path:
    """Standard MIDI file: tempo track that follows the song, one track per hand."""
    import mido

    mid = mido.MidiFile(ticks_per_beat=ticks_per_beat)
    meta = mido.MidiTrack()
    meta.append(mido.MetaMessage("track_name", name=score.title, time=0))
    meta.append(mido.MetaMessage("time_signature", numerator=score.beats_per_bar, denominator=score.beat_unit, time=0))
    try:
        meta.append(mido.MetaMessage("key_signature", key=score.key.tonic_name + ("m" if score.key.mode == "minor" else ""), time=0))
    except (ValueError, KeyError):
        pass
    last = 0
    for beat, bpm in score.tempo:
        tick = int(round(beat * ticks_per_beat))
        meta.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=tick - last))
        last = tick
    mid.tracks.append(meta)

    for channel, (hand, name, velocity) in enumerate((("rh", "Right hand", 84), ("lh", "Left hand", 68))):
        track = mido.MidiTrack()
        track.append(mido.MetaMessage("track_name", name=name, time=0))
        track.append(mido.Message("program_change", program=0, channel=channel, time=0))
        msgs: list[tuple[int, int, int, int]] = []  # (tick, order, note, velocity)
        for ev in score.hand(hand):
            on = int(round(ev.start * ticks_per_beat))
            off = int(round(ev.end * ticks_per_beat))
            for p in ev.pitches:
                msgs.append((on, 1, p, velocity))
                msgs.append((off, 0, p, 0))
        msgs.sort()
        last = 0
        for tick, _, p, vel in msgs:
            kind = "note_on" if vel else "note_off"
            track.append(mido.Message(kind, note=p, velocity=vel, channel=channel, time=tick - last))
            last = tick
        mid.tracks.append(track)
    mid.save(str(path))
    return path


# ---------------------------------------------------------------- JSON for the web viewer

def score_to_dict(score: Score) -> dict[str, Any]:
    events = []
    for ev in sorted(score.events, key=lambda e: (e.start, e.hand)):
        k = score.key_at(ev.start)
        events.append(
            {
                "hand": ev.hand,
                "start": float(ev.start),
                "duration": float(ev.duration),
                "pitches": list(ev.pitches),
                "names": [midi_name(p, k) for p in ev.pitches],
            }
        )
    return {
        "schema": 1,
        "title": score.title,
        "level": score.level,
        "transpose": score.transpose,
        "meter": {"beats_per_bar": score.beats_per_bar, "beat_unit": score.beat_unit},
        "key": {"tonic": score.key.tonic_name, "mode": score.key.mode, "fifths": score.key.fifths},
        "bpm": round(score.bpm, 1),
        "tempo": [{"beat": b, "bpm": bpm} for b, bpm in score.tempo],
        "total_beats": score.total_beats,
        "events": events,
        "chords": [
            {
                "start": float(c.start),
                "end": float(c.end),
                "symbol": c.label.symbol(score.key_at(c.start)),
                "confidence": round(c.confidence, 3),
            }
            for c in score.chords
        ],
    }


# ---------------------------------------------------------------- engraving (SVG / PDF)

# Verovio draws accidentals in chord symbols and the metronome note with SMuFL glyphs
# from an embedded web font that cairo can't load; swap them for plain Unicode.
_SMUFL_TEXT = {
    "": "\U0001d12b", "": "♭", "": "♮", "": "♯", "": "\U0001d12a",
    "": "\U0001d15e", "": "♩", "": "♪", "": ".",
    "": "♭", "": "♮", "": "♯",
}
_TSPAN_RE = re.compile(r'<tspan font-family="Leipzig" font-size="(\d+(?:\.\d+)?)px">([^<]*)</tspan>')


def _fix_svg_text(svg: str) -> str:
    def repl(m: re.Match) -> str:
        size = float(m.group(1)) * 0.6
        text = "".join(_SMUFL_TEXT.get(ch, ch) for ch in m.group(2))
        return f'<tspan font-family="DejaVu Sans" font-size="{size:.0f}px">{text}</tspan>'

    return _TSPAN_RE.sub(repl, svg)


# Verovio keeps its font resources per thread and isn't safe to use from several
# threads at once, so every engraving runs on one dedicated thread.
_engraver = ThreadPoolExecutor(max_workers=1, thread_name_prefix="verovio")


def render_svg_pages(musicxml: str) -> list[str]:
    return _engraver.submit(_render_svg_pages, musicxml).result()


def _render_svg_pages(musicxml: str) -> list[str]:
    import os

    import verovio

    tk = verovio.toolkit(False)
    tk.setResourcePath(os.path.join(os.path.dirname(verovio.__file__), "data"))
    tk.setOptions(
        {
            "pageWidth": 2100,
            "pageHeight": 2970,
            "pageMarginTop": 80,
            "pageMarginBottom": 80,
            "pageMarginLeft": 100,
            "pageMarginRight": 100,
            "scale": 42,
            "footer": "none",
            "header": "auto",
            "breaks": "auto",
            "justifyVertically": False,
        }
    )
    if not tk.loadData(musicxml):
        raise RuntimeError("Verovio couldn't read the MusicXML")
    return [_fix_svg_text(tk.renderToSVG(i)) for i in range(1, tk.getPageCount() + 1)]


def write_pdf(musicxml_path: Path, pdf_path: Path) -> Path:
    import cairosvg
    from pypdf import PdfReader, PdfWriter

    pages = render_svg_pages(Path(musicxml_path).read_text(encoding="utf-8"))
    writer = PdfWriter()
    for svg in pages:
        pdf_bytes = cairosvg.svg2pdf(bytestring=svg.encode("utf-8"), output_width=595, output_height=842)
        for page in PdfReader(io.BytesIO(pdf_bytes)).pages:
            writer.add_page(page)
    with open(pdf_path, "wb") as f:
        writer.write(f)
    return pdf_path
