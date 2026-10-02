"""Detección de silencios y cálculo de los tramos que se conservan.

Todo es lógica pura salvo `run_silencedetect`/`probe_duration`, que llaman a ffmpeg.
Los tiempos van siempre en segundos sobre el archivo ORIGINAL, salvo `remap_time`
y lo que devuelve `build_cues`, que ya están sobre el resultado recortado.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

_START = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?)")
_END = re.compile(r"silence_end:\s*(-?\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class Interval:
    start: float
    end: float

    @property
    def length(self) -> float:
        return self.end - self.start


def probe_duration(path: str) -> float:
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", path,
        ],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def run_silencedetect(path: str, noise_db: float, min_silence: float) -> str:
    """Devuelve el stderr de ffmpeg, que es donde `silencedetect` escribe."""
    proc = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-nostats", "-i", path, "-vn",
            "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}",
            "-f", "null", "-",
        ],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg falló:\n{proc.stderr[-800:]}")
    return proc.stderr


def parse_silencedetect(stderr: str, duration: float) -> list[Interval]:
    silences: list[Interval] = []
    start: float | None = None
    for line in stderr.splitlines():
        m = _START.search(line)
        if m:
            start = max(0.0, float(m.group(1)))
            continue
        m = _END.search(line)
        if m and start is not None:
            silences.append(Interval(start, min(duration, float(m.group(1)))))
            start = None
    if start is not None:  # el silencio llega hasta el final del archivo
        silences.append(Interval(start, duration))
    return silences


RMS_WINDOW = 0.05  # segundos por ventana de nivel
_PTS = re.compile(r"pts_time:\s*([\d.]+)")
_RMS = re.compile(r"RMS_level=(\S+)")


def parse_rms_levels(text: str) -> list[float]:
    """Niveles RMS (dB) por ventana, de la salida de `astats`+`ametadata`. -inf se toma como -120."""
    levels: list[float] = []
    seen_window = False
    for line in text.splitlines():
        if _PTS.search(line):
            seen_window = True
            continue
        m = _RMS.search(line)
        if m and seen_window:
            v = m.group(1)
            levels.append(-120.0 if v in ("-inf", "inf", "nan") else float(v))
            seen_window = False
    return levels


def rms_levels(path: str, window: float = RMS_WINDOW, rate: int = 16000) -> list[float]:
    """Nivel RMS por ventana de `window` s.

    `silencedetect` de ffmpeg mira la amplitud de cada MUESTRA: el ruido de fondo (ventilador,
    zumbido) tiene picos que superan cualquier umbral razonable aunque su nivel medio sea bajo,
    y entonces no detecta ninguna pausa. El RMS por ventanas sí separa habla de ruido.
    """
    n = int(rate * window)
    proc = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-nostats", "-i", path, "-vn", "-ac", "1", "-af",
            f"aresample={rate},asetnsamples=n={n}:p=0,astats=metadata=1:reset=1,"
            "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
            "-f", "null", "-",
        ],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg falló:\n{proc.stderr[-800:]}")
    return parse_rms_levels(proc.stdout)


def auto_threshold(levels: list[float], fraction: float = 0.3) -> float:
    """Umbral entre el ruido de fondo (percentil 10) y el habla (percentil 90), en dB.

    Si casi no hay diferencia entre ambos (audio de nivel constante) no hay pausas que
    separar: devuelve un umbral por debajo del ruido, que no corta nada.
    """
    if not levels:
        return -60.0
    ordered = sorted(levels)
    low = ordered[int(0.10 * (len(ordered) - 1))]
    high = ordered[int(0.90 * (len(ordered) - 1))]
    if high - low < 6.0:
        return low - 3.0
    return low + fraction * (high - low)


def silences_from_levels(
    levels: list[float], threshold: float, min_silence: float, duration: float,
    window: float = RMS_WINDOW,
) -> list[Interval]:
    silences: list[Interval] = []
    start: int | None = None
    for i, v in enumerate(levels + [float("inf")]):  # el centinela cierra un silencio abierto
        if v < threshold and start is None:
            start = i
        elif v >= threshold and start is not None:
            s, e = start * window, min(duration, i * window)
            if e - s >= min_silence:
                silences.append(Interval(s, e))
            start = None
    return silences


def speech_segments(
    silences: list[Interval],
    duration: float,
    padding: float = 0.1,
    min_speech: float = 0.15,
) -> list[Interval]:
    """Invierte los silencios en tramos hablados.

    `padding` conserva un poco de silencio a cada lado del habla para que el corte
    no suene seco; los tramos que quedan solapados se fusionan. Los tramos
    hablados más cortos que `min_speech` (clics, golpes) se descartan antes de
    aplicar el padding.
    """
    raw: list[Interval] = []
    cursor = 0.0
    for s in sorted(silences, key=lambda i: i.start):
        if s.start > cursor:
            raw.append(Interval(cursor, s.start))
        cursor = max(cursor, s.end)
    if cursor < duration:
        raw.append(Interval(cursor, duration))

    padded = [
        Interval(max(0.0, r.start - padding), min(duration, r.end + padding))
        for r in raw
        if r.length >= min_speech
    ]
    merged: list[Interval] = []
    for seg in padded:
        if merged and seg.start <= merged[-1].end:
            merged[-1] = Interval(merged[-1].start, max(merged[-1].end, seg.end))
        else:
            merged.append(seg)
    return merged


def remap_time(t: float, segments: list[Interval]) -> float | None:
    """Convierte un instante del original al de la versión recortada.

    Devuelve None si `t` cae en un tramo eliminado.
    """
    offset = 0.0
    for seg in segments:
        if seg.start <= t <= seg.end:
            return offset + (t - seg.start)
        offset += seg.length
    return None


def total_length(segments: list[Interval]) -> float:
    return sum(s.length for s in segments)


def render_cut(path: str, segments: list[Interval], out: str, height: int = 720, crf: int = 26) -> None:
    """Renderiza la versión recortada (para revisarla sin Resolve). Une los tramos con trim+concat."""
    if not segments:
        raise ValueError("no hay tramos que renderizar")
    parts, joined = [], []
    for i, s in enumerate(segments):
        parts.append(
            f"[0:v]trim=start={s.start:.3f}:end={s.end:.3f},setpts=PTS-STARTPTS,scale=-2:{height}[v{i}];"
            f"[0:a]atrim=start={s.start:.3f}:end={s.end:.3f},asetpts=PTS-STARTPTS[a{i}]"
        )
        joined.append(f"[v{i}][a{i}]")
    graph = ";".join(parts) + ";" + "".join(joined) + f"concat=n={len(segments)}:v=1:a=1[v][a]"
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", path, "-filter_complex", graph,
         "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", str(crf), "-preset", "veryfast",
         "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", out],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg falló al renderizar:\n{proc.stderr[-800:]}")
