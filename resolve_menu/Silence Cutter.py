"""Script para el menú Workspace > Scripts de DaVinci Resolve.

Instalación: copia este archivo a la carpeta Scripts/Edit de Resolve y define
SILENCE_CUTTER_HOME con la ruta de este repositorio (o edita HOME aquí abajo).

Uso: abre una timeline con el clip a limpiar en la pista V1 y ejecútalo desde
Workspace > Scripts > Edit > Silence Cutter. Crea una timeline nueva sin silencios
y deja el guión (.guion.md y .srt) junto al archivo original. El resultado queda
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

    name = build_timeline(media, segments, os.path.basename(stem) + " - sin silencios", resolve)
    return "Listo: %s. Timeline '%s'." % (msg, name)


try:
    if HOME and HOME not in sys.path:
        sys.path.insert(0, HOME)
    result = run(resolve)  # noqa: F821 - `resolve` lo inyecta Resolve
except BaseException:  # SystemExit incluido: los módulos salen con SystemExit
    result = traceback.format_exc()
with open(_log_path(), "w", encoding="utf-8") as _f:
    _f.write(result + "\n")
