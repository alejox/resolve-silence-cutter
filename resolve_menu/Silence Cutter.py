"""Script para el menú Workspace > Scripts de DaVinci Resolve.

Instalación: copia este archivo a la carpeta Scripts/Edit de Resolve y define
SILENCE_CUTTER_HOME con la ruta de este repositorio (o edita HOME aquí abajo).

Uso: abre una timeline con el clip a limpiar en la pista V1 y ejecútalo desde
Workspace > Scripts > Edit > Silence Cutter. Crea una timeline nueva sin silencios
y deja el guión (.guion.md y .srt) junto al archivo original. Si defines
SILENCE_CUTTER_OVERLAYS (ruta al overlays.manifest.json), coloca los overlays en V2. El resultado queda
en `Silence Cutter.log`, porque el menú no muestra una consola.
"""

import os
import sys
import traceback

HOME = os.environ.get("SILENCE_CUTTER_HOME", "")
NOISE_DB = -30.0
MIN_SILENCE = 0.5
PADDING = 0.1
MIN_SPEECH = 0.15
WHISPER_MODEL = "small"
LANGUAGE = None  # ej. "es"; None = autodetectar
TRANSCRIBE = True
# Cortes por contenido con Claude (necesita ANTHROPIC_API_KEY). Dos pasadas:
#   1) ANALYZE = True  -> escribe <video>.cortes.json / .cortes.md para revisar, no corta nada
#   2) ANALYZE = False y SILENCE_CUTTER_CUTS=<ruta al .cortes.json> -> aplica los aprobados
ANALYZE = False
CUTS_FILE = os.environ.get("SILENCE_CUTTER_CUTS", "")
AI_MODEL = None  # None = el predeterminado
MAX_CUT = 0.5  # fracción máxima de palabras que se pueden cortar
# manifiesto de overlays de Remotion (render-overlays.mjs); "" = sin overlays
OVERLAYS_MANIFEST = os.environ.get("SILENCE_CUTTER_OVERLAYS", "")

# Resolve no hereda el PATH de la terminal en macOS: ffmpeg de Homebrew no se encontraría.
os.environ["PATH"] += os.pathsep + os.pathsep.join(["/opt/homebrew/bin", "/usr/local/bin"])


def _log_path():
    return os.path.join(HOME or os.path.expanduser("~"), "Silence Cutter.log")


def run(resolve):
    from pathlib import Path

    from silence_cutter.core import total_length
    from silence_cutter.edit import InvalidDecisions
    from silence_cutter.pipeline import (
        analyze, apply_cuts, detect_segments, get_words, load_words, words_file,
    )
    from silence_cutter.resolve_integration import build_timeline
    from silence_cutter.script import build_cues, to_markdown, to_srt

    project = resolve.GetProjectManager().GetCurrentProject()
    timeline = project.GetCurrentTimeline() if project else None
    if timeline is None:
        return "Abre una timeline primero."
    items = timeline.GetItemListInTrack("video", 1) or []
    if not items:
        return "La pista V1 está vacía."
    media = items[0].GetMediaPoolItem().GetClipProperty("File Path")
    if not media or not os.path.isfile(media):
        return "No encuentro el archivo del primer clip: %r" % media

    out = Path(media).parent
    stem = Path(media).stem
    duration, segments = detect_segments(media, NOISE_DB, MIN_SILENCE, PADDING, MIN_SPEECH)

    if ANALYZE:  # paso 1: Claude propone, una persona revisa; no se corta nada
        cuts, report, n = analyze(media, out, stem, WHISPER_MODEL, LANGUAGE, AI_MODEL, MAX_CUT)
        return ("Claude propone %d cortes. Revisa %s y edita %s ('apply': false conserva un corte). "
                "Luego define SILENCE_CUTTER_CUTS con esa ruta y ejecuta de nuevo (ANALYZE = False)."
                % (n, report, cuts))

    words = None
    if CUTS_FILE:  # paso 2: aplicar los cortes aprobados
        wf = words_file(out, stem)
        if not wf.is_file():
            return "Falta %s: ejecuta primero con ANALYZE = True." % wf
        words = load_words(wf)
        try:
            segments = apply_cuts(segments, Path(CUTS_FILE), words, MIN_SPEECH, MAX_CUT)
        except InvalidDecisions as exc:
            return "Los cortes no son válidos:\n- " + "\n- ".join(exc.errors)

    msg = "%.1fs -> %.1fs (%d tramos)" % (duration, total_length(segments), len(segments))

    if TRANSCRIBE:
        words = words or get_words(media, out, stem, WHISPER_MODEL, LANGUAGE)
        cues = build_cues(words, segments)
        (out / (stem + ".srt")).write_text(to_srt(cues), encoding="utf-8")
        (out / (stem + ".guion.md")).write_text(to_markdown(cues, stem), encoding="utf-8")
        msg += "; guión con %d líneas" % len(cues)

    placements = None
    if OVERLAYS_MANIFEST:
        from silence_cutter.overlays import load_manifest, place_overlays

        placements, skipped = place_overlays(load_manifest(OVERLAYS_MANIFEST), segments)
        msg += "; overlays %d ubicados, %d omitidos" % (len(placements), len(skipped))

    name = build_timeline(media, segments, stem + " - sin silencios", resolve, placements)
    return "Listo: %s. Timeline '%s'." % (msg, name)


try:
    if HOME and HOME not in sys.path:
        sys.path.insert(0, HOME)
    result = run(resolve)  # noqa: F821 - `resolve` lo inyecta Resolve
except SystemExit as exc:  # los módulos avisan con SystemExit("mensaje claro")
    result = str(exc.code) if exc.code else "Terminó sin mensaje."
except BaseException:
    result = traceback.format_exc()
with open(_log_path(), "w", encoding="utf-8") as _f:
    _f.write(result + "\n")
