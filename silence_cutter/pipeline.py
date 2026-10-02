"""Pasos compartidos por la línea de comandos y el script del menú de Resolve."""

from __future__ import annotations

import json
from pathlib import Path

from .core import (
    Interval, auto_threshold, probe_duration, rms_levels, silences_from_levels, speech_segments,
)
from .edit import (
    cuts_to_intervals, proposal_from_json, proposal_to_json, proposal_to_markdown,
    subtract, validate,
)
from .script import Word


def detect_segments_info(
    media: str, noise: float | None, min_silence: float, padding: float, min_speech: float
) -> tuple[float, list[Interval], float]:
    """`noise` en dB, o None para calcularlo del propio audio. Devuelve (duración, tramos, umbral usado)."""
    duration = probe_duration(media)
    levels = rms_levels(media)
    threshold = auto_threshold(levels) if noise is None else noise
    silences = silences_from_levels(levels, threshold, min_silence, duration)
    return duration, speech_segments(silences, duration, padding, min_speech), threshold


def detect_segments(
    media: str, noise: float | None, min_silence: float, padding: float, min_speech: float
) -> tuple[float, list[Interval]]:
    duration, segments, _ = detect_segments_info(media, noise, min_silence, padding, min_speech)
    return duration, segments


def words_file(out: Path, stem: str) -> Path:
    return out / f"{stem}.words.json"


def save_words(path: Path, words: list[Word]) -> None:
    path.write_text(
        json.dumps([{"start": w.start, "end": w.end, "text": w.text} for w in words], ensure_ascii=False),
        encoding="utf-8",
    )


def load_words(path: Path) -> list[Word]:
    return [Word(d["start"], d["end"], d["text"]) for d in json.loads(path.read_text(encoding="utf-8"))]


def get_words(
    media: str, out: Path, stem: str, model: str, language: str | None
) -> list[Word]:
    """Transcribe una sola vez: las palabras quedan en `<stem>.words.json`.

    Importa: los índices de palabra que usa `--apply-cuts` solo valen para ESA transcripción.
    """
    cache = words_file(out, stem)
    if cache.is_file():
        return load_words(cache)
    from .transcribe import transcribe

    words = transcribe(media, model, language)
    save_words(cache, words)
    return words


def analyze(
    media: str, out: Path, stem: str, model: str,
    language: str | None, ai_model: str | None, max_cut: float, caller=None,
) -> tuple[Path, Path, int]:
    """Pide cortes a Claude y escribe la propuesta para revisar. No toca el video."""
    from . import ai

    words = get_words(media, out, stem, model, language)
    kwargs = {"caller": caller} if caller else {}
    decisions = ai.propose_cuts(words, ai_model, max_cut, **kwargs)
    removed = sum(i.length for i in cuts_to_intervals(decisions, words))
    cuts_file = out / f"{stem}.cortes.json"
    report = out / f"{stem}.cortes.md"
    cuts_file.write_text(
        proposal_to_json(decisions, words, media, ai_model or ai.DEFAULT_MODEL), encoding="utf-8"
    )
    report.write_text(proposal_to_markdown(decisions, words, stem, removed), encoding="utf-8")
    return cuts_file, report, len(decisions)


def apply_cuts(
    segments: list[Interval], cuts_path: Path, words: list[Word],
    min_speech: float, max_cut: float,
) -> list[Interval]:
    """Resta de los tramos hablados los cortes aprobados (`apply: true`)."""
    decisions = proposal_from_json(cuts_path.read_text(encoding="utf-8"))
    validate(decisions, len(words), max_cut)
    return subtract(segments, cuts_to_intervals(decisions, words), min_speech)
