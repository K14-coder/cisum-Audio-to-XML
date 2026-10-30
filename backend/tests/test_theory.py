import pytest

from cisum.engine.theory import (
    ChordLabel,
    ChordParseError,
    Key,
    best_transposition,
    midi_name,
    parse_chord,
)


@pytest.mark.parametrize(
    "symbol, root, quality, bass",
    [
        ("G", 7, "maj", None),
        ("Em7", 4, "min7", None),
        ("D/F#", 2, "maj", 6),
        ("Bbmaj7", 10, "maj7", None),
        ("Csus4", 0, "sus4", None),
        ("F#dim", 6, "dim", None),
        ("Am6", 9, "min6", None),
        ("c", 0, "maj", None),
        ("Ab/C", 8, "maj", 0),
    ],
)
def test_parse_chord(symbol, root, quality, bass):
    label = parse_chord(symbol)
    assert (label.root, label.quality, label.bass) == (root, quality, bass)


def test_no_chord():
    assert parse_chord("N").is_none
    assert parse_chord("N.C.").is_none


@pytest.mark.parametrize("bad", ["H", "Cxyz", "C/H", "7"])
def test_bad_chords(bad):
    with pytest.raises(ChordParseError):
        parse_chord(bad)


def test_symbols_follow_key():
    assert ChordLabel(10, "maj").symbol(Key(5, "major")) == "Bb"  # F major uses flats
    assert ChordLabel(6, "min").symbol(Key(2, "major")) == "F#m"
    assert ChordLabel(2, "maj", 6).symbol(Key(7, "major")) == "D/F#"
    assert ChordLabel(None).symbol() == "N"


def test_key_names_and_signatures():
    assert Key(7, "major").fifths == 1
    assert Key(5, "major").fifths == -1
    assert Key(9, "minor").fifths == 0
    assert Key(4, "minor").name == "E minor"
    assert Key(3, "major").name == "Eb major"
    assert Key.parse("Bb", "major").tonic == 10


def test_spelling():
    assert midi_name(60) == "C4"
    assert midi_name(70, Key(5, "major")) == "Bb4"
    assert midi_name(66, Key(7, "major")) == "F#4"
    assert midi_name(68, Key(9, "minor")) == "G#4"  # raised leading tone in A minor
    assert midi_name(61, Key(2, "minor")) == "C#4"  # and in D minor


def test_best_transposition():
    assert best_transposition(Key(0, "major")) == 0
    assert best_transposition(Key(7, "major")) == 0  # one sharp is fine
    assert Key(2, "major").transpose(best_transposition(Key(2, "major"))).accidentals <= 1
    assert Key(4, "major").transpose(best_transposition(Key(4, "major"))).accidentals <= 1
