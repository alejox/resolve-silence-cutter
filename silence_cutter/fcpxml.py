"""Exporta los tramos conservados como una timeline FCPXML que DaVinci Resolve importa.

Por qué FCPXML y no un script dentro de Resolve: en Resolve 21 el Lua de los scripts corre en un entorno
cerrado (sin `io`, sin `os.execute`) y Python no siempre está disponible. Importar un archivo
(File > Import > Timeline) no depende de nada de eso y funciona también en la versión gratuita.

Se usa FCPXML 1.8 (`src` en el `asset`), la variante más antigua que Resolve lee de forma fiable.
Todos los tiempos son fracciones exactas de la duración del fotograma, nunca decimales.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from xml.sax.saxutils import quoteattr

from .core import Interval


@dataclass(frozen=True)
class MediaInfo:
    path: str
    fps: Fraction  # fotogramas por segundo, exactos (24, 30000/1001...)
    width: int
    height: int
    duration: float
    has_audio: bool
    audio_rate: int = 48000
    audio_channels: int = 2
    tc_start_frames: int = 0  # timecode embebido del archivo, en fotogramas (0 si no trae)


def parse_timecode(tc: str, fps: Fraction) -> int:
    """HH:MM:SS:FF (o HH:MM:SS;FF con drop-frame) -> número de fotogramas desde 00:00:00:00."""
    m = re.fullmatch(r"(\d+):(\d+):(\d+)([:;])(\d+)", tc.strip())
    if not m:
        raise ValueError(f"timecode no válido: {tc!r}")
    h, mi, s, sep, f = int(m[1]), int(m[2]), int(m[3]), m[4], int(m[5])
    nominal = round(float(fps))
    frames = (h * 3600 + mi * 60 + s) * nominal + f
    if sep == ";":  # drop-frame: se saltan 2 fotogramas por minuto (4 a 60 fps), salvo cada 10 minutos
        drop = round(nominal * 0.066666)
        total_minutes = 60 * h + mi
        frames -= drop * (total_minutes - total_minutes // 10)
    return frames


def probe_media(path: str) -> MediaInfo:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(proc.stdout)
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    if video is None:
        raise ValueError("el archivo no tiene video")
    audio = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    fps = Fraction(video["r_frame_rate"])
    tags = {**data.get("format", {}).get("tags", {}), **video.get("tags", {})}
    tc = next((v for k, v in tags.items() if k.lower() == "timecode"), None)
    return MediaInfo(
        path=str(Path(path).resolve()),
        fps=fps,
        width=int(video["width"]),
        height=int(video["height"]),
        duration=float(data["format"]["duration"]),
        has_audio=audio is not None,
        audio_rate=int(audio.get("sample_rate", 48000)) if audio else 48000,
        audio_channels=int(audio.get("channels", 2)) if audio else 2,
        tc_start_frames=parse_timecode(tc, fps) if tc else 0,
    )


def _t(frames: int, fps: Fraction) -> str:
    """Tiempo FCPXML exacto: `frames` fotogramas, como fracción de segundo reducida."""
    if frames == 0:
        return "0s"
    seconds = Fraction(frames) / fps
    return f"{seconds.numerator}/{seconds.denominator}s" if seconds.denominator != 1 else f"{seconds.numerator}s"


def build_fcpxml(info: MediaInfo, segments: list[Interval], name: str) -> str:
    fps = info.fps
    frame_duration = 1 / fps
    kept = []
    for seg in segments:
        a, b = round(seg.start * float(fps)), round(seg.end * float(fps))
        if b > a:
            kept.append((a, b - a))
    if not kept:
        raise ValueError("no hay tramos que exportar")

    stem = Path(info.path).stem
    asset_frames = round(info.duration * float(fps))
    total = sum(d for _, d in kept)
    fd = f"{frame_duration.numerator}/{frame_duration.denominator}s"
    audio_attrs = (
        f' hasAudio="1" audioSources="1" audioChannels="{info.audio_channels}" audioRate="{info.audio_rate}"'
        if info.has_audio else ""
    )

    clips, offset = [], 0
    for start, dur in kept:
        clips.append(
            f'            <asset-clip ref="r2" offset="{_t(offset, fps)}" name={quoteattr(stem)} '
            f'start="{_t(info.tc_start_frames + start, fps)}" duration="{_t(dur, fps)}" '
            f'format="r1" tcFormat="NDF"/>'
        )
        offset += dur

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.8">
  <resources>
    <format id="r1" name="FFVideoFormat{info.height}p" frameDuration="{fd}" width="{info.width}" height="{info.height}"/>
    <asset id="r2" name={quoteattr(stem)} src={quoteattr(Path(info.path).as_uri())} start="{_t(info.tc_start_frames, fps)}" duration="{_t(asset_frames, fps)}" hasVideo="1" format="r1"{audio_attrs}/>
  </resources>
  <library>
    <event name="Silence Cutter">
      <project name={quoteattr(name)}>
        <sequence format="r1" duration="{_t(total, fps)}" tcStart="0s" tcFormat="NDF" audioLayout="stereo" audioRate="48k">
          <spine>
{chr(10).join(clips)}
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>
"""
