"""Construye en DaVinci Resolve una timeline nueva solo con los tramos hablados.

Requiere correr con el Python que Resolve expone (Preferences > System > General >
External scripting using = Local) y con DaVinciResolveScript importable.
"""

from __future__ import annotations

import os
import sys

from .core import Interval

_MODULE_DIRS = {
    "win32": r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules",
    "darwin": "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules",
    "linux": "/opt/resolve/Developer/Scripting/Modules",
}


def _load_resolve():
    path = os.environ.get("RESOLVE_SCRIPT_API")
    modules = os.path.join(path, "Modules") if path else _MODULE_DIRS.get(sys.platform, "")
    if modules and modules not in sys.path:
        sys.path.append(modules)
    try:
        import DaVinciResolveScript as dvr
    except ImportError as exc:
        raise SystemExit(
            "No encuentro DaVinciResolveScript. Define RESOLVE_SCRIPT_API o revisa "
            "que Resolve esté instalado y el scripting externo en 'Local'."
        ) from exc
    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        raise SystemExit("No pude conectar con Resolve: ábrelo antes de correr el script.")
    return resolve


def build_timeline(media_path: str, segments: list[Interval], name: str) -> str:
    resolve = _load_resolve()
    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None:
        raise SystemExit("Abre un proyecto en Resolve antes de continuar.")
    pool = project.GetMediaPool()

    clips = pool.ImportMedia([os.path.abspath(media_path)])
    if not clips:
        raise SystemExit(f"Resolve no pudo importar {media_path}")
    clip = clips[0]
    fps = float(clip.GetClipProperty("FPS") or 24)

    timeline = pool.CreateEmptyTimeline(name)
    if timeline is None:
        raise SystemExit(f"No pude crear la timeline '{name}' (¿ya existe?).")
    project.SetCurrentTimeline(timeline)

    items = []
    for seg in segments:
        start = int(round(seg.start * fps))
        end = max(start, int(round(seg.end * fps)) - 1)  # endFrame es inclusivo
        items.append({"mediaPoolItem": clip, "startFrame": start, "endFrame": end})
    if not pool.AppendToTimeline(items):
        raise SystemExit("Resolve rechazó los recortes al agregarlos a la timeline.")
    return name
