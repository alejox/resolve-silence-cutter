#!/usr/bin/env bash
# Instala los scripts del menú Workspace (Área de trabajo) > Scripts (Secuencias de comandos) de
# DaVinci Resolve.
#
#   ./install-resolve.sh            enlaces en la carpeta de scripts de TU USUARIO (un `git pull` actualiza todo)
#   ./install-resolve.sh --copy     copias en la carpeta de tu usuario (si Resolve no ve los enlaces)
#   ./install-resolve.sh --system   copias en la carpeta del SISTEMA (todos los usuarios); pide tu contraseña
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="link"
SUDO=""
SYSTEM=0
for arg in "$@"; do
  case "$arg" in
    --copy) MODE="copy" ;;
    --system) SYSTEM=1; MODE="copy"; SUDO="${SUDO_BIN:-sudo}" ;;  # SUDO_BIN solo para pruebas
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
  *) echo "En Windows copia los .py de resolve_menu\\ a %APPDATA%\\Blackmagic Design\\DaVinci Resolve\\Support\\Fusion\\Scripts\\Utility y escribe la ruta del repo en REPO_PATH dentro de cada script."; exit 1 ;;
esac
DEST="$SCRIPTS/Utility"

# Versiones anteriores instalaban en .../Scripts/Edit, una carpeta que Resolve no lista: se limpia.
OLD="$SCRIPTS/Edit"
if [ -d "$OLD" ]; then
  $SUDO rm -f "$OLD"/"Silence Cutter"*.py
  $SUDO rmdir "$OLD" 2>/dev/null || true
fi

$SUDO mkdir -p "$DEST"
for f in "$REPO"/resolve_menu/*.py; do
  name="$(basename "$f")"
  $SUDO rm -f "$DEST/$name"
  if [ "$MODE" = "link" ]; then
    $SUDO ln -s "$f" "$DEST/$name"
  else
    # copia y escribe la ruta del repo, porque una copia no puede averiguarla sola
    sed "s|^REPO_PATH = \"\"|REPO_PATH = \"$REPO\"|" "$f" | $SUDO tee "$DEST/$name" >/dev/null
  fi
  echo "instalado ($MODE): $name"
done
echo
echo "Carpeta: $DEST"
echo "Reinicia Resolve (cierra la app del todo) y busca Área de trabajo > Secuencias de comandos."
echo "Primero ejecuta 'Silence Cutter Check' y lee 'Silence Cutter Check.log' en: $REPO"
