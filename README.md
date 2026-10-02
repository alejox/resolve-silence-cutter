# resolve-silence-cutter

Corta los silencios de un video o audio, transcribe lo que queda y genera un **guión con los tiempos ya ajustados a los recortes**. Opcionalmente crea en **DaVinci Resolve** una timeline nueva solo con los tramos hablados.

## Qué hace

1. Detecta silencios con `ffmpeg silencedetect`.
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

# ajustar la sensibilidad
python -m silence_cutter entrevista.mp4 --noise -35 --min-silence 0.4 --padding 0.15

# sin transcripción (rápido)
python -m silence_cutter entrevista.mp4 --no-transcribe

# además, crear la timeline en Resolve
python -m silence_cutter entrevista.mp4 --language es --resolve
```

| Opción | Def. | Para qué |
|---|---|---|
| `--noise` | `-30` | Umbral en dB bajo el cual es silencio. Más bajo (`-40`) = corta menos. |
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
- **Sincronía**: `offset` por canal, en segundos (`tiempo_del_canal = tiempo_del_maestro + offset`). Si el offset deja a un canal sin imagen en un momento que se le pide, el plan se rechaza con un mensaje. **No hay sincronía automática por audio todavía**: el offset se pone a mano.
- **Tomas de producto**: se reproducen desde su inicio y no pueden durar más que su archivo (Claude ve la duración de cada una). Si un corte cae en medio, la toma sigue donde iba.
- **Protecciones**: igual que los cortes: Claude responde con cambios de plano por palabra, el código valida todo (canales que existen, orden, duración de producto, lateral válido) y reintenta una vez con los errores concretos.
- **En Resolve**: voz en A1; el plano en V1 y el lateral en V2 (escala 28 %, esquina inferior); los overlays de Remotion van en V3. En la versión gratuita usa `resolve_menu/Silence Cutter Multicam.py`.

**Sin probar**: la colocación en Resolve real (en especial `SetProperty` para escala y posición del lateral). Y no mira la imagen: decide por la transcripción y las descripciones que tú das.

## Desde el menú de Resolve (sin terminal)

1. Copia `resolve_menu/Silence Cutter.py` a la carpeta de scripts de Resolve (`Scripts/Edit`):
   - macOS: `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Edit`
   - Windows: `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Edit`
   - Linux: `~/.local/share/DaVinciResolve/Fusion/Scripts/Edit`
2. Define la variable de entorno `SILENCE_CUTTER_HOME` con la ruta de este repo (o edita `HOME` en el script). Ajusta ahí mismo `NOISE_DB`, `LANGUAGE`, etc.
3. Con una timeline abierta y el clip en V1: *Workspace > Scripts > Edit > Silence Cutter*.

En macOS añade a mano `/opt/homebrew/bin` al PATH si `ffmpeg` no se encuentra (el script ya lo intenta). Para los cortes con Claude, el script tiene `ANALYZE` y `SILENCE_CUTTER_CUTS` (dos pasadas, igual que arriba). Usa el primer clip de V1 y su archivo completo; el resultado (o el error) queda en `Silence Cutter.log`.

## Overlays de Remotion (lower thirds, keywords, etc.)

Los componentes del repo [`alejox/remotion`](https://github.com/alejox/remotion) se pueden usar como overlays con transparencia sobre la timeline recortada.

1. En `remotion`, renderiza los beats de tu `config` (con `at` en segundos del **original**):
   ```bash
   node scripts/render-overlays.mjs mis-beats.json out/overlays
   ```
   Genera un `.mov` ProRes 4444 con alfa por beat y un `overlays.manifest.json`. Los `spotlight` se omiten (necesitan el video de fondo).
2. Aquí, cortar y colocar en V2:
   ```bash
   python -m silence_cutter entrevista.mp4 --resolve --overlays ../remotion/out/overlays/overlays.manifest.json
   ```

Cómo se ubican: cada `at` se convierte a su posición en el video recortado. Un beat que cae en un silencio eliminado se **omite** (se avisa en consola); uno que empieza en un tramo pero lo excede se **recorta** al final del tramo.

Límites: sin video detrás, el vidrio (`lowerThird`, `checklist`, `subscribe`) se ve como un panel oscuro translúcido, sin desenfoque. El texto sin vidrio (`title`, `keyword`, `value`, `compare`) queda igual que en la plantilla. `--resolve` desde la terminal necesita Resolve Studio (scripting externo). En la versión gratuita usa el script del menú, que también coloca overlays si defines `SILENCE_CUTTER_OVERLAYS` con la ruta del manifiesto.

## Pruebas

```bash
python -m unittest discover -s tests
```

La lógica de cortes y guión está probada sin ffmpeg ni Whisper. La integración con Resolve (`resolve_integration.py`) no tiene prueba automática porque necesita Resolve en ejecución.

## Licencia

MIT
