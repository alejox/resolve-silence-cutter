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
    for _ in range(track):  # acotado: si AddTrack falla no queda en bucle
        if timeline.GetTrackCount("video") >= track:
            break
        if not timeline.AddTrack("video"):
            raise SystemExit(f"No pude agregar la pista de video V{track} en Resolve.")

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


PIP_SCALE = 0.28  # tamaño del canal lateral respecto al cuadro
PIP_MARGIN = 0.03  # margen respecto al borde, como fracción del cuadro


def pip_properties(side_pos: str, width: int, height: int) -> dict:
    """Escala y posición del canal lateral, abajo a la derecha (o izquierda).

    Pan/Tilt de Resolve son píxeles desde el centro; Tilt positivo sube la imagen.
    """
    w, h = width * PIP_SCALE, height * PIP_SCALE
    pan = width / 2 - w / 2 - width * PIP_MARGIN
    tilt = height / 2 - h / 2 - height * PIP_MARGIN
    return {
        "ZoomX": PIP_SCALE, "ZoomY": PIP_SCALE,
        "Pan": pan if side_pos == "right" else -pan,
        "Tilt": -tilt,
    }


def build_multicam_timeline(project, pieces, name: str, resolve=None, placements=None) -> str:
    """Timeline con el audio maestro en A1 y, por trozo, el plano elegido en V1 (+ lateral en V2).

    Los clips de imagen entran SIN audio (mediaType 1): el sonido sale solo del canal maestro,
    así no se duplica la voz ni suena la cámara por detrás de la pantalla.
    """
    resolve = resolve or _load_resolve()
    proj = resolve.GetProjectManager().GetCurrentProject()
    if proj is None:
        raise SystemExit("Abre un proyecto en Resolve antes de continuar.")
    pool = proj.GetMediaPool()

    files = {os.path.abspath(s.file): s.name for s in project.sources.values()}
    imported = pool.ImportMedia(list(files)) or []
    clips = {}
    for c in imported:
        path = os.path.abspath(c.GetClipProperty("File Path") or "")
        if path in files:
            clips[files[path]] = c
    missing = sorted(set(project.sources) - set(clips))
    if missing:
        raise SystemExit(f"Resolve no importó estos canales: {', '.join(missing)}")

    timeline = pool.CreateEmptyTimeline(name)
    if timeline is None:
        raise SystemExit(f"No pude crear la timeline '{name}' (¿ya existe?).")
    proj.SetCurrentTimeline(timeline)

    tl_fps = float(timeline.GetSetting("timelineFrameRate") or 30)
    width = int(timeline.GetSetting("timelineResolutionWidth") or 1920)
    height = int(timeline.GetSetting("timelineResolutionHeight") or 1080)
    origin = timeline.GetStartFrame()
    needs_pip = any(p.shot.layout == "pip" for p in pieces)
    top = 3 if placements else (2 if needs_pip else 1)
    for _ in range(top):
        if timeline.GetTrackCount("video") >= top:
            break
        if not timeline.AddTrack("video"):
            raise SystemExit(f"No pude agregar la pista de video V{top} en Resolve.")

    def fps_of(src_name: str) -> float:
        return float(clips[src_name].GetClipProperty("FPS") or tl_fps)

    infos, pip_of = [], {}
    cum = 0.0
    for piece in pieces:
        length = piece.interval.length
        rec = origin + int(round(cum * tl_fps))
        frames_tl = int(round((cum + length) * tl_fps)) - int(round(cum * tl_fps))
        if frames_tl < 1:
            cum += length
            continue

        def clip_info(src_name: str, track: int, media_type: int) -> dict:
            src = project.sources[src_name]
            f = fps_of(src_name)
            t0 = piece.play_from if src.role == "product" else piece.interval.start + src.offset
            start = int(round(t0 * f))
            return {
                "mediaPoolItem": clips[src_name], "startFrame": start,
                "endFrame": start + max(1, int(round(length * f))) - 1,
                "mediaType": media_type, "trackIndex": track, "recordFrame": rec,
            }

        infos.append(clip_info(project.audio, 1, 2))  # voz continua desde el maestro
        shot = piece.shot
        if shot.layout == "full":
            infos.append(clip_info(shot.source, 1, 1))
        else:
            infos.append(clip_info(shot.main, 1, 1))
            pip_of[len(infos)] = shot.side_pos
            infos.append(clip_info(shot.side, 2, 1))
        cum += length

    result = pool.AppendToTimeline(infos)
    if not result:
        raise SystemExit("Resolve rechazó los clips al armar la timeline multicámara.")
    if pip_of:
        if not isinstance(result, list) or len(result) != len(infos):
            print("Aviso: Resolve no devolvió los clips; el lateral queda sin escalar/mover.", file=sys.stderr)
        else:
            for idx, pos in pip_of.items():
                for key, value in pip_properties(pos, width, height).items():
                    result[idx].SetProperty(key, value)
    if placements:
        _place_overlays(proj, pool, timeline, placements, 3)
    return name
