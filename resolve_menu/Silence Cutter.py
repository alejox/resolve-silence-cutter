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
# manifiesto de overlays de Remotion (render-overlays.mjs); "" = sin overlays
OVERLAYS_MANIFEST = os.environ.get("SILENCE_CUTTER_OVERLAYS", "")

# Resolve no hereda el PATH de la terminal en macOS: ffmpeg de Homebrew no se encontraría.
os.environ["PATH"] += os.pathsep + os.pathsep.join(["/opt/homebrew/bin", "/usr/local/bin"])


def _log_path():
    return os.path.join(HOME or os.path.expanduser("~"), "Silence Cutter.log")


def run(resolve):
    from silence_cutter.core import (
        parse_silencedetect, probe_duration, run_silencedetect, speech_segments, total_length,
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

    duration = probe_duration(media)
    silences = parse_silencedetect(run_silencedetect(media, NOISE_DB, MIN_SILENCE), duration)
    segments = speech_segments(silences, duration, PADDING, MIN_SPEECH)
    stem = os.path.splitext(media)[0]
    msg = "%.1fs -> %.1fs (%d tramos)" % (duration, total_length(segments), len(segments))

    if TRANSCRIBE:
        from silence_cutter.transcribe import transcribe

        cues = build_cues(transcribe(media, WHISPER_MODEL, LANGUAGE), segments)
        with open(stem + ".srt", "w", encoding="utf-8") as f:
            f.write(to_srt(cues))
        with open(stem + ".guion.md", "w", encoding="utf-8") as f:
            f.write(to_markdown(cues, os.path.basename(stem)))
        msg += "; guión con %d líneas" % len(cues)

    placements = None
    if OVERLAYS_MANIFEST:
        from silence_cutter.overlays import load_manifest, place_overlays

        placements, skipped = place_overlays(load_manifest(OVERLAYS_MANIFEST), segments)
        msg += "; overlays %d ubicados, %d omitidos" % (len(placements), len(skipped))

    name = build_timeline(
        media, segments, os.path.basename(stem) + " - sin silencios", resolve, placements
    )
    return "Listo: %s. Timeline '%s'." % (msg, name)


try:
    if HOME and HOME not in sys.path:
        sys.path.insert(0, HOME)
    result = run(resolve)  # noqa: F821 - `resolve` lo inyecta Resolve
except BaseException:  # SystemExit incluido: los módulos salen con SystemExit
    result = traceback.format_exc()
with open(_log_path(), "w", encoding="utf-8") as _f:
    _f.write(result + "\n")
