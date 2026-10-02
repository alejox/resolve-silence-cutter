"""Del texto transcrito (con tiempos por palabra) al guión del video recortado."""

from __future__ import annotations

from dataclasses import dataclass

from .core import Interval


@dataclass(frozen=True)
class Word:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Cue:
    start: float  # sobre el video YA recortado
    end: float
    text: str


def build_cues(
    words: list[Word], segments: list[Interval], max_words: int = 12
) -> list[Cue]:
    """Reubica cada palabra en la línea de tiempo recortada y la agrupa en líneas.

    Una palabra se conserva si su punto medio cae dentro de un tramo que se queda;
    así una palabra partida por un corte no reaparece en el guión. Cada tramo
    conservado arranca línea nueva, y las líneas largas se parten cada `max_words`.
    """
    cues: list[Cue] = []
    offset = 0.0
    for seg in segments:
        inside = [
            w for w in words if seg.start <= (w.start + w.end) / 2 <= seg.end
        ]
        for i in range(0, len(inside), max_words):
            chunk = inside[i : i + max_words]
            start = offset + max(chunk[0].start, seg.start) - seg.start
            end = offset + min(chunk[-1].end, seg.end) - seg.start
            text = " ".join(w.text for w in chunk).strip()
            if text:
                cues.append(Cue(start, max(end, start), text))
        offset += seg.length
    return cues


def _stamp(t: float, sep: str) -> str:
    ms = round(t * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def to_srt(cues: list[Cue]) -> str:
    blocks = [
        f"{n}\n{_stamp(c.start, ',')} --> {_stamp(c.end, ',')}\n{c.text}\n"
        for n, c in enumerate(cues, 1)
    ]
    return "\n".join(blocks)


def to_markdown(cues: list[Cue], title: str) -> str:
    body = [f"**[{_stamp(c.start, '.')[:-4]}]** {c.text}" for c in cues]
    return "\n\n".join([f"# Guión: {title}", *body]) + "\n"
