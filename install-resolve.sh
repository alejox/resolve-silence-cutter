#!/usr/bin/env bash
# Instala el script "Silence Cutter Importar" en el menú Área de trabajo > Secuencias de comandos de DaVinci
# Resolve. Es un script en Lua que solo IMPORTA la última timeline generada por la herramienta
# (python3 -m silence_cutter video.mov --fcpxml): el Lua de Resolve 21 no puede leer archivos ni ejecutar nada.
#
#   ./install-resolve.sh             copias en la carpeta de scripts de TU USUARIO
#   ./install-resolve.sh --system    copias en la carpeta del SISTEMA (todos los usuarios); pide tu contraseña
#   ./install-resolve.sh --python    además instala los scripts en Python (solo útiles si Resolve ejecuta Python)
#
# Son COPIAS con la ruta de este repo escrita dentro: repite el comando después de un `git pull`.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUDO=""
SYSTEM=0
PYTHON_TOO=0
for arg in "$@"; do
  case "$arg" in
    --copy) ;;  # compatibilidad: ahora siempre se copia
    --system) SYSTEM=1; SUDO="${SUDO_BIN:-sudo}" ;;  # SUDO_BIN solo para pruebas
    --python) PYTHON_TOO=1 ;;
    *) echo "Opción desconocida: $arg"; exit 2 ;;
  esac
done

case "$(uname)" in
  Darwin)
    if [ "$SYSTEM" = 1 ]; then
      SCRIPTS="${RESOLVE_SYSTEM_DIR:-/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts}"
    else
      SCRIPTS="$HOME/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts"
    fi ;;
  Linux)
    if [ "$SYSTEM" = 1 ]; then
      SCRIPTS="${RESOLVE_SYSTEM_DIR:-/opt/resolve/Fusion/Scripts}"
    else
      SCRIPTS="$HOME/.local/share/DaVinciResolve/Fusion/Scripts"
    fi ;;
  *) echo "En Windows copia los .lua de resolve_menu\\ a %APPDATA%\\Blackmagic Design\\DaVinci Resolve\\Support\\Fusion\\Scripts\\Utility y escribe la ruta del repo en REPO dentro de cada script."; exit 1 ;;
esac
DEST="$SCRIPTS/Utility"

# Limpieza de instalaciones anteriores: la carpeta Edit (Resolve no la lista), los lanzadores en Lua que
# intentaban ejecutar comandos (en Resolve 21 no hay io ni os.execute: no podían funcionar) y los .py.
for d in "$SCRIPTS/Edit" "$DEST"; do
  if [ -d "$d" ]; then
    $SUDO rm -f "$d/Silence Cutter.lua" "$d/Silence Cutter Check.lua"
    if [ "$PYTHON_TOO" != 1 ] || [ "$d" != "$DEST" ]; then
      $SUDO rm -f "$d"/"Silence Cutter"*.py
    fi
  fi
done
[ -d "$SCRIPTS/Edit" ] && $SUDO rmdir "$SCRIPTS/Edit" 2>/dev/null || true

$SUDO mkdir -p "$DEST"
install_file() {  # $1 = archivo, $2 = patrón de la línea que lleva la ruta del repo
  local name; name="$(basename "$1")"
  $SUDO rm -f "$DEST/$name"
  sed "s|$2|$3|" "$1" | $SUDO tee "$DEST/$name" >/dev/null
  echo "instalado: $name"
}
for f in "$REPO"/resolve_menu/*.lua; do
  install_file "$f" '^local REPO = ""' "local REPO = \"$REPO\""
done
if [ "$PYTHON_TOO" = 1 ]; then
  for f in "$REPO"/resolve_menu/*.py; do
    install_file "$f" '^REPO_PATH = ""' "REPO_PATH = \"$REPO\""
  done
fi
echo
echo "Carpeta: $DEST"
echo "Reinicia Resolve (cierra la app del todo) y busca Área de trabajo > Secuencias de comandos."
echo "Uso: en la terminal  python3 -m silence_cutter tu_video.mov --fcpxml  y luego, en Resolve, ese script de menú."
