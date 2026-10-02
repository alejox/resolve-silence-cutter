"""Plan de planos: qué canal se ve en cada momento.

Un plano es un CAMBIO: empieza en la palabra `start` y dura hasta el siguiente plano.
- full: un canal a pantalla completa.
- pip: un canal principal con otro pequeño al costado (p. ej. la pantalla con la cámara).

Capa pura y determinista, sin Claude ni Resolve: valida lo que venga de un modelo o de una
persona antes de que toque la timeline.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .core import Interval
from .edit import InvalidDecisions
from .project import Project
from .script import Word

LAYOUTS = ("full", "pip")
POSITIONS = ("right", "left")


@dataclass(frozen=True)
class Shot:
    start: int  # índice de la palabra donde empieza
    layout: str
    source: str = ""  # full
    main: str = ""  # pip
    side: str = ""  # pip
    side_pos: str = "right"
    reason: str = ""

    def sources(self) -> list[str]:
        return [self.source] if self.layout == "full" else [self.main, self.side]


@dataclass(frozen=True)
class Piece:
    """Un trozo continuo de la timeline final con un solo plano."""

    interval: Interval  # tiempos del maestro
    shot: Shot
    shot_index: int
    play_from: float  # segundos ya reproducidos de este plano antes del trozo (para tomas de producto)


def parse_shots(raw: list[dict]) -> list[Shot]:
    errors: list[str] = []
    out: list[Shot] = []
    for i, d in enumerate(raw):
        try:
            start = d["start"]
            if isinstance(start, bool) or not isinstance(start, int):
                raise TypeError("start debe ser entero")
            out.append(Shot(
                start, str(d.get("layout", "full")), str(d.get("source", "")),
                str(d.get("main", "")), str(d.get("side", "")),
                str(d.get("side_pos", "right")), str(d.get("reason", "")).strip(),
            ))
        except (KeyError, TypeError) as exc:
            errors.append(f"plano {i}: {exc}")
    if errors:
        raise InvalidDecisions(errors)
    return out


def default_shot(project: Project) -> Shot:
    return Shot(0, "full", source=project.default_source, reason="plano por defecto")


def with_opening(shots: list[Shot], project: Project) -> list[Shot]:
    """Si el primer plano no arranca en la palabra 0, el inicio usa el plano por defecto."""
    ordered = sorted(shots, key=lambda s: s.start)
    return ordered if ordered and ordered[0].start == 0 else [default_shot(project), *ordered]


def validate(shots: list[Shot], words: list[Word], project: Project, total: float) -> None:
    """Lanza InvalidDecisions con TODOS los problemas (sirve para reintentar con el modelo)."""
    errors: list[str] = []
    names = set(project.sources)
    for i, s in enumerate(shots):
        if not (0 <= s.start < len(words)):
            errors.append(f"plano {i}: la palabra {s.start} no existe (0-{len(words) - 1})")
        if s.layout not in LAYOUTS:
            errors.append(f"plano {i}: layout '{s.layout}' no es uno de {', '.join(LAYOUTS)}")
            continue
        used = s.sources()
        if "" in used:
            errors.append(f"plano {i}: faltan canales para el layout '{s.layout}'")
            continue
        for n in used:
            if n not in names:
                errors.append(f"plano {i}: el canal '{n}' no existe (hay: {', '.join(sorted(names))})")
            elif project.sources[n].role == "audio":
                errors.append(f"plano {i}: '{n}' es solo audio y no se puede mostrar")
        if s.layout == "pip":
            if s.main == s.side:
                errors.append(f"plano {i}: el principal y el lateral son el mismo canal")
            if s.side_pos not in POSITIONS:
                errors.append(f"plano {i}: side_pos '{s.side_pos}' no es uno de {', '.join(POSITIONS)}")
            if any(n in names and project.sources[n].role == "product" for n in (s.side,)):
                errors.append(f"plano {i}: una toma de producto no va como lateral")
    starts = [s.start for s in shots]
    if any(b <= a for a, b in zip(starts, starts[1:])):
        errors.append("los planos deben estar ordenados por 'start' y sin repetir palabra")
    if errors:
        raise InvalidDecisions(errors)

    # una toma de producto no puede durar más que su archivo
    ordered = with_opening(shots, project)
    for i, s in enumerate(ordered):
        for n in s.sources():
            src = project.sources[n]
            if src.role != "product" or n not in project.durations:
                continue
            end = words[ordered[i + 1].start].start if i + 1 < len(ordered) else total
            length = end - words[s.start].start
            if length > project.durations[n] + 0.05:
                errors.append(
                    f"plano {i}: '{n}' dura {project.durations[n]:.1f}s pero el plano dura {length:.1f}s; "
                    "agrega un cambio de plano antes o usa otro canal"
                )
    if errors:
        raise InvalidDecisions(errors)


def split_into_pieces(
    segments: list[Interval], shots: list[Shot], words: list[Word], project: Project
) -> list[Piece]:
    """Parte los tramos conservados en cada cambio de plano.

    Para tomas de producto, `play_from` acumula solo el tiempo CONSERVADO: si un corte cae
    en medio, la toma sigue donde iba en vez de saltarse un trozo.
    """
    ordered = with_opening(shots, project)
    times = [words[s.start].start for s in ordered]
    pieces: list[Piece] = []
    played = [0.0] * len(ordered)
    for seg in segments:
        cursor = seg.start
        while cursor < seg.end:
            idx = max(i for i, t in enumerate(times) if t <= cursor or i == 0)
            nxt = times[idx + 1] if idx + 1 < len(times) else float("inf")
            end = min(seg.end, nxt)
            if end > cursor:
                pieces.append(Piece(Interval(cursor, end), ordered[idx], idx, played[idx]))
                played[idx] += end - cursor
            cursor = end
    return pieces


def check_sync_range(pieces: list[Piece], project: Project) -> None:
    """Falla si un canal sincronizado no tiene imagen en algún momento que se le pide."""
    errors = []
    for p in pieces:
        for n in p.shot.sources():
            src = project.sources[n]
            if src.role == "product" or n not in project.durations or n == project.audio:
                continue
            t0, t1 = p.interval.start + src.offset, p.interval.end + src.offset
            if t0 < -0.01 or t1 > project.durations[n] + 0.05:
                errors.append(
                    f"'{n}' no cubre {p.interval.start:.1f}-{p.interval.end:.1f}s del maestro "
                    f"(tiene 0-{project.durations[n]:.1f}s con offset {src.offset:+.2f}s); revisa el offset"
                )
    if errors:
        raise InvalidDecisions(sorted(set(errors)))


def plan_to_json(shots: list[Shot], words: list[Word], model: str, project: Project) -> str:
    items = [
        {
            "id": n, "start": s.start, "at": round(words[s.start].start, 2),
            "text": " ".join(w.text for w in words[s.start : s.start + 8]),
            "layout": s.layout,
            **({"source": s.source} if s.layout == "full" else
               {"main": s.main, "side": s.side, "side_pos": s.side_pos}),
            "reason": s.reason,
        }
        for n, s in enumerate(shots, 1)
    ]
    return json.dumps(
        {
            "model": model, "audio": project.audio,
            "ayuda": "Edita 'layout' y los canales de cualquier plano. Un plano dura hasta el siguiente.",
            "shots": items,
        },
        indent=2, ensure_ascii=False,
    )


def plan_from_json(text: str) -> list[Shot]:
    return parse_shots(json.loads(text)["shots"])
