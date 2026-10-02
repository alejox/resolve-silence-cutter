"""Edición por planos (cámara, pantalla, productos) desde Workspace > Scripts de DaVinci Resolve.

Instalación: igual que `Silence Cutter.py` (carpeta Scripts/Edit y SILENCE_CUTTER_HOME).
Define SILENCE_CUTTER_PROJECT con la ruta de tu proyecto.json (ver examples/proyecto.ejemplo.json).

Dos pasadas, como en la terminal:
  1) Sin SILENCE_CUTTER_PLAN: Claude propone los planos y escribe <proyecto>.planos.json / .md.
     Necesita ANTHROPIC_API_KEY. No toca la timeline.
  2) Con SILENCE_CUTTER_PLAN=<ruta al .planos.json> (ya revisado): arma la timeline multicámara.
     SILENCE_CUTTER_CUTS (opcional) suma cortes por contenido aprobados; SILENCE_CUTTER_OVERLAYS, overlays.
El resultado (o el error) queda en `Silence Cutter Multicam.log`.
"""

import os
import sys
import traceback
from pathlib import Path

HOME = os.environ.get("SILENCE_CUTTER_HOME", "")
PROJECT = os.environ.get("SILENCE_CUTTER_PROJECT", "")
PLAN = os.environ.get("SILENCE_CUTTER_PLAN", "")
CUTS = os.environ.get("SILENCE_CUTTER_CUTS", "")
OVERLAYS = os.environ.get("SILENCE_CUTTER_OVERLAYS", "")
OPTS = {"noise": None,  # None = automático; o un nivel fijo en dB
         "min_silence": 0.5, "padding": 0.1, "min_speech": 0.15,
        "model": "small", "language": None, "max_cut": 0.5}
AI_MODEL = None

# Resolve no hereda el PATH de la terminal en macOS: ffmpeg de Homebrew no se encontraría.
os.environ["PATH"] += os.pathsep + os.pathsep.join(["/opt/homebrew/bin", "/usr/local/bin"])


def run(resolve):
    from silence_cutter.edit import InvalidDecisions
    from silence_cutter.multicam_cli import apply_plan, load, propose_plan

    if not PROJECT or not os.path.isfile(PROJECT):
        return "Define SILENCE_CUTTER_PROJECT con la ruta al proyecto.json: %r" % PROJECT
    project = load(PROJECT)
    pfile = Path(PROJECT)
    out, stem = pfile.parent, pfile.stem

    if not PLAN:
        f, md, n = propose_plan(project, out, stem, OPTS["model"], OPTS["language"], AI_MODEL)
        return ("Claude propone %d planos. Revisa %s y edita %s. Luego define "
                "SILENCE_CUTTER_PLAN con esa ruta y ejecuta de nuevo." % (n, md, f))
    try:
        msg = apply_plan(project, Path(PLAN), out, stem, OPTS, CUTS or None,
                         OVERLAYS or None, resolve, True)
    except InvalidDecisions as exc:
        return "El plan no es válido:\n- " + "\n- ".join(exc.errors)
    return "Listo: " + msg


try:
    if HOME and HOME not in sys.path:
        sys.path.insert(0, HOME)
    result = run(resolve)  # noqa: F821 - `resolve` lo inyecta Resolve
except SystemExit as exc:  # los módulos avisan con SystemExit("mensaje claro")
    result = str(exc.code) if exc.code else "Terminó sin mensaje."
except BaseException:
    result = traceback.format_exc()
with open(os.path.join(HOME or os.path.expanduser("~"), "Silence Cutter Multicam.log"), "w", encoding="utf-8") as _f:
    _f.write(result + "\n")
