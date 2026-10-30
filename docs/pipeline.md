# How the pipeline works

The pipeline splits at one file, `analysis.json`. Everything before it is slow audio work that runs once per recording. Everything after it is fast and deterministic, so switching level, key or left-hand style, or fixing a chord, regenerates the sheet in about a second.

Every neural stage has a DSP fallback, so the engine runs (with lower quality) on a machine with nothing but the base install. `cisum doctor` lists what's available, and `analysis.json` records which backend ran each stage under `backends`.

## 1. Ingest — `engine/audio.py`

- `ffprobe` confirms the file contains audio and checks the length limit. Errors carry stable codes (`not_audio`, `too_long`, `too_short`, `silent`, `decode_failed`) that the API shows to users.
- `ffmpeg` decodes to 44.1 kHz stereo WAV with EBU R128 loudness normalization.
- The original file's SHA-256 is the cache key: uploading the same recording again reuses the stored analysis.
- Tuning offset (cents from A440) comes from `librosa.estimate_tuning`. Every detected pitch is corrected by it before rounding to a note.

## 2. Separate — `engine/separate.py`

| Backend | What it does |
|---|---|
| `demucs` (default) | Hybrid Transformer Demucs (`htdemucs`, MIT) splits into vocals, bass, drums and other. Weights download on first use. |
| `hpss` (fallback) | librosa harmonic/percussive separation. The harmonic part becomes "other", a 220 Hz low-pass of it becomes "bass", and there is no vocal stem. |

Drums are never used. You can also hand the engine stems you already have (`cisum transcribe --stems DIR`), which is how the tests simulate perfect separation.

## 3. Analyze — `engine/analyze.py`

**Beats** (`beats.py`). Beat This! (MIT) gives beats and downbeats. The fallback is librosa's beat tracker plus a downbeat estimate: for meter 3 or 4 and every phase, it scores how well chord changes (chroma difference) and low-frequency onsets line up with bar starts. `timing.BeatGrid` then cleans the beats (removing doubled beats, filling dropouts), settles on one meter, extends the grid over the whole recording, and pads the start so beat 0 is a downbeat. From here on, every time is in **beats from the start of bar 1**.

**Melody** (`pitch.py`). torchcrepe (MIT, weights bundled) tracks the vocal stem's pitch every 10 ms; pYIN is the fallback. Frames more than 40 dB below the stem's loud passages are ignored. The pitch curve becomes notes in four steps:
1. Median smoothing.
2. Rounding to semitones with hysteresis, so vibrato doesn't flicker between notes.
3. Absorbing segments under 90 ms into their nearest neighbour.
4. Splitting held notes at re-attacks: onsets preceded by a clear dip in loudness, i.e. a new syllable.

With no vocal stem (or almost nothing sung), the melody is the top line of the accompaniment's transcription instead. Overtones reported as extra notes an octave up are dropped first, and isolated octave jumps are pulled back toward the line.

**Notes** (`transcribe.py`). Basic Pitch (Apache 2.0) transcribes the "other" and bass stems through its bundled ONNX model. The bass line keeps the lowest note at each moment. Without Basic Pitch, the bass is pitch-tracked like the melody and chords use chroma.

**Chords** (`chords.py`). For every beat, the engine totals how strongly each of the 12 pitch classes sounds, weighted by duration and confidence. That profile is scored against templates for major, minor, 7, maj7, m7, sus2, sus4 and dim, with:
- a bonus when the bass plays the root
- a small bonus for chords that belong to the key
- a prior that favours plain triads
- evidence scaled down on near-silent beats, with a "no chord" state for them

Viterbi then picks the sequence. Changing chord costs least on a downbeat, more at mid-bar, and most elsewhere, so labels don't flicker and tend to change on bar lines. A segment whose bass clearly sits on a chord tone other than the root becomes a slash chord (D/F#). Confidence is the softmax probability of the chosen chord's family (C and Cmaj7 agreeing still counts as a confident C). Below 0.5, the editor highlights it.

**Key** (`keydetect.py`). Krumhansl-Kessler profiles are correlated with the pitch-class histogram, with a nudge toward the tonic of the first and last bars' bass to split relative major/minor. To catch modulations, 16-bar windows are scored and Viterbi applies a stiff change penalty; segments shorter than 8 bars are folded away.

Finally, silent bars at the start and end are trimmed. A quarter beat of slack keeps a note detected at beat 3.9 from opening an empty bar.

## 4. Arrange — `engine/arrange.py`

| | Easy | Medium | Hard |
|---|---|---|---|
| Melody grid | eighths | sixteenths | sixteenths + triplet beats |
| Key | moved to ≤ 1 sharp/flat | as recorded | as recorded |
| Right-hand harmony | none | 1 chord note on beats 1 & 3 | 2 chord notes on every beat |
| Left hand | chord root, one note | voice-led 3-note chords, half notes | broken chords (1-5-8-10) in eighths, following the real bass |
| Max notes / hand span | 1 / 7 semitones | 2–3 / octave | 3 / octave |

Steps:
1. **Melody to right hand.** Each note snaps to the level's grid; triplet beats are allowed on Hard when the onsets fit a triplet grid clearly better. When two notes land in one slot, the longer and more confident one stays. Overlaps are cut and short gaps are closed (legato). The line is moved by whole octaves into C4–C6, phrase by phrase where a phrase still sticks out.
2. **Gaps.** Where the melody rests for 2+ bars (1 bar at the start and end), the right hand plays: a held chord tone (Easy), close-position chords near the previous melody note (Medium), or the accompaniment's top line when there is one (Hard).
3. **Right-hand harmony.** Chord tones a 3rd or 6th below the melody are preferred, and stay at or above middle C.
4. **Left hand** from the chords, split at bar lines. Medium picks, for each chord, the inversion that moves the fewest semitones from the previous one, kept below middle C.
5. **Playability.** Notes per hand and hand span are capped, keeping the melody note in the right hand and the bass note in the left. The left hand stays below the right: clashing notes are dropped, or the chord moves down an octave.

Within one hand, events never overlap. Notes that sound together are one event, which keeps the notation to a single voice per staff.

## 5. Notate — `engine/notate.py`

- **MusicXML** via music21: grand staff, key and time signatures, tempo, chord symbols, beams, triplet brackets.
  - Each event is split at bar lines and into note values a single (dotted or triplet) note can show, then tied.
  - Accidentals are worked out explicitly per bar and staff line (tied continuations never show one).
  - Pitch spelling follows the key, including the raised leading tone in minor.
- **MIDI** via mido: one track per hand, with a tempo map that follows the recording bar by bar (a single tempo when the song is steady).
- **PDF** via Verovio → SVG → cairosvg → pypdf. Verovio's text glyphs (♯ ♭ in chord symbols, the metronome note) come from a web font cairo can't load, so they're swapped for Unicode characters. Verovio keeps fonts per thread, so all engraving runs on one dedicated thread.
- **Score JSON** for the web viewer: events with spelled note names, chord symbols, and the tempo map.

## Measured on the synthetic test song

`tests/synth.py` renders an original 19-bar song: G major, 96 BPM, a two-bar intro and a vocal-like lead with vibrato. On it:
- **With clean stems:** tempo within 1%, key correct, 19/19 bars with the right chord, and 58/58 melody notes (onset within a quarter beat, exact pitch).
- **From the full mix with every DSP fallback:** tempo, key and at least 60% of chords right. The tests assert these thresholds.

Real recordings are harder; treat these numbers as a regression check, not an accuracy claim.
