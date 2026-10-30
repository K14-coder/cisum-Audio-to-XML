"""Command line: `cisum transcribe song.mp3 -o out/`, `cisum arrange`, `cisum doctor`."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from .types import LEVELS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cisum", description="Turn a song recording into piano arrangements.")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    t = sub.add_parser("transcribe", help="analyze a recording and write arrangements")
    t.add_argument("input", type=Path)
    t.add_argument("-o", "--out", type=Path, default=Path("out"))
    t.add_argument("--title", default=None)
    t.add_argument("--levels", default=",".join(LEVELS), help="comma-separated: easy,medium,hard")
    t.add_argument("--formats", default="musicxml,mid,json,pdf")
    t.add_argument("--separator", default="auto", choices=["auto", "demucs", "hpss"])
    t.add_argument("--demucs-model", default="htdemucs")
    t.add_argument("--beats", default="auto", choices=["auto", "beat_this", "librosa"])
    t.add_argument("--melody", default="auto", choices=["auto", "crepe", "pyin"])
    t.add_argument("--notes", default="auto", choices=["auto", "basic_pitch", "none"])
    t.add_argument("--stems", type=Path, default=None, help="folder with vocals.wav, bass.wav, other.wav to skip separation")
    t.add_argument("--device", default=None, help="torch device, e.g. cpu or cuda")
    t.add_argument("--max-duration", type=float, default=600.0, help="seconds")

    a = sub.add_parser("arrange", help="re-arrange from an existing analysis.json")
    a.add_argument("analysis", type=Path)
    a.add_argument("-o", "--out", type=Path, default=Path("out"))
    a.add_argument("--level", default="medium", choices=list(LEVELS))
    a.add_argument("--transpose", default=None, help="semitones, or 'auto'")
    a.add_argument("--title", default="Untitled")
    a.add_argument("--formats", default="musicxml,mid,json,pdf")

    sub.add_parser("doctor", help="show which analysis backends are installed")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    if args.command == "doctor":
        return _doctor()
    if args.command == "arrange":
        return _arrange(args)
    return _transcribe(args)


def _transcribe(args: argparse.Namespace) -> int:
    from .analyze import AnalyzeOptions
    from .audio import AudioError
    from .pipeline import PipelineOptions, run

    options = PipelineOptions(
        title=args.title or args.input.stem,
        levels=tuple(x.strip() for x in args.levels.split(",") if x.strip()),
        separator=args.separator,
        demucs_model=args.demucs_model,
        analyze=AnalyzeOptions(beats=args.beats, melody=args.melody, notes=args.notes, device=args.device),
        max_duration_s=args.max_duration,
        stems_dir=args.stems,
        formats=tuple(x.strip() for x in args.formats.split(",") if x.strip()),
    )
    started = time.time()

    def progress(status: str, frac: float, message: str) -> None:
        print(f"[{frac * 100:5.1f}%] {message}", file=sys.stderr)

    try:
        result = run(args.input, args.out, options, progress)
    except AudioError as e:
        print(f"error ({e.code}): {e.message}", file=sys.stderr)
        return 2
    a = result.analysis
    print(f"\nDone in {time.time() - started:.0f}s → {args.out}/")
    print(f"  key {a.main_key.name}, {a.bpm:.0f} BPM, {a.beats_per_bar}/{a.beat_unit}, {a.total_beats // a.beats_per_bar} bars")
    print(f"  melody from {a.flags.get('melody_source')}, {len(a.melody)} notes; {len(a.chords)} chord changes")
    print("  backends: " + ", ".join(f"{k}={v}" for k, v in a.backends.items()))
    for level, files in result.outputs.items():
        print(f"  {level}: " + ", ".join(p.name for p in files.values()))
    return 0


def _arrange(args: argparse.Namespace) -> int:
    from .pipeline import render
    from .types import Analysis

    analysis = Analysis.from_dict(json.loads(args.analysis.read_text()))
    transpose: int | str | None = args.transpose
    if transpose not in (None, "auto"):
        transpose = int(transpose)
    formats = tuple(x.strip() for x in args.formats.split(",") if x.strip())
    paths = render(analysis, args.level, transpose, args.out, args.title, formats)
    for p in paths.values():
        print(p)
    return 0


def _doctor() -> int:
    import shutil

    from . import beats, pitch, separate, transcribe

    rows = [
        ("ffmpeg", "yes" if shutil.which("ffmpeg") and shutil.which("ffprobe") else "MISSING (required)"),
        ("separation", ", ".join(separate.available_backends())),
        ("beats", ", ".join(beats.available_backends())),
        ("melody pitch", ", ".join(pitch.available_backends())),
        ("note transcription", "basic_pitch" if transcribe.available() else "none (chords use chroma)"),
    ]
    try:
        import torch

        rows.append(("torch device", "cuda" if torch.cuda.is_available() else "cpu"))
    except Exception:
        rows.append(("torch", "not installed"))
    width = max(len(k) for k, _ in rows)
    for k, v in rows:
        print(f"{k.ljust(width)}  {v}")
    print("\nBackends are listed best first; 'auto' uses the first one that loads.")
    print("Demucs and Beat This! download their weights the first time they run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
