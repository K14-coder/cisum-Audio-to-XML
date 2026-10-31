"""Pitch classes, keys, spelling and chord symbols.

Pitch classes are integers 0..11 with C = 0. MIDI note numbers use 60 = middle C (C4).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

LETTERS = "CDEFGAB"
LETTER_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
SHARP_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLAT_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]

# Interval structure and display suffix of every chord quality we detect or accept.
QUALITIES: dict[str, tuple[tuple[int, ...], str]] = {
    "maj": ((0, 4, 7), ""),
    "min": ((0, 3, 7), "m"),
    "7": ((0, 4, 7, 10), "7"),
    "maj7": ((0, 4, 7, 11), "maj7"),
    "min7": ((0, 3, 7, 10), "m7"),
    "sus2": ((0, 2, 7), "sus2"),
    "sus4": ((0, 5, 7), "sus4"),
    "dim": ((0, 3, 6), "dim"),
    "aug": ((0, 4, 8), "aug"),
    "6": ((0, 4, 7, 9), "6"),
    "min6": ((0, 3, 7, 9), "m6"),
}

# Accepted spellings of each quality when parsing user input.
_SUFFIX_TO_QUALITY = {
    "": "maj", "M": "maj", "maj": "maj", "major": "maj",
    "m": "min", "min": "min", "-": "min", "minor": "min",
    "7": "7", "dom7": "7",
    "maj7": "maj7", "M7": "maj7", "Maj7": "maj7", "Δ": "maj7", "Δ7": "maj7",
    "m7": "min7", "min7": "min7", "-7": "min7",
    "sus2": "sus2",
    "sus4": "sus4", "sus": "sus4",
    "dim": "dim", "°": "dim", "o": "dim",
    "aug": "aug", "+": "aug",
    "6": "6", "maj6": "6",
    "m6": "min6", "min6": "min6",
}

_CHORD_RE = re.compile(r"^\s*([A-Ga-g])([#b♯♭]?)([^/\s]*)(?:/([A-Ga-g])([#b♯♭]?))?\s*$")

# Major-key signature (circle-of-fifths position) for each tonic pitch class.
# Enharmonic ties (F#/Gb) resolve to sharps, the more common spelling in pop charts.
_MAJOR_FIFTHS = {0: 0, 7: 1, 2: 2, 9: 3, 4: 4, 11: 5, 6: 6, 1: -5, 8: -4, 3: -3, 10: -2, 5: -1}
_MAJOR_TONIC_BY_FIFTHS = {
    -7: "Cb", -6: "Gb", -5: "Db", -4: "Ab", -3: "Eb", -2: "Bb", -1: "F", 0: "C",
    1: "G", 2: "D", 3: "A", 4: "E", 5: "B", 6: "F#", 7: "C#",
}
_MINOR_TONIC_BY_FIFTHS = {
    -7: "Ab", -6: "Eb", -5: "Bb", -4: "F", -3: "C", -2: "G", -1: "D", 0: "A",
    1: "E", 2: "B", 3: "F#", 4: "C#", 5: "G#", 6: "D#", 7: "A#",
}
_SHARP_ORDER = "FCGDAEB"


class ChordParseError(ValueError):
    pass


def name_to_pc(name: str) -> int:
    """'C' -> 0, 'F#' -> 6, 'Bb' -> 10, 'Cb' -> 11."""
    name = name.strip().replace("♯", "#").replace("♭", "b")
    if not name or name[0].upper() not in LETTER_PC:
        raise ValueError(f"not a note name: {name!r}")
    pc = LETTER_PC[name[0].upper()]
    for ch in name[1:]:
        if ch == "#":
            pc += 1
        elif ch in "b-":
            pc -= 1
        else:
            raise ValueError(f"not a note name: {name!r}")
    return pc % 12


@dataclass(frozen=True)
class Key:
    tonic: int  # pitch class
    mode: str  # "major" | "minor"

    @property
    def fifths(self) -> int:
        relative_major = self.tonic if self.mode == "major" else (self.tonic + 3) % 12
        return _MAJOR_FIFTHS[relative_major]

    @property
    def tonic_name(self) -> str:
        table = _MAJOR_TONIC_BY_FIFTHS if self.mode == "major" else _MINOR_TONIC_BY_FIFTHS
        return table[self.fifths]

    @property
    def name(self) -> str:
        return f"{self.tonic_name} {self.mode}"

    @property
    def accidentals(self) -> int:
        return abs(self.fifths)

    def transpose(self, semitones: int) -> "Key":
        return Key((self.tonic + semitones) % 12, self.mode)

    def scale_pcs(self) -> list[int]:
        steps = (0, 2, 4, 5, 7, 9, 11) if self.mode == "major" else (0, 2, 3, 5, 7, 8, 10)
        return [(self.tonic + s) % 12 for s in steps]

    @classmethod
    def parse(cls, tonic: str, mode: str) -> "Key":
        if mode not in ("major", "minor"):
            raise ValueError(f"mode must be 'major' or 'minor', got {mode!r}")
        return cls(name_to_pc(tonic), mode)


def key_letter_alters(key: Key) -> dict[str, int]:
    """Accidental applied to each letter by the key signature."""
    alters = {letter: 0 for letter in LETTERS}
    f = key.fifths
    if f > 0:
        for letter in _SHARP_ORDER[:f]:
            alters[letter] = 1
    elif f < 0:
        for letter in reversed(_SHARP_ORDER[f:]):
            alters[letter] = -1
    return alters


def spell_pc(pc: int, key: Key) -> tuple[str, int]:
    """Choose letter + alteration (-2..2) for a pitch class in the context of a key."""
    pc %= 12
    alters = key_letter_alters(key)
    # Diatonic: the letter whose key-signature spelling hits this pitch class.
    for letter in LETTERS:
        if (LETTER_PC[letter] + alters[letter]) % 12 == pc:
            return letter, alters[letter]
    # Leading tone in minor keys is raised from the letter below the tonic (A minor -> G#).
    if key.mode == "minor" and pc == (key.tonic - 1) % 12:
        tonic_letter = key.tonic_name[0]
        letter = LETTERS[(LETTERS.index(tonic_letter) - 1) % 7]
        alter = (pc - LETTER_PC[letter] + 6) % 12 - 6
        return letter, alter
    # Other chromatic notes: sharps in sharp keys, flats in flat keys.
    if key.fifths > 0:
        name = SHARP_NAMES[pc]
    elif key.fifths < 0:
        name = FLAT_NAMES[pc]
    else:
        name = {1: "C#", 3: "Eb", 6: "F#", 8: "G#", 10: "Bb"}.get(pc, SHARP_NAMES[pc])
    return name[0], (1 if name.endswith("#") else -1 if name.endswith("b") else 0)


def pc_name(pc: int, key: Key | None = None) -> str:
    if key is None:
        return SHARP_NAMES[pc % 12]
    letter, alter = spell_pc(pc, key)
    return letter + ("#" * alter if alter > 0 else "b" * -alter)


def midi_name(midi: int, key: Key | None = None) -> str:
    """60 -> 'C4'; spelled for the key (Bb4 rather than A#4 in F major)."""
    if key is None:
        letter, alter = SHARP_NAMES[midi % 12][0], (1 if "#" in SHARP_NAMES[midi % 12] else 0)
    else:
        letter, alter = spell_pc(midi % 12, key)
    octave = (midi - alter) // 12 - 1
    return letter + ("#" * alter if alter > 0 else "b" * -alter) + str(octave)


def midi_spelling(midi: int, key: Key) -> tuple[str, int, int]:
    """(letter, alter, octave) for building notation objects."""
    letter, alter = spell_pc(midi % 12, key)
    return letter, alter, (midi - alter) // 12 - 1


@dataclass(frozen=True)
class ChordLabel:
    root: int | None  # None = no chord ("N")
    quality: str | None = None
    bass: int | None = None

    @property
    def is_none(self) -> bool:
        return self.root is None

    def pcs(self) -> list[int]:
        if self.root is None or self.quality is None:
            return []
        return [(self.root + i) % 12 for i in QUALITIES[self.quality][0]]

    def bass_pc(self) -> int | None:
        return self.root if self.bass is None else self.bass

    def transpose(self, semitones: int) -> "ChordLabel":
        if self.root is None:
            return self
        return ChordLabel(
            (self.root + semitones) % 12,
            self.quality,
            None if self.bass is None else (self.bass + semitones) % 12,
        )

    def symbol(self, key: Key | None = None) -> str:
        if self.root is None or self.quality is None:
            return "N"
        text = _chord_root_name(self.root, key) + QUALITIES[self.quality][1]
        if self.bass is not None and self.bass != self.root:
            text += "/" + _chord_root_name(self.bass, key)
        return text


def _chord_root_name(pc: int, key: Key | None) -> str:
    # Chord roots avoid double accidentals and odd spellings (E#, Cb) even when the key implies them.
    if key is None:
        return FLAT_NAMES[pc] if pc in (3, 10) else SHARP_NAMES[pc]
    name = pc_name(pc, key)
    if name in ("E#", "B#", "Fb", "Cb") or len(name) > 2:
        return FLAT_NAMES[pc] if key.fifths < 0 else SHARP_NAMES[pc]
    return name


def parse_chord(symbol: str) -> ChordLabel:
    """Parse 'Em7', 'D/F#', 'Bbmaj7', 'Csus4', 'N' (no chord)."""
    text = symbol.strip()
    if text.upper() in ("N", "N.C.", "NC", ""):
        return ChordLabel(None)
    m = _CHORD_RE.match(text)
    if not m:
        raise ChordParseError(f"can't read chord symbol {symbol!r}")
    letter, acc, suffix, bass_letter, bass_acc = m.groups()
    quality = _SUFFIX_TO_QUALITY.get(suffix)
    if quality is None:
        raise ChordParseError(f"unsupported chord quality {suffix!r} in {symbol!r}")
    root = name_to_pc(letter.upper() + _norm_acc(acc))
    bass = name_to_pc(bass_letter.upper() + _norm_acc(bass_acc)) if bass_letter else None
    if bass == root:
        bass = None
    return ChordLabel(root, quality, bass)


def _norm_acc(acc: str | None) -> str:
    return (acc or "").replace("♯", "#").replace("♭", "b")


def diatonic_chords(key: Key) -> set[tuple[int, str]]:
    """(root, quality) pairs that belong to the key, including common 7ths and the
    major V in minor keys."""
    scale = key.scale_pcs()
    if key.mode == "major":
        triads = ["maj", "min", "min", "maj", "maj", "min", "dim"]
        sevenths = ["maj7", "min7", "min7", "maj7", "7", "min7", None]
    else:
        triads = ["min", "dim", "maj", "min", "min", "maj", "maj"]
        sevenths = ["min7", None, "maj7", "min7", "min7", "maj7", "7"]
    out: set[tuple[int, str]] = set()
    for degree, root in enumerate(scale):
        out.add((root, triads[degree]))
        if sevenths[degree]:
            out.add((root, sevenths[degree]))
        out.add((root, "sus4"))
        out.add((root, "sus2"))
    if key.mode == "minor":
        out.add(((key.tonic + 7) % 12, "maj"))  # harmonic-minor V
        out.add(((key.tonic + 7) % 12, "7"))
    return out


def best_transposition(key: Key, max_shift: int = 6, shift_cost: float = 0.1, comfortable: int = 1) -> int:
    """Semitone shift (-max_shift..max_shift) that lands on a key with few accidentals.
    Keys with up to `comfortable` sharps or flats (C, G, F, Am, Em, Dm) count as easy."""
    best, best_cost = 0, float("inf")
    for t in range(-max_shift, max_shift + 1):
        cost = max(0, key.transpose(t).accidentals - comfortable) + shift_cost * abs(t)
        if cost < best_cost - 1e-9:
            best, best_cost = t, cost
    return best
