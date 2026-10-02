"""Proyecto multicámara: canales con nombre (pantalla, cámara, productos...).

Cada archivo es un CANAL con nombre y descripción. A Claude solo se le muestran esos
nombres y descripciones: no tiene que adivinar qué es cada archivo.

Roles:
- camera / screen: grabados a la vez que el audio maestro; se sincronizan con `offset`
  (segundos: tiempo_del_canal = tiempo_maestro + offset).
- product: toma suelta. Se reproduce desde su inicio mientras dura su plano.
- audio: solo sonido (p. ej. un micrófono aparte); no se muestra.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

ROLES = ("camera", "screen", "product", "audio")
VISUAL_ROLES = ("camera", "screen", "product")


class InvalidProject(ValueError):
    pass


@dataclass(frozen=True)
class Source:
    name: str
    file: str
    role: str
    description: str = ""
    offset: float = 0.0


@dataclass
class Project:
    sources: dict[str, Source]
    audio: str  # nombre del canal que da el audio y la referencia de tiempo
    default_source: str
    durations: dict[str, float] = field(default_factory=dict)  # se llena con ffprobe

    @property
    def master(self) -> Source:
        return self.sources[self.audio]

    def visual(self) -> list[Source]:
        return [s for s in self.sources.values() if s.role in VISUAL_ROLES]


def parse_project(data: dict, base_dir: Path | None = None, check_files: bool = True) -> Project:
    raw = data.get("sources")
    if not isinstance(raw, dict) or not raw:
        raise InvalidProject("falta 'sources' con al menos un canal")
    sources: dict[str, Source] = {}
    for name, s in raw.items():
        if not isinstance(s, dict) or "file" not in s or "role" not in s:
            raise InvalidProject(f"canal '{name}': necesita 'file' y 'role'")
        if s["role"] not in ROLES:
            raise InvalidProject(f"canal '{name}': role '{s['role']}' no es uno de {', '.join(ROLES)}")
        path = Path(s["file"])
        if base_dir and not path.is_absolute():
            path = base_dir / path
        if check_files and not path.is_file():
            raise InvalidProject(f"canal '{name}': no existe {path}")
        sources[name] = Source(name, str(path), s["role"], str(s.get("description", "")), float(s.get("offset", 0.0)))

    audio = data.get("audio")
    if audio is None:  # por lo general el audio llega con la grabación de pantalla
        audio = next((n for n, s in sources.items() if s.role == "screen"), None) or next(
            (n for n, s in sources.items() if s.role in ("camera", "audio")), None
        )
    if audio not in sources:
        raise InvalidProject(f"'audio' apunta a '{audio}', que no es un canal")
    if sources[audio].role == "product":
        raise InvalidProject("el audio maestro no puede ser una toma de producto")

    default = data.get("default")
    if default is None:
        default = next((n for n, s in sources.items() if s.role == "camera"), None) or next(
            (n for n, s in sources.items() if s.role == "screen"), None
        )
    if default not in sources or sources[default].role not in VISUAL_ROLES:
        raise InvalidProject("no hay un canal visual para usar como plano por defecto ('default')")
    return Project(sources, audio, default)


def load_project(path: str, check_files: bool = True) -> Project:
    p = Path(path)
    return parse_project(json.loads(p.read_text(encoding="utf-8")), p.parent, check_files)


def describe(project: Project) -> str:
    """Lo que ve Claude de los canales: nombre, rol, descripción y, en tomas sueltas, la duración."""
    lines = []
    for s in project.visual():
        extra = ""
        if s.role == "product" and s.name in project.durations:
            extra = f" (dura {project.durations[s.name]:.1f}s)"
        desc = f": {s.description}" if s.description else ""
        lines.append(f"- {s.name} [{s.role}]{extra}{desc}")
    return "\n".join(lines)
