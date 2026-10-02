#!/usr/bin/env bash
# Instala los scripts del menú Workspace (Área de trabajo) > Scripts (Secuencias de comandos) de
# DaVinci Resolve.
#
#   ./install-resolve.sh          enlaces a este repo: un `git pull` actualiza todo
#   ./install-resolve.sh --copy   copias (si tu Resolve no ve los enlaces); hay que repetirlo tras un `git pull`
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="link"
[ "${1:-}" = "--copy" ] && MODE="copy"

case "$(uname)" in
  Darwin) DEST="$HOME/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Edit" ;;
  Linux)  DEST="$HOME/.local/share/DaVinciResolve/Fusion/Scripts/Edit" ;;
  *) echo "En Windows copia los .py de resolve_menu\\ a %APPDATA%\\Blackmagic Design\\DaVinci Resolve\\Support\\Fusion\\Scripts\\Edit y escribe la ruta del repo en REPO_PATH dentro de cada script."; exit 1 ;;
esac

mkdir -p "$DEST"
for f in "$REPO"/resolve_menu/*.py; do
  name="$(basename "$f")"
  rm -f "$DEST/$name"
  if [ "$MODE" = "link" ]; then
    ln -s "$f" "$DEST/$name"
  else
    # copia y escribe la ruta del repo, porque una copia no puede averiguarla sola
    sed "s|^REPO_PATH = \"\"|REPO_PATH = \"$REPO\"|" "$f" > "$DEST/$name"
  fi
  echo "instalado ($MODE): $name"
done
echo
echo "Carpeta: $DEST"
echo "Reinicia Resolve (cierra la app del todo) y busca Área de trabajo > Secuencias de comandos > Edit."
echo "Primero ejecuta 'Silence Cutter Check' y lee 'Silence Cutter Check.log' en: $REPO"
