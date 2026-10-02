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
