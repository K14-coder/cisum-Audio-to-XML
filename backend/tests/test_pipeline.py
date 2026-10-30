"""End-to-end runs on a synthetic song with known chords, melody, key and tempo."""

import json
from pathlib import Path

import mido
import pytest
from music21 import converter, stream

from cisum.engine import notate
from cisum.engine.analyze import AnalyzeOptions
from cisum.engine.audio import AudioError
from cisum.engine.pipeline import PipelineOptions, render, run
from cisum.engine.types import Analysis

from .synth import BPM, LEAD_IN_S, render as render_song

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def song(tmp_path_factory):
    return render_song(tmp_path_factory.mktemp("song"))


def _bar_offset(analysis: dict, song) -> int:
    """Analysis beat that lines up with the song's bar 1."""
    return round((LEAD_IN_S - analysis["beat_times"][0]) / song.beat_period)


def _chord_accuracy(a: dict, song) -> float:
    off = _bar_offset(a, song)
    hits = 0
    for bar, (root, quality) in enumerate(song.bar_chords):
        mid = off + bar * 4 + 1.5
        found = [c for c in a["chords"] if c["start"] <= mid < c["end"]]
        family = ("maj", "7", "maj7") if quality == "maj" else ("min", "min7")
        hits += bool(found and found[0]["root"] == root and found[0]["quality"] in family)
    return hits / len(song.bar_chords)


@pytest.fixture(scope="module")
def stems_result(song, tmp_path_factory):
    out = tmp_path_factory.mktemp("out")
    options = PipelineOptions(title="Synthetic", stems_dir=song.stems_dir, formats=("musicxml", "mid", "json", "pdf"))
    return run(song.mix, out, options)


def test_analysis_with_clean_stems(stems_result, song):
    a = json.loads(stems_result.analysis_path.read_text())
    assert abs(a["bpm"] - BPM) / BPM < 0.03
    assert a["meter"]["beats_per_bar"] == 4
    assert a["key"][0]["name"] == "G major"
    assert _chord_accuracy(a, song) >= 0.9
    off = _bar_offset(a, song)
    found = [(n["start"] - off, n["pitch"]) for n in a["melody"]]
    hits = sum(any(abs(s - t) <= 0.25 and p == q for s, p in found) for t, _, q in song.melody)
    assert hits / len(song.melody) >= 0.85
    assert a["flags"]["melody_source"] == "vocals"
    # The song model round-trips through JSON.
    assert Analysis.from_dict(a).to_dict()["chords"] == a["chords"]


def test_outputs_are_valid(stems_result):
    for level, files in stems_result.outputs.items():
        assert set(files) == {"musicxml", "mid", "json", "pdf"}
        parsed = converter.parse(str(files["musicxml"]))
        parts = parsed.parts
        assert len(parts) == 2
        bpb = 4
        for part in parts:
            for m in part.getElementsByClass(stream.Measure):
                assert m.duration.quarterLength == bpb, f"{level} bar {m.number} is not full"
        mid = mido.MidiFile(str(files["mid"]))
        assert len(mid.tracks) == 3
        assert sum(1 for t in mid.tracks[1:] for msg in t if msg.type == "note_on") > 20
        assert files["pdf"].read_bytes()[:5] == b"%PDF-"
        score = json.loads(files["json"].read_text())
        assert score["level"] == level and score["events"]


def test_rearrange_after_editing_a_chord(stems_result, tmp_path):
    a = Analysis.from_dict(json.loads(stems_result.analysis_path.read_text()))
    from cisum.engine.theory import parse_chord

    a.chords[1].label = parse_chord("Bm")
    paths = render(a, "medium", 3, tmp_path, "Edited", ("json",))
    score = json.loads(paths["json"].read_text())
    assert score["transpose"] == 3
    assert score["chords"][1]["symbol"] == "Dm"  # Bm up three semitones


def test_full_mix_with_dsp_fallbacks(song, tmp_path):
    """No separation model: harmonic/percussive split, melody from the accompaniment."""
    options = PipelineOptions(title="Fallback", separator="hpss", analyze=AnalyzeOptions(beats="librosa", melody="pyin"))
    result = run(song.mix, tmp_path, options)
    a = json.loads(result.analysis_path.read_text())
    assert abs(a["bpm"] - BPM) / BPM < 0.05
    assert a["key"][0]["name"] in ("G major", "E minor")
    assert _chord_accuracy(a, song) >= 0.6
    assert result.outputs["easy"]["musicxml"].exists()


def test_rejects_non_audio(tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("not audio")
    with pytest.raises(AudioError) as e:
        run(bad, tmp_path / "out")
    assert e.value.code == "not_audio"


def test_rejects_too_long(song, tmp_path):
    with pytest.raises(AudioError) as e:
        run(song.mix, tmp_path, PipelineOptions(max_duration_s=10))
    assert e.value.code == "too_long"


def test_pdf_has_no_missing_glyphs(stems_result):
    svg = notate.render_svg_pages(Path(stems_result.outputs["medium"]["musicxml"]).read_text())[0]
    assert 'font-family="Leipzig"' not in svg.split("</style>")[-1]


def test_engraving_works_from_other_threads(stems_result):
    import threading

    xml = Path(stems_result.outputs["easy"]["musicxml"]).read_text()
    results = []
    threads = [threading.Thread(target=lambda: results.append(len(notate.render_svg_pages(xml)))) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == [1, 1, 1]
