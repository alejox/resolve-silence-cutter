"""Propuesta de cortes con la API de Claude (solo stdlib, sin dependencias).

El modelo NUNCA toca el video: devuelve rangos de palabras, `edit.validate` los revisa y
una persona los aprueba antes de aplicarlos. Si la respuesta no valida, se reintenta una
vez devolviéndole los errores concretos.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Callable

from .edit import Decision, InvalidDecisions, parse_decisions, validate
from .script import Word

API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-5-5"
MAX_WORDS = 20000  # una sola llamada; más allá habría que trocear

SYSTEM = """Eres un editor de video experto en pulir entrevistas y videos hablados.
Recibes la transcripción de un video con cada palabra numerada como [n]palabra y marcas
de tiempo (Ns) al inicio de cada línea. Decide qué rangos de palabras eliminar para que el
resultado sea coherente, directo y fácil de seguir, sin perder información.

Elimina SOLO estos casos (campo "kind"):
- repeat: la misma idea dicha varias veces (varias tomas). Conserva la toma más completa y clara, normalmente la última.
- filler: muletillas vacías (eh, mmm, o sea, ¿sí?) que no aportan.
- false_start: frases abandonadas o arrancadas y corregidas.
- offtopic: digresiones claramente ajenas al tema del video.
- other: solo si ninguna anterior aplica y el motivo es claro.

Reglas estrictas:
- Sé conservador: ante la duda, NO cortes. Es peor borrar contenido bueno que dejar una muletilla.
- No cortes información única, cifras, nombres ni conclusiones.
- Cada corte debe dejar frases completas y gramaticales a ambos lados.
- Rangos [start, end] INCLUSIVOS de índices de palabra, sin solaparse.
- "reason": una frase corta en español explicando el corte.

Responde ÚNICAMENTE con JSON, sin texto alrededor:
{"decisions": [{"start": 12, "end": 20, "kind": "repeat", "reason": "..."}]}
Si no hay nada que cortar: {"decisions": []}"""


def format_transcript(words: list[Word], pause: float = 0.7) -> str:
    """Una línea por pausa larga, con su marca de tiempo, para que el modelo vea las tomas."""
    lines: list[str] = []
    current: list[str] = []
    line_start = 0.0
    last_end = 0.0
    for i, w in enumerate(words):
        if current and w.start - last_end > pause:
            lines.append(f"({line_start:.1f}s) " + " ".join(current))
            current = []
        if not current:
            line_start = w.start
        current.append(f"[{i}]{w.text}")
        last_end = w.end
    if current:
        lines.append(f"({line_start:.1f}s) " + " ".join(current))
    return "\n".join(lines)


def extract_json(text: str) -> dict:
    """Saca el objeto JSON aunque el modelo lo envuelva en ``` o agregue texto."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text[text.find("{") : text.rfind("}") + 1]
    if not candidate:
        raise InvalidDecisions(["la respuesta no contiene JSON"])
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise InvalidDecisions([f"JSON inválido: {exc}"]) from exc


Caller = Callable[[str, list[dict], str], str]


def call_claude(system: str, messages: list[dict], model: str) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise SystemExit("Define ANTHROPIC_API_KEY para usar --analyze.")
    body = json.dumps(
        {"model": model, "max_tokens": 4096, "system": system, "messages": messages}
    ).encode()
    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"La API respondió {exc.code}: {exc.read().decode()[:400]}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"No pude contactar la API: {exc.reason}") from exc
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def propose_cuts(
    words: list[Word],
    model: str | None = None,
    max_cut_fraction: float = 0.5,
    caller: Caller = call_claude,
) -> list[Decision]:
    if not words:
        return []
    if len(words) > MAX_WORDS:
        raise SystemExit(f"{len(words)} palabras: demasiado largo para una sola llamada (máx. {MAX_WORDS}).")
    model = model or os.environ.get("SILENCE_CUTTER_MODEL", DEFAULT_MODEL)
    messages = [{"role": "user", "content": format_transcript(words)}]
    reply = caller(SYSTEM, messages, model)
    for attempt in (1, 2):
        try:
            decisions = parse_decisions(extract_json(reply).get("decisions", []))
            validate(decisions, len(words), max_cut_fraction)
            return sorted(decisions, key=lambda d: d.start)
        except InvalidDecisions as exc:
            if attempt == 2:
                raise
            messages += [
                {"role": "assistant", "content": reply},
                {
                    "role": "user",
                    "content": "Tu respuesta no es válida:\n- "
                    + "\n- ".join(exc.errors)
                    + "\nCorrígela y responde solo con el JSON.",
                },
            ]
            reply = caller(SYSTEM, messages, model)
    raise AssertionError("inalcanzable")
