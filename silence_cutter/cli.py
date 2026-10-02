from __future__ import annotations

import argparse
import json
from pathlib import Path

from .core import (
    parse_silencedetect, probe_duration, run_silencedetect, speech_segments, total_length,
)
from .script import build_cues, to_markdown, to_srt


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="silence-cutter",
        description="Corta silencios y genera un guión con los tiempos del video recortado.",
    )
    p.add_argument("media", help="video o audio de entrada")
    p.add_argument("--noise", type=float, default=-30.0, help="umbral de silencio en dB (def. -30)")
    p.add_argument("--min-silence", type=float, default=0.5, help="silencio mínimo a cortar, en s (def. 0.5)")
    p.add_argument("--padding", type=float, default=0.1, help="holgura conservada junto al habla, en s (def. 0.1)")
    p.add_argument("--min-speech", type=float, default=0.15, help="descarta tramos hablados más cortos, en s")
    p.add_argument("--model", default="small", help="modelo de Whisper (def. small)")
    p.add_argument("--language", default=None, help="idioma, ej. es (def. autodetectar)")
    p.add_argument("--no-transcribe", action="store_true", help="solo cortar, sin guión")
    p.add_argument("--resolve", action="store_true", help="crear la timeline recortada en DaVinci Resolve")
    p.add_argument("--out", default=None, help="carpeta de salida (def. junto al archivo)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    media = Path(args.media)
    if not media.is_file():
        raise SystemExit(f"No existe: {media}")
    out = Path(args.out) if args.out else media.parent
    out.mkdir(parents=True, exist_ok=True)

    duration = probe_duration(str(media))
    stderr = run_silencedetect(str(media), args.noise, args.min_silence)
    silences = parse_silencedetect(stderr, duration)
    segments = speech_segments(silences, duration, args.padding, args.min_speech)
    kept = total_length(segments)
    print(f"Duración: {duration:.1f}s -> {kept:.1f}s ({len(segments)} tramos, "
          f"-{duration - kept:.1f}s de silencio)")

    seg_file = out / f"{media.stem}.segments.json"
    seg_file.write_text(
        json.dumps([{"start": s.start, "end": s.end} for s in segments], indent=2),
        encoding="utf-8",
    )
    print(f"Tramos: {seg_file}")

    if not args.no_transcribe:
        from .transcribe import transcribe

        cues = build_cues(transcribe(str(media), args.model, args.language), segments)
        (out / f"{media.stem}.srt").write_text(to_srt(cues), encoding="utf-8")
        (out / f"{media.stem}.guion.md").write_text(to_markdown(cues, media.stem), encoding="utf-8")
        print(f"Guión: {out / (media.stem + '.guion.md')} y .srt ({len(cues)} líneas)")

    if args.resolve:
        from .resolve_integration import build_timeline

        name = build_timeline(str(media), segments, f"{media.stem} - sin silencios")
        print(f"Timeline creada en Resolve: {name}")
    return 0
