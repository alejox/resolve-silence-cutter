from __future__ import annotations

import argparse
import json
from pathlib import Path

from .core import total_length
from .edit import InvalidDecisions
from .pipeline import analyze, apply_cuts, detect_segments, get_words, load_words, words_file
from .script import build_cues, to_markdown, to_srt


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="silence-cutter",
        description="Corta silencios (y, con IA, lo que no aporta) y genera un guión con los tiempos del video recortado.",
    )
    p.add_argument("media", help="video o audio de entrada")
    p.add_argument("--noise", type=float, default=-30.0, help="umbral de silencio en dB (def. -30)")
    p.add_argument("--min-silence", type=float, default=0.5, help="silencio mínimo a cortar, en s (def. 0.5)")
    p.add_argument("--padding", type=float, default=0.1, help="holgura conservada junto al habla, en s (def. 0.1)")
    p.add_argument("--min-speech", type=float, default=0.15, help="descarta tramos hablados más cortos, en s")
    p.add_argument("--model", default="small", help="modelo de Whisper (def. small)")
    p.add_argument("--language", default=None, help="idioma, ej. es (def. autodetectar)")
    p.add_argument("--no-transcribe", action="store_true", help="solo cortar, sin guión")
    p.add_argument("--analyze", action="store_true",
                   help="pide a Claude cortes por contenido (tomas repetidas, muletillas...) y escribe <video>.cortes.json para revisar; no corta nada")
    p.add_argument("--apply-cuts", default=None, metavar="CORTES.JSON",
                   help="aplica los cortes aprobados (los 'apply': true) además de los silencios")
    p.add_argument("--ai-model", default=None, help="modelo de Claude para --analyze")
    p.add_argument("--max-cut", type=float, default=0.5, help="fracción máxima de palabras que se pueden cortar (def. 0.5)")
    p.add_argument("--resolve", action="store_true", help="crear la timeline recortada en DaVinci Resolve (requiere Studio)")
    p.add_argument("--overlays", default=None, help="overlays.manifest.json de render-overlays.mjs (Remotion); se colocan en V2 con --resolve")
    p.add_argument("--out", default=None, help="carpeta de salida (def. junto al archivo)")
    return p


def main(argv: list[str] | None = None) -> int:
    import sys

    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "multicam":  # python -m silence_cutter multicam proyecto.json ...
        from .multicam_cli import main as multicam_main

        return multicam_main(argv[1:])
    args = _parser().parse_args(argv)
    media = Path(args.media)
    if not media.is_file():
        raise SystemExit(f"No existe: {media}")
    out = Path(args.out) if args.out else media.parent
    out.mkdir(parents=True, exist_ok=True)

    duration, segments = detect_segments(
        str(media), args.noise, args.min_silence, args.padding, args.min_speech
    )

    if args.analyze:
        cuts_file, report, n = analyze(
            str(media), out, media.stem, args.model, args.language,
            args.ai_model, args.max_cut,
        )
        print(f"Claude propone {n} cortes.\n  Revisa: {report}\n  Edita:  {cuts_file} ('apply': false conserva un corte)")
        print(f"Luego: python -m silence_cutter {media} --apply-cuts {cuts_file}")
        return 0

    words = None
    if args.apply_cuts:
        wf = words_file(out, media.stem)
        if not wf.is_file():
            raise SystemExit(f"Falta {wf}: corre primero --analyze sobre este mismo archivo.")
        words = load_words(wf)
        try:
            segments = apply_cuts(segments, Path(args.apply_cuts), words, args.min_speech, args.max_cut)
        except InvalidDecisions as exc:
            raise SystemExit("Los cortes no son válidos:\n- " + "\n- ".join(exc.errors)) from exc

    kept = total_length(segments)
    print(f"Duración: {duration:.1f}s -> {kept:.1f}s ({len(segments)} tramos, "
          f"-{duration - kept:.1f}s eliminados)")

    seg_file = out / f"{media.stem}.segments.json"
    seg_file.write_text(
        json.dumps([{"start": s.start, "end": s.end} for s in segments], indent=2),
        encoding="utf-8",
    )
    print(f"Tramos: {seg_file}")

    if not args.no_transcribe:
        words = words or get_words(str(media), out, media.stem, args.model, args.language)
        cues = build_cues(words, segments)
        (out / f"{media.stem}.srt").write_text(to_srt(cues), encoding="utf-8")
        (out / f"{media.stem}.guion.md").write_text(to_markdown(cues, media.stem), encoding="utf-8")
        print(f"Guión: {out / (media.stem + '.guion.md')} y .srt ({len(cues)} líneas)")

    placements = None
    if args.overlays:
        from .overlays import load_manifest, place_overlays

        placements, skipped = place_overlays(load_manifest(args.overlays), segments)
        print(f"Overlays: {len(placements)} ubicados, {len(skipped)} omitidos (caen en un corte)")
        for it in skipped:
            print(f"  omitido: {it.get('type', '?')} en {it['at']}s")
        for pl in placements:
            print(f"  {pl.type or pl.file}: {pl.start:.2f}s por {pl.duration:.2f}s")

    if args.resolve:
        from .resolve_integration import build_timeline

        name = build_timeline(
            str(media), segments, f"{media.stem} - sin silencios", placements=placements
        )
        print(f"Timeline creada en Resolve: {name}")
    return 0
