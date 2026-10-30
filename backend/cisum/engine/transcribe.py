"""Stage 3c, notes: polyphonic note transcription of the bass and accompaniment stems.

Backend:
  basic_pitch  Spotify's Basic Pitch (Apache 2.0), run through its bundled ONNX
               model with onnxruntime.

Without it, chords fall back to chroma features and the bass line to pitch tracking.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .types import NoteEvent

log = logging.getLogger(__name__)
_model_cache: dict[str, object] = {}


def available() -> bool:
    try:
        _load_model()
        return True
    except Exception:
        return False


def _load_model():
    model = _model_cache.get("basic_pitch")
    if model is None:
        # basic_pitch warns at import time about every runtime it can't find.
        previous = logging.root.manager.disable
        logging.disable(logging.WARNING)
        try:
            from basic_pitch import ICASSP_2022_MODEL_PATH
            from basic_pitch.inference import Model
        finally:
            logging.disable(previous)
        onnx_path = Path(ICASSP_2022_MODEL_PATH)
        if onnx_path.suffix != ".onnx":
            onnx_path = onnx_path.parent / "nmp.onnx"
        model = Model(onnx_path if onnx_path.exists() else ICASSP_2022_MODEL_PATH)
        _model_cache["basic_pitch"] = model
    return model


def transcribe(
    path: Path,
    min_freq: float | None = None,
    max_freq: float | None = None,
    onset_threshold: float = 0.5,
    frame_threshold: float = 0.3,
    min_note_ms: float = 100.0,
) -> list[NoteEvent]:
    from basic_pitch.inference import predict

    model = _load_model()
    _, _, note_events = predict(
        str(path),
        model,
        onset_threshold=onset_threshold,
        frame_threshold=frame_threshold,
        minimum_note_length=min_note_ms,
        minimum_frequency=min_freq,
        maximum_frequency=max_freq,
        multiple_pitch_bends=False,
        melodia_trick=True,
    )
    out = []
    for start, end, pitch, amplitude, _bends in note_events:
        out.append(NoteEvent(float(start), float(end), int(pitch), confidence=float(amplitude), velocity=float(amplitude)))
    out.sort(key=lambda n: (n.start, n.pitch))
    return out
