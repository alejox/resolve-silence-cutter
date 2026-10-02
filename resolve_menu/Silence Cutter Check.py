"""Diagnóstico para Workspace > Scripts de DaVinci Resolve: ¿está todo listo?

Resolve no muestra una consola al correr un script del menú, así que el resultado se escribe en
`Silence Cutter Check.log` (en la carpeta del repo, o en tu carpeta personal si no se encuentra).
Ejecútalo primero: te dice qué falta antes de intentar cortar nada.
"""

import os
import shutil
import sys
import traceback

lines = []


def check(name, ok, detail=""):
    lines.append("%s  %s%s" % ("OK " if ok else "FALTA", name, ("  -> " + detail) if detail else ""))


REPO_PATH = ""  # `install-resolve.sh --copy` escribe aquí la ruta del repo


def _find_home():
    env = os.environ.get("SILENCE_CUTTER_HOME", "")
    if env:
        return env
    try:
        root = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
        if os.path.isdir(os.path.join(root, "silence_cutter")):
            return root
    except NameError:
        pass
    if REPO_PATH:
        return REPO_PATH
    for p in sys.path:  # corrido desde la consola: la carpeta que se añadió a sys.path
        if p and os.path.isdir(os.path.join(p, "silence_cutter")):
            return p
    return ""


HOME = _find_home()
try:
    lines.append("Python que usa Resolve: %s  (%s)" % (sys.version.split()[0], sys.executable))
    os.environ["PATH"] += os.pathsep + os.pathsep.join(["/opt/homebrew/bin", "/usr/local/bin"])
    check("Carpeta del repo", bool(HOME), HOME or "no se encontró: instala con ./install-resolve.sh")
    if HOME and HOME not in sys.path:
        sys.path.insert(0, HOME)
    try:
        import silence_cutter  # noqa: F401
        check("Paquete silence_cutter", True)
    except Exception as exc:
        check("Paquete silence_cutter", False, repr(exc))
    check("ffmpeg", bool(shutil.which("ffmpeg")), shutil.which("ffmpeg") or "instala con: brew install ffmpeg")
    check("ffprobe", bool(shutil.which("ffprobe")), shutil.which("ffprobe") or "viene con ffmpeg")
    try:
        import faster_whisper  # noqa: F401
        check("faster-whisper (transcripción)", True)
    except Exception:
        check("faster-whisper (transcripción)", False,
              "instálalo con ESTE Python: %s -m pip install faster-whisper" % sys.executable)
    try:
        from silence_cutter.ai import KEY_FILE, api_key
        check("API key de Anthropic (cortes y planos con Claude)", bool(api_key()),
              "" if api_key() else "opcional; guárdala en %s" % KEY_FILE)
    except Exception as exc:
        check("API key de Anthropic", False, repr(exc))
    try:
        resolve  # noqa: F821 - lo inyecta Resolve
        project = resolve.GetProjectManager().GetCurrentProject()  # noqa: F821
        check("Conexión con Resolve", project is not None, "proyecto: %s" % (project.GetName() if project else "ninguno abierto"))
    except NameError:
        lines.append("(corriendo fuera de Resolve: no se comprueba la conexión)")
except BaseException:
    lines.append(traceback.format_exc())

out = "\n".join(lines) + "\n"
print(out)
with open(os.path.join(HOME or os.path.expanduser("~"), "Silence Cutter Check.log"), "w", encoding="utf-8") as _f:
    _f.write(out)
