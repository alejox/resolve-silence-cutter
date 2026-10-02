"""Sincronía automática entre canales por correlación de la envolvente de audio.

`offset` sigue la convención del proyecto: tiempo_del_canal = tiempo_del_maestro + offset.
Sin dependencias (ni numpy): se busca en dos pasadas, primero grueso y luego fino, sobre un
trozo acotado del inicio, así el costo no crece con la duración del video.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from .core import rms_levels

FINE = 0.01  # s por muestra de la envolvente fina
COARSE_STEP = 10  # muestras finas por muestra gruesa (0,1 s)


@dataclass(frozen=True)
class SyncResult:
    offset: float
    confidence: float  # 0..1; por debajo de ~0.5 conviene revisar a mano


def has_audio(path: str) -> bool:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
         "-of", "csv=p=0", path],
        capture_output=True, text=True,
    ).stdout
    return bool(out.strip())


def envelope(path: str, seconds: float) -> list[float]:
    """Nivel (dB, con piso) cada 10 ms de los primeros `seconds`, con la media quitada."""
    levels = rms_levels(path, window=FINE, rate=8000)[: int(seconds / FINE)]
    clipped = [max(v, -70.0) for v in levels]
    if not clipped:
        return []
    mean = sum(clipped) / len(clipped)
    return [v - mean for v in clipped]


def _decimate(x: list[float], k: int) -> list[float]:
    return [sum(x[i : i + k]) / k for i in range(0, len(x) - k + 1, k)]


def _corr(a: list[float], b: list[float], lag: int, min_overlap: int = 10) -> float:
    """Correlación normalizada de a[i] con b[i + lag] sobre el solape.

    Con poco solape la correlación sale alta por azar, así que se exige un mínimo.
    """
    lo, hi = max(0, -lag), min(len(a), len(b) - lag)
    if hi - lo < min_overlap:
        return -1.0
    sab = saa = sbb = 0.0
    for i in range(lo, hi):
        x, y = a[i], b[i + lag]
        sab += x * y
        saa += x * x
        sbb += y * y
    return sab / ((saa * sbb) ** 0.5) if saa > 0 and sbb > 0 else -1.0


def best_offset(master: list[float], channel: list[float], max_lag: float) -> SyncResult:
    """Offset (s) que alinea `channel` con `master`, buscando en ±max_lag.

    La confianza es la correlación del mejor pico MENOS la del mejor candidato LEJANO (a más de
    1 s): un pico único y claro da confianza alta; un audio sin relación, o muy repetitivo
    (varios picos parecidos), da baja.
    """
    if len(master) < 100 or len(channel) < 100:
        return SyncResult(0.0, 0.0)
    ca, cb = _decimate(master, COARSE_STEP), _decimate(channel, COARSE_STEP)
    reach = int(max_lag / (FINE * COARSE_STEP))
    overlap = max(10, min(len(ca), len(cb)) // 2)  # al menos la mitad del audio más corto
    scores = {lag: _corr(ca, cb, lag, overlap) for lag in range(-reach, reach + 1)}
    best = max(scores, key=scores.get)
    far = [s for lag, s in scores.items() if abs(lag - best) * FINE * COARSE_STEP > 1.0]
    rival = max(far) if far else 0.0
    confidence = max(0.0, min(1.0, scores[best] - max(rival, 0.0)))

    centre = best * COARSE_STEP
    fine = {lag: _corr(master, channel, lag, overlap * COARSE_STEP)
            for lag in range(centre - 2 * COARSE_STEP, centre + 2 * COARSE_STEP + 1)}
    lag = max(fine, key=fine.get)
    return SyncResult(round(lag * FINE, 2), round(confidence, 2))


def sync_offset(
    master_path: str, channel_path: str, max_lag: float = 60.0, analyze_seconds: float = 120.0
) -> SyncResult:
    if not has_audio(channel_path):
        raise ValueError("el canal no tiene audio para sincronizar")
    m = envelope(master_path, analyze_seconds)
    c = envelope(channel_path, analyze_seconds + max_lag)
    return best_offset(m, c, max_lag)
