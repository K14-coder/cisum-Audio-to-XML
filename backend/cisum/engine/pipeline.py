"""The whole pipeline: upload → ingest → separate → analyze → arrange → notate."""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import audio, notate, separate
from .analyze import AnalyzeOptions, analyze
from .arrange import arrange
from .types import LEVELS, Analysis, Score

log = logging.getLogger(__name__)

# Bump when a change to the engine makes old analyses worth recomputing.
PIPELINE_VERSION = "1"

# (status, start fraction, end fraction, message) for each stage of a job.
STAGES = {
    "ingesting": (0.0, 0.05, "Preparing audio…"),
    "separating": (0.05, 0.45, "Separating instruments…"),
    "analyzing": (0.45, 0.9, "Analyzing beats, melody, chords and key…"),
    "arranging": (0.9, 1.0, "Writing arrangements…"),
}

Progress = Callable[[str, float, str], None]  # (status, overall 0..1, message)


@dataclass
class PipelineOptions:
    title: str = "Untitled"
    levels: tuple[str, ...] = LEVELS
    separator: str = "auto"  # auto | demucs | hpss
    demucs_model: str = "htdemucs"
    analyze: AnalyzeOptions = field(default_factory=AnalyzeOptions)
    max_duration_s: float = 600.0
    min_duration_s: float = 5.0
    stems_dir: Path | None = None  # use pre-separated stems instead of running separation
    formats: tuple[str, ...] = ("musicxml", "mid", "json")  # add "pdf" to engrave PDFs too
    normalize_loudness: bool = True


@dataclass
class PipelineResult:
    analysis: Analysis
    analysis_path: Path
    outputs: dict[str, dict[str, Path]]  # level -> format -> path
    content_hash: str


def run(input_path: Path, out_dir: Path, options: PipelineOptions | None = None, progress: Progress | None = None) -> PipelineResult:
    options = options or PipelineOptions()
    report = progress or (lambda status, frac, msg: None)
    out_dir.mkdir(parents=True, exist_ok=True)

    def stage(status: str) -> Callable[[float, str], None]:
        a, b, default = STAGES[status]
        report(status, a, default)
        return lambda f, msg: report(status, a + (b - a) * max(0.0, min(1.0, f)), msg or default)

    stage("ingesting")
    info = audio.probe(input_path)
    if info.duration_s and info.duration_s > options.max_duration_s:
        raise audio.AudioError(
            "too_long", f"This recording is {info.duration_s / 60:.1f} minutes long; the limit is {options.max_duration_s / 60:.0f}."
        )
    content_hash = audio.sha256_file(input_path)
    work = Path(tempfile.mkdtemp(prefix="cisum-"))
    try:
        mix = audio.decode(input_path, work / "mix.wav", normalize=options.normalize_loudness)
        y, sr = audio.load(mix, sr=22050)
        audio.check_not_silent(y)
        if len(y) / sr < options.min_duration_s:
            raise audio.AudioError("too_short", "This recording is too short to arrange.")

        on_sep = stage("separating")
        if options.stems_dir:
            stems = separate.stems_from_dir(mix, Path(options.stems_dir))
        else:
            on_sep(0.1, "Separating instruments…")
            stems = separate.separate(mix, work / "stems", options.separator, options.demucs_model, options.analyze.device)

        on_analyze = stage("analyzing")
        analysis = analyze(stems, options.analyze, on_analyze)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    analysis_path = out_dir / "analysis.json"
    analysis_path.write_text(json.dumps(analysis.to_dict()), encoding="utf-8")

    on_arrange = stage("arranging")
    outputs: dict[str, dict[str, Path]] = {}
    for i, level in enumerate(options.levels):
        on_arrange(i / max(1, len(options.levels)), f"Writing the {level} arrangement…")
        outputs[level] = render(analysis, level, None, out_dir, options.title, options.formats)
    report("done", 1.0, "Done")
    return PipelineResult(analysis, analysis_path, outputs, content_hash)


def render(
    analysis: Analysis,
    level: str,
    transpose: int | str | None,
    out_dir: Path,
    title: str,
    formats: tuple[str, ...] = ("musicxml", "mid", "json"),
    stem: str | None = None,
    artist: str | None = None,
) -> dict[str, Path]:
    """Arrange one level and write the requested formats. Fast: no audio involved."""
    score = arrange(analysis, level, transpose, title, artist)
    return write_score(score, out_dir, formats, stem or level)


def write_score(score: Score, out_dir: Path, formats: tuple[str, ...], stem: str) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    if "musicxml" in formats or "pdf" in formats:
        paths["musicxml"] = notate.write_musicxml(score, out_dir / f"{stem}.musicxml")
    if "mid" in formats:
        paths["mid"] = notate.write_midi(score, out_dir / f"{stem}.mid")
    if "json" in formats:
        p = out_dir / f"{stem}.json"
        p.write_text(json.dumps(notate.score_to_dict(score)), encoding="utf-8")
        paths["json"] = p
    if "pdf" in formats:
        paths["pdf"] = notate.write_pdf(paths["musicxml"], out_dir / f"{stem}.pdf")
    return paths
