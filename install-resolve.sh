#!/usr/bin/env bash
# Instala los scripts del menú Workspace > Scripts de DaVinci Resolve como ENLACES a este repo:
# así un `git pull` los actualiza solo y los scripts encuentran la carpeta del repo.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
case "$(uname)" in
  Darwin) DEST="$HOME/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Edit" ;;
  Linux)  DEST="$HOME/.local/share/DaVinciResolve/Fusion/Scripts/Edit" ;;
  *) echo "En Windows copia los .py de resolve_menu\\ a %APPDATA%\\Blackmagic Design\\DaVinci Resolve\\Support\\Fusion\\Scripts\\Edit y escribe la ruta del repo en HOME dentro de cada script."; exit 1 ;;
esac

mkdir -p "$DEST"
for f in "$REPO"/resolve_menu/*.py; do
  ln -sf "$f" "$DEST/$(basename "$f")"
  echo "enlazado: $(basename "$f")"
done
echo
echo "Listo. Reinicia Resolve y busca Workspace > Scripts > Edit."
echo "Primero ejecuta 'Silence Cutter Check' y lee Silence Cutter Check.log en: $REPO"
