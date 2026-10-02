"""Ubica los overlays de Remotion sobre la timeline recortada.

Los beats viven en segundos del archivo ORIGINAL (`at`); tras cortar silencios esos
instantes se mueven. Aquí se convierten a la posición real en la versión recortada.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .core import Interval, remap_time


@dataclass(frozen=True)
class Placement:
    file: str
    start: float  # segundos sobre la timeline recortada
    duration: float
    type: str = ""


def load_manifest(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        items = json.load(f)
    for i, it in enumerate(items):
        for key in ("file", "at", "dur"):
            if key not in it:
                raise ValueError(f"El manifiesto no tiene '{key}' en el elemento {i}")
    return items


def place_overlays(
    manifest: list[dict], segments: list[Interval]
) -> tuple[list[Placement], list[dict]]:
    """Devuelve (colocados, omitidos).

    Un beat cuyo `at` cae en un tramo eliminado se omite en vez de moverlo a ojo: el
    texto estaba atado a algo que ya no está en el video. Si el beat empieza en un tramo
    pero se extiende más allá de su final, se recorta a lo que queda del tramo.
    """
    placed: list[Placement] = []
    skipped: list[dict] = []
    for it in manifest:
        start = remap_time(float(it["at"]), segments)
        if start is None:
            skipped.append(it)
            continue
        seg = next(s for s in segments if s.start <= float(it["at"]) <= s.end)
        available = seg.end - float(it["at"])
        placed.append(
            Placement(it["file"], start, min(float(it["dur"]), available), it.get("type", ""))
        )
    return placed, skipped
