"""Construye en DaVinci Resolve una timeline nueva solo con los tramos hablados.

Requiere correr con el Python que Resolve expone (Preferences > System > General >
External scripting using = Local) y con DaVinciResolveScript importable.
"""

from __future__ import annotations

import os
import sys

from .core import Interval
from .overlays import Placement

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


def build_timeline(
    media_path: str,
    segments: list[Interval],
    name: str,
    resolve=None,
    placements: list[Placement] | None = None,
    overlay_track: int = 2,
) -> str:
    """`resolve` ya viene resuelto cuando corre desde el menú Workspace > Scripts."""
    resolve = resolve or _load_resolve()
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
    if placements:
        _place_overlays(project, pool, timeline, placements, overlay_track)
    return name


def _place_overlays(project, pool, timeline, placements, track: int) -> None:
    """Importa los clips con alfa y los coloca en `track` en su instante exacto.

    `recordFrame` es absoluto: incluye el frame inicial de la timeline (p. ej. 01:00:00:00).
    """
    fps = float(timeline.GetSetting("timelineFrameRate") or 30)
    origin = timeline.GetStartFrame()
    while timeline.GetTrackCount("video") < track:
        timeline.AddTrack("video")

    clips = pool.ImportMedia([os.path.abspath(p.file) for p in placements])
    by_name = {c.GetClipProperty("File Name"): c for c in clips or []}
    infos = []
    for p in placements:
        clip = by_name.get(os.path.basename(p.file))
        if clip is None:
            print(f"Aviso: Resolve no importó {p.file}; se omite.", file=sys.stderr)
            continue
        clip_fps = float(clip.GetClipProperty("FPS") or fps)
        frames = max(1, int(round(p.duration * clip_fps)))
        infos.append({
            "mediaPoolItem": clip,
            "startFrame": 0,
            "endFrame": frames - 1,
            "mediaType": 1,  # solo video
            "trackIndex": track,
            "recordFrame": origin + int(round(p.start * fps)),
        })
    if infos and not pool.AppendToTimeline(infos):
        raise SystemExit("Resolve rechazó los overlays al colocarlos en la timeline.")
