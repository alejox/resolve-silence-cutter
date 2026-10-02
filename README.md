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

## Pruebas

```bash
python -m unittest discover -s tests
```

La lógica de cortes y guión está probada sin ffmpeg ni Whisper. La integración con Resolve (`resolve_integration.py`) no tiene prueba automática porque necesita Resolve en ejecución.

## Licencia

MIT
