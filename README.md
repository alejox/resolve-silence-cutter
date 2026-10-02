# resolve-silence-cutter

Corta los silencios de un video o audio, transcribe lo que queda y genera un **guión con los tiempos ya ajustados a los recortes**. Opcionalmente crea en **DaVinci Resolve** una timeline nueva solo con los tramos hablados.

## Qué hace

1. Detecta pausas midiendo el nivel RMS por ventanas de 50 ms (no `silencedetect`, que mira la amplitud de cada muestra y no detecta pausas si hay ruido de fondo).
2. Calcula los tramos hablados (con un poco de holgura para que el corte no suene seco).
3. Transcribe con [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (palabra por palabra).
4. Reubica cada palabra en el video recortado y escribe:
   - `<archivo>.guion.md`: guión con marcas de tiempo.
   - `<archivo>.srt`: subtítulos que calzan con la timeline recortada.
   - `<archivo>.segments.json`: los tramos conservados (tiempos del original).
5. Con `--resolve`, importa el archivo y arma la timeline con esos tramos.

Las palabras que caen en un silencio eliminado no aparecen en el guión.

## Requisitos

- Python 3.9+
- `ffmpeg` y `ffprobe` en el PATH
- Para el guión: `pip install faster-whisper`
- Para `--resolve`: DaVinci Resolve abierto con un proyecto, y en *Preferences > System > General* → *External scripting using: Local*

## Uso

```bash
# solo cortar + guión
python -m silence_cutter entrevista.mp4 --language es

# ajustar la sensibilidad (o --noise auto, el valor por defecto)
python -m silence_cutter entrevista.mp4 --noise -35 --min-silence 0.4 --padding 0.15

# renderizar el resultado (720p) para revisarlo sin Resolve
python -m silence_cutter entrevista.mp4 --no-transcribe --render recortado.mp4

# sin transcripción (rápido)
python -m silence_cutter entrevista.mp4 --no-transcribe

# además, crear la timeline en Resolve
python -m silence_cutter entrevista.mp4 --language es --resolve
```

| Opción | Def. | Para qué |
|---|---|---|
| `--noise` | `auto` | Umbral de silencio. `auto` lo calcula del ruido de fondo del propio archivo (entre su percentil 10 y 90 de nivel); o un nivel fijo en dB (`-35`). |
| `--min-silence` | `0.5` | Silencio mínimo a cortar, en segundos. |
| `--padding` | `0.1` | Silencio que se conserva a cada lado del habla. |
| `--min-speech` | `0.15` | Descarta ruidos más cortos que esto. |
| `--model` | `small` | Modelo de Whisper (`tiny`…`large-v3`). |

## Cortes por contenido con Claude (revisión humana)

Además de los silencios, Claude puede proponer qué quitar para que el video sea coherente: **tomas repetidas** (se conserva la más completa), **muletillas**, **falsos comienzos** y **digresiones fuera de tema**. Nunca corta solo: propone, tú revisas y recién entonces se aplica.

```bash
export ANTHROPIC_API_KEY=...
# 1) transcribe y pide la propuesta (no corta nada)
python -m silence_cutter entrevista.mp4 --language es --analyze
#    -> entrevista.cortes.md (para leer) y entrevista.cortes.json (para editar)
# 2) pon "apply": false en los cortes que quieras conservar, y aplica
python -m silence_cutter entrevista.mp4 --apply-cuts entrevista.cortes.json
```

Cómo está protegido:
- Claude responde con rangos de **palabras**, no de tiempo. El código valida todo (índices en rango, sin solapes, tipo y motivo presentes) y, si la respuesta es inválida, se la devuelve **una vez** con los errores concretos; si vuelve a fallar, aborta.
- `--max-cut` (50 % por defecto) rechaza propuestas que borrarían demasiado.
- Los índices de palabra solo valen para la transcripción de esa corrida, que queda guardada en `<video>.words.json`. Si borras ese archivo, vuelve a correr `--analyze`.
- El prompt le pide ser conservador: ante la duda, no corta.

Qué **no** hace: no mira la imagen (solo audio y texto), así que no detecta que te equivocaste a cámara en silencio. Y la calidad de las decisiones depende del modelo y de la transcripción; revisa siempre `.cortes.md`. La transcripción se envía a la API de Anthropic y tiene costo por uso.

## Varias fuentes: cámara, pantalla y productos (edición por planos)

Cada archivo es un **canal con nombre y descripción** (`proyecto.json`, ver `examples/proyecto.ejemplo.json`). Claude solo ve esos nombres y descripciones, así que no tiene que adivinar qué es cada archivo. Elige qué se ve según lo que se dice:

- **Un canal a pantalla completa**: la cámara cuando hablas a la audiencia, una toma de producto cuando lo mencionas.
- **Un canal principal con otro al costado**: la pantalla con la cámara en una esquina cuando explicas lo que se ve.

```bash
export ANTHROPIC_API_KEY=...
# 1) Claude propone los planos (no toca nada)
python -m silence_cutter multicam proyecto.json --plan --language es
#    -> proyecto.planos.md (para leer) y proyecto.planos.json (para editar)
# 2) corrige lo que no te guste en el .json y aplica (cortes de silencio incluidos)
python -m silence_cutter multicam proyecto.json --apply-plan proyecto.planos.json
```

- **Audio**: por defecto lo da el canal de pantalla (`"audio": "pantalla"`). Si viene aparte, define un canal con `"role": "audio"` y apúntalo en `audio`. La voz sale solo de ese canal; los demás clips entran sin sonido.
- **Sincronía**: `offset` por canal, en segundos (`tiempo_del_canal = tiempo_del_maestro + offset`). Se calcula solo con `python -m silence_cutter multicam proyecto.json --sync`: correlaciona el audio de cada cámara/pantalla con el del maestro (busca ±60 s en los primeros 2 minutos) y guarda `proyecto.offsets.json`, que tiene prioridad sobre el `offset` del proyecto. Imprime una confianza; por debajo de 0,5 revisa el offset a mano. Los canales sin audio (o las tomas de producto) no se sincronizan. Si un offset deja a un canal sin imagen en un momento que se le pide, el plan se rechaza con un mensaje.
- **Tomas de producto**: se reproducen desde su inicio y no pueden durar más que su archivo (Claude ve la duración de cada una). Si un corte cae en medio, la toma sigue donde iba.
- **Protecciones**: igual que los cortes: Claude responde con cambios de plano por palabra, el código valida todo (canales que existen, orden, duración de producto, lateral válido) y reintenta una vez con los errores concretos.
- **En Resolve**: voz en A1; el plano en V1 y el lateral en V2 (escala 28 %, esquina inferior); los overlays de Remotion van en V3. En la versión gratuita usa `resolve_menu/Silence Cutter Multicam.py`.

**Sin probar**: la colocación en Resolve real (en especial `SetProperty` para escala y posición del lateral). Y no mira la imagen: decide por la transcripción y las descripciones que tú das.

## Instalar y usar en DaVinci Resolve (Mac)

Los scripts del menú *Área de trabajo > Secuencias de comandos* (*Workspace > Scripts*) son en **Lua**, porque Resolve no siempre ejecuta Python (en algunas instalaciones, incluida una gratuita 21.1.1, ni siquiera lo ofrece en la consola). El script de Lua no necesita Python dentro de Resolve: le pide el trabajo pesado a la herramienta por la terminal y arma la timeline con la API de Lua. Funciona en la versión gratuita (el scripting desde fuera, `--resolve`, requiere Studio).

```bash
brew install ffmpeg
git clone https://github.com/alejox/resolve-silence-cutter
cd resolve-silence-cutter
git checkout claude/new-repo-kh63yw     # hasta que esta rama se fusione en main
./install-resolve.sh
```
Cierra Resolve del todo (Cmd+Q) y ábrelo. Deberían aparecer **Silence Cutter** y **Silence Cutter Check** directamente en *Secuencias de comandos*.

1. Ejecuta primero **Silence Cutter Check**: dice qué falta (`io.popen`, Python 3, `ffmpeg`, el paquete, `faster-whisper`, la API key). El resultado queda en `Silence Cutter Check.log` dentro de la carpeta del repo, y también sale en la Consola de comandos (F6).
2. Abre un proyecto, pon tu clip en la pista **V1** y ejecuta **Silence Cutter**. Crea una timeline nueva "<clip> - sin silencios". Resolve parece congelado mientras trabaja: es normal. El resultado o el error queda en `Silence Cutter.log`.

Los ajustes (`NOISE`, `TRANSCRIBE`, `LANGUAGE`...) están arriba en el propio script. Son **copias** con la ruta del repo escrita dentro: repite `./install-resolve.sh` después de un `git pull`. Si tu Resolve lee la carpeta del sistema y no la de tu usuario, usa `./install-resolve.sh --system` (pide contraseña).

El Python que se usa es el primero que encuentre entre `/Library/Frameworks/Python.framework`, Homebrew y `/usr/bin/python3`. Para transcribir, instala `faster-whisper` en **ese** Python (el *Check* te dice cuál es). El Python de Apple (`/usr/bin/python3`) sirve para cortar silencios.

Qué hace hoy el script de Lua: cortar silencios (y guión con `TRANSCRIBE = true`). Los cortes con Claude, los planos con varias fuentes y los overlays se usan desde la terminal (secciones de arriba); todavía no tienen lanzador en Lua. Los scripts en Python (`./install-resolve.sh --python`) solo sirven si tu Resolve ejecuta Python.

**Variables de entorno en macOS:** una app abierta desde el Dock (Resolve) **no lee** tu `.zshrc`. La API key de Anthropic se lee de `~/.config/silence-cutter/anthropic_key` (un archivo con solo la clave; `chmod 600`), que vive fuera del repo para no subirla por error.

**Probar sin Resolve** (recomendado primero, con tu video):
```bash
python3 -m silence_cutter mi_video.mov --no-transcribe --render prueba.mp4
```

## Pruebas

```bash
python -m unittest discover -s tests
```

La lógica de cortes y guión está probada sin ffmpeg ni Whisper. La integración con Resolve (`resolve_integration.py`) no tiene prueba automática porque necesita Resolve en ejecución.

## Licencia

MIT
