"""Audio → piano arrangement engine.

Stages: audio (ingest) → separate → analyze (beats, pitch, transcribe, chords,
keydetect) → arrange → notate. `pipeline.run` chains them; `pipeline.render`
re-arranges an existing analysis without touching audio.
"""
