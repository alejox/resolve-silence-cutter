"""Cortes por contenido: lista de decisiones sobre palabras -> tramos de tiempo.

Una decisión es un rango INCLUSIVO de índices de palabra (`start`..`end`) que se elimina.
Esta capa es pura y determinista: no sabe de Claude. Valida lo que venga de donde venga
(un modelo, o editado a mano por una persona) antes de que toque el video.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .core import Interval
from .script import Word

KINDS = ("repeat", "filler", "false_start", "offtopic", "other")
KIND_LABELS = {
    "repeat": "toma repetida",
    "filler": "muletilla",
    "false_start": "falso comienzo",
    "offtopic": "fuera de tema",
    "other": "otro",
}


class InvalidDecisions(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class Decision:
    start: int
    end: int
    kind: str
    reason: str
    apply: bool = True


def parse_decisions(raw: list[dict]) -> list[Decision]:
    """Convierte dicts sueltos en Decision, sin validar contra el texto."""
    errors: list[str] = []
    out: list[Decision] = []
    for i, d in enumerate(raw):
        try:
            start, end = d["start"], d["end"]
            if isinstance(start, bool) or isinstance(end, bool) or not (
                isinstance(start, int) and isinstance(end, int)
            ):
                raise TypeError("start y end deben ser enteros")
            out.append(
                Decision(
                    start, end,
                    str(d.get("kind", "other")),
                    str(d.get("reason", "")).strip(),
                    bool(d.get("apply", True)),
                )
            )
        except (KeyError, TypeError) as exc:
            errors.append(f"decisión {i}: {exc}")
    if errors:
        raise InvalidDecisions(errors)
    return out


def validate(
    decisions: list[Decision], n_words: int, max_cut_fraction: float = 0.5
) -> None:
    """Lanza InvalidDecisions con TODOS los problemas encontrados (sirve para reintentar)."""
    errors: list[str] = []
    for i, d in enumerate(decisions):
        if not (0 <= d.start <= d.end < n_words):
            errors.append(f"decisión {i}: rango {d.start}-{d.end} fuera de 0-{n_words - 1} o invertido")
        if d.kind not in KINDS:
            errors.append(f"decisión {i}: kind '{d.kind}' no es uno de {', '.join(KINDS)}")
        if not d.reason:
            errors.append(f"decisión {i}: falta el motivo")
    ordered = sorted(
        (d for d in decisions if 0 <= d.start <= d.end < n_words), key=lambda d: d.start
    )
    for a, b in zip(ordered, ordered[1:]):
        if b.start <= a.end:
            errors.append(f"los rangos {a.start}-{a.end} y {b.start}-{b.end} se solapan")
    if n_words and not errors:
        cut = sum(d.end - d.start + 1 for d in decisions if d.apply)
        if cut / n_words > max_cut_fraction:
            errors.append(
                f"se cortan {cut} de {n_words} palabras ({cut / n_words:.0%}); "
                f"el máximo permitido es {max_cut_fraction:.0%}"
            )
    if errors:
        raise InvalidDecisions(errors)


def cuts_to_intervals(decisions: list[Decision], words: list[Word]) -> list[Interval]:
    """Tiempos (del original) de las decisiones marcadas con apply=True."""
    return [
        Interval(words[d.start].start, words[d.end].end)
        for d in sorted(decisions, key=lambda d: d.start)
        if d.apply
    ]


def subtract(
    segments: list[Interval], cuts: list[Interval], min_length: float = 0.15
) -> list[Interval]:
    """Quita `cuts` de `segments`; descarta lo que quede más corto que `min_length`."""
    result: list[Interval] = []
    for seg in segments:
        pieces = [seg]
        for c in cuts:
            nxt: list[Interval] = []
            for p in pieces:
                if c.end <= p.start or c.start >= p.end:
                    nxt.append(p)
                    continue
                if c.start > p.start:
                    nxt.append(Interval(p.start, c.start))
                if c.end < p.end:
                    nxt.append(Interval(c.end, p.end))
            pieces = nxt
        result.extend(p for p in pieces if p.length >= min_length)
    return result


def preview(words: list[Word], d: Decision, limit: int = 12) -> str:
    text = [w.text for w in words[d.start : d.end + 1]]
    if len(text) > limit:
        text = text[: limit // 2] + ["…"] + text[-limit // 2 :]
    return " ".join(text)


def proposal_to_json(
    decisions: list[Decision], words: list[Word], media: str, model: str
) -> str:
    items = [
        {
            "id": n,
            "start": d.start,
            "end": d.end,
            "kind": d.kind,
            "reason": d.reason,
            "at": round(words[d.start].start, 2),
            "text": preview(words, d),
            "apply": d.apply,
        }
        for n, d in enumerate(decisions, 1)
    ]
    return json.dumps(
        {
            "media": media,
            "model": model,
            "ayuda": "Pon \"apply\": false en un corte para conservarlo. Solo se aplican los 'apply': true.",
            "decisions": items,
        },
        indent=2,
        ensure_ascii=False,
    )


def proposal_from_json(text: str) -> list[Decision]:
    data = json.loads(text)
    return parse_decisions(data["decisions"])


def proposal_to_markdown(
    decisions: list[Decision], words: list[Word], title: str, removed_seconds: float
) -> str:
    lines = [
        f"# Cortes propuestos: {title}",
        "",
        f"{len(decisions)} cortes, unos {removed_seconds:.0f}s en total. "
        "Edita el `.cortes.json` (`\"apply\": false` para conservar uno) y aplícalos con `--apply-cuts`.",
        "",
    ]
    for n, d in enumerate(decisions, 1):
        label = KIND_LABELS.get(d.kind, d.kind)
        lines.append(
            f"{n}. **[{words[d.start].start:.1f}s] {label}** — {d.reason}\n   > {preview(words, d, 30)}"
        )
    return "\n".join(lines) + "\n"
