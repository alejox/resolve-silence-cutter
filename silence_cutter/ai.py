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

from . import shots as shotlib
from .edit import Decision, InvalidDecisions, parse_decisions, validate
from .project import Project, describe
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


def _converse(user: str, system: str, check, model: str | None, caller: Caller):
    """Pide, valida con `check(reply)` y reintenta UNA vez devolviendo los errores concretos."""
    model = model or os.environ.get("SILENCE_CUTTER_MODEL", DEFAULT_MODEL)
    messages = [{"role": "user", "content": user}]
    reply = caller(system, messages, model)
    for attempt in (1, 2):
        try:
            return check(reply)
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
            reply = caller(system, messages, model)
    raise AssertionError("inalcanzable")


def _check_size(words: list[Word]) -> None:
    if len(words) > MAX_WORDS:
        raise SystemExit(f"{len(words)} palabras: demasiado largo para una sola llamada (máx. {MAX_WORDS}).")


def propose_cuts(
    words: list[Word],
    model: str | None = None,
    max_cut_fraction: float = 0.5,
    caller: Caller = call_claude,
) -> list[Decision]:
    if not words:
        return []
    _check_size(words)

    def check(reply: str) -> list[Decision]:
        decisions = parse_decisions(extract_json(reply).get("decisions", []))
        validate(decisions, len(words), max_cut_fraction)
        return sorted(decisions, key=lambda d: d.start)

    return _converse(format_transcript(words), SYSTEM, check, model, caller)


SHOTS_SYSTEM = """Eres un editor de video. Recibes la transcripción numerada de un video ([n]palabra, con
marcas de tiempo (Ns) por línea) y la lista de CANALES disponibles, cada uno con su nombre, su rol y una
descripción. Decide qué canal se ve en cada momento según lo que se está diciendo.

Cada plano es un CAMBIO que empieza en la palabra "start" y dura hasta el siguiente plano:
- {"start": n, "layout": "full", "source": "<canal>"}: un canal a pantalla completa.
- {"start": n, "layout": "pip", "main": "<canal>", "side": "<canal>", "side_pos": "right"|"left"}: un canal
  principal con otro pequeño al costado. Úsalo cuando la persona explica algo que se muestra en pantalla:
  main = la pantalla, side = la cámara.
Cada plano lleva "reason": una frase corta en español.

Reglas:
- Usa SOLO los nombres de canal listados, tal cual. Los de rol "audio" no se pueden mostrar.
- Cuando se habla a la audiencia sin mostrar nada, usa la cámara a pantalla completa.
- Cuando se menciona o explica algo que está en pantalla, usa la pantalla (con la cámara al costado si se sigue explicando).
- Cuando se habla de un producto, muestra su toma ("product") mientras se menciona y vuelve a otro plano después.
  Una toma de producto no puede durar más que su archivo (se indica entre paréntesis).
- No cambies de plano sin motivo: evita parpadeos (planos de menos de ~2 segundos) salvo una toma de producto breve.
- "start" estrictamente creciente. Si el primer plano no empieza en 0, el inicio usa el plano por defecto.

Responde ÚNICAMENTE con JSON:
{"shots": [{"start": 0, "layout": "full", "source": "camara", "reason": "..."}]}"""


def propose_shots(
    words: list[Word],
    project: Project,
    total: float,
    model: str | None = None,
    caller: Caller = call_claude,
) -> list[shotlib.Shot]:
    if not words:
        return []
    _check_size(words)

    def check(reply: str) -> list[shotlib.Shot]:
        shots = shotlib.parse_shots(extract_json(reply).get("shots", []))
        shotlib.validate(shots, words, project, total)
        return sorted(shots, key=lambda s: s.start)

    user = (
        f"CANALES (plano por defecto: {project.default_source}):\n{describe(project)}\n\n"
        f"TRANSCRIPCIÓN:\n{format_transcript(words)}"
    )
    return _converse(user, SHOTS_SYSTEM, check, model, caller)
