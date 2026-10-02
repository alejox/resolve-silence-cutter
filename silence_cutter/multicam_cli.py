"""`python -m silence_cutter multicam proyecto.json ...`: edición por planos con canales con nombre."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import shots as shotlib
from .core import probe_duration, total_length
from .edit import InvalidDecisions
from .pipeline import analyze, apply_cuts, detect_segments, get_words
from .project import InvalidProject, Project, load_project
from .script import build_cues, to_markdown, to_srt


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="silence-cutter multicam",
        description="Elige qué canal se ve (cámara, pantalla, productos) según lo que se dice.",
    )
    p.add_argument("project", help="proyecto.json con los canales (ver examples/proyecto.ejemplo.json)")
    p.add_argument("--propose-cuts", action="store_true", help="Claude propone cortes por contenido (como --analyze); no corta nada")
    p.add_argument("--cuts", default=None, metavar="CORTES.JSON", help="aplica cortes aprobados además de los silencios")
    p.add_argument("--plan", action="store_true", help="Claude propone los planos y escribe <proyecto>.planos.json para revisar")
    p.add_argument("--apply-plan", default=None, metavar="PLANOS.JSON", help="aplica el plan de planos aprobado")
    p.add_argument("--noise", type=lambda v: None if v.lower() == "auto" else float(v), default=None, metavar="auto|DB")
    p.add_argument("--min-silence", type=float, default=0.5)
    p.add_argument("--padding", type=float, default=0.1)
    p.add_argument("--min-speech", type=float, default=0.15)
    p.add_argument("--model", default="small", help="modelo de Whisper")
    p.add_argument("--language", default=None)
    p.add_argument("--ai-model", default=None)
    p.add_argument("--max-cut", type=float, default=0.5)
    p.add_argument("--overlays", default=None, help="overlays.manifest.json (Remotion)")
    p.add_argument("--resolve", action="store_true", help="armar la timeline en Resolve (requiere Studio; sin Studio usa el script del menú)")
    p.add_argument("--out", default=None)
    return p


def load(project_path: str) -> Project:
    try:
        project = load_project(project_path)
    except InvalidProject as exc:
        raise SystemExit(f"Proyecto inválido: {exc}") from exc
    for s in project.sources.values():
        project.durations[s.name] = probe_duration(s.file)
    return project


def propose_plan(project: Project, out: Path, stem: str, model: str, language, ai_model) -> tuple[Path, Path, int]:
    from . import ai

    master = project.master.file
    words = get_words(master, out, stem, model, language)
    total = project.durations[project.audio]
    plan = ai.propose_shots(words, project, total, ai_model)
    plan = shotlib.with_opening(plan, project)
    f = out / f"{stem}.planos.json"
    f.write_text(shotlib.plan_to_json(plan, words, ai_model or ai.DEFAULT_MODEL, project), encoding="utf-8")
    md = out / f"{stem}.planos.md"
    lines = [f"# Planos propuestos: {stem}", ""]
    for n, s in enumerate(plan, 1):
        what = s.source if s.layout == "full" else f"{s.main} + {s.side} ({s.side_pos})"
        lines.append(f"{n}. **[{words[s.start].start:.1f}s] {what}** — {s.reason}")
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f, md, len(plan)


def apply_plan(project: Project, plan_path: Path, out: Path, stem: str, opts, cuts_path=None,
               overlays=None, resolve=None, use_resolve=False) -> str:
    master = project.master.file
    words = get_words(master, out, stem, opts["model"], opts["language"])
    _, segments = detect_segments(master, opts["noise"], opts["min_silence"], opts["padding"], opts["min_speech"])
    if cuts_path:
        segments = apply_cuts(segments, Path(cuts_path), words, opts["min_speech"], opts["max_cut"])
    shots = shotlib.plan_from_json(plan_path.read_text(encoding="utf-8"))
    total = project.durations[project.audio]
    shotlib.validate(shots, words, project, total)
    pieces = shotlib.split_into_pieces(segments, shots, words, project)
    shotlib.check_sync_range(pieces, project)

    cues = build_cues(words, segments)
    (out / f"{stem}.srt").write_text(to_srt(cues), encoding="utf-8")
    (out / f"{stem}.guion.md").write_text(to_markdown(cues, stem), encoding="utf-8")
    msg = f"{total:.1f}s -> {total_length(segments):.1f}s, {len(pieces)} trozos, {len(shots)} planos"

    placements = None
    if overlays:
        from .overlays import load_manifest, place_overlays

        placements, skipped = place_overlays(load_manifest(overlays), segments)
        msg += f"; overlays {len(placements)} ubicados, {len(skipped)} omitidos"
    if use_resolve:
        from .resolve_integration import build_multicam_timeline

        build_multicam_timeline(project, pieces, f"{stem} - multicam", resolve, placements)
        msg += "; timeline creada en Resolve"
    return msg


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    project = load(args.project)
    pfile = Path(args.project)
    out = Path(args.out) if args.out else pfile.parent
    out.mkdir(parents=True, exist_ok=True)
    stem = pfile.stem
    opts = {"noise": args.noise, "min_silence": args.min_silence, "padding": args.padding,
            "min_speech": args.min_speech, "model": args.model, "language": args.language,
            "max_cut": args.max_cut}

    if args.propose_cuts:
        cuts, report, n = analyze(project.master.file, out, stem, args.model, args.language, args.ai_model, args.max_cut)
        print(f"Claude propone {n} cortes.\n  Revisa: {report}\n  Edita:  {cuts}")
        return 0
    if args.plan:
        f, md, n = propose_plan(project, out, stem, args.model, args.language, args.ai_model)
        print(f"Claude propone {n} planos.\n  Revisa: {md}\n  Edita:  {f}")
        print(f"Luego: python -m silence_cutter multicam {args.project} --apply-plan {f}")
        return 0
    if args.apply_plan:
        try:
            print(apply_plan(project, Path(args.apply_plan), out, stem, opts, args.cuts,
                             args.overlays, None, args.resolve))
        except InvalidDecisions as exc:
            raise SystemExit("El plan no es válido:\n- " + "\n- ".join(exc.errors)) from exc
        return 0
    raise SystemExit("Indica --plan, --apply-plan o --propose-cuts.")
