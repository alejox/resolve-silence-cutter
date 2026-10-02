"""Transcripción con faster-whisper (dependencia opcional)."""

from __future__ import annotations

from .script import Word


def transcribe(path: str, model: str = "small", language: str | None = None) -> list[Word]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise SystemExit(
            "Falta faster-whisper. Instalalo con: pip install faster-whisper\n"
            "o corré con --no-transcribe para solo cortar."
        ) from exc

    engine = WhisperModel(model, compute_type="int8")
    segments, _info = engine.transcribe(path, language=language, word_timestamps=True)
    words: list[Word] = []
    for seg in segments:
        for w in seg.words or []:
            text = w.word.strip()
            if text:
                words.append(Word(w.start, w.end, text))
    return words
