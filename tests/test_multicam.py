import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from silence_cutter import ai
from silence_cutter import shots as sh
from silence_cutter.cli import main
from silence_cutter.core import Interval
from silence_cutter.edit import InvalidDecisions
from silence_cutter.pipeline import save_words, words_file
from silence_cutter.project import InvalidProject, describe, parse_project
from silence_cutter.resolve_integration import build_multicam_timeline, pip_properties
from silence_cutter.script import Word

WORDS = [Word(i + 1.0, i + 1.8, f"p{i}") for i in range(10)]  # p0 1.0-1.8 ... p9 10.0-10.8
DATA = {
    "audio": "pantalla",
    "default": "camara",
    "sources": {
        "pantalla": {"file": "pantalla.mp4", "role": "screen", "description": "demo de la app"},
        "camara": {"file": "camara.mp4", "role": "camera", "description": "yo hablando"},
        "caja": {"file": "caja.mp4", "role": "product", "description": "caja del producto"},
        "mic": {"file": "mic.wav", "role": "audio"},
    },
}


def project(durations=None):
    p = parse_project(DATA, check_files=False)
    p.durations.update(durations or {"pantalla": 15.0, "camara": 15.0, "caja": 3.0, "mic": 15.0})
    return p


class ProjectTests(unittest.TestCase):
    def test_defaults_and_describe(self):
        p = parse_project({"sources": {k: v for k, v in DATA["sources"].items() if k != "mic"}}, check_files=False)
        self.assertEqual((p.audio, p.default_source), ("pantalla", "camara"))
        p.durations["caja"] = 3.0
        self.assertIn("caja [product] (dura 3.0s): caja del producto", describe(p))
        self.assertNotIn("mic", describe(project()))  # el audio no se muestra a Claude

    def test_rejects_bad_projects(self):
        bad = [
            {"sources": {"a": {"file": "x", "role": "magia"}}},
            {"audio": "nope", "sources": DATA["sources"]},
            {"audio": "caja", "sources": DATA["sources"]},
            {"sources": {"mic": {"file": "m.wav", "role": "audio"}}},
        ]
        for d in bad:
            with self.assertRaises(InvalidProject, msg=d):
                parse_project(d, check_files=False)

    def test_independent_audio_channel(self):
        p = parse_project({**DATA, "audio": "mic"}, check_files=False)
        self.assertEqual(p.master.name, "mic")


class ShotValidationTests(unittest.TestCase):
    def errs(self, raw, total=15.0):
        with self.assertRaises(InvalidDecisions) as cm:
            sh.validate(sh.parse_shots(raw), WORDS, project(), total)
        return " ".join(cm.exception.errors)

    def test_valid_plan(self):
        sh.validate(sh.parse_shots([
            {"start": 0, "layout": "full", "source": "camara"},
            {"start": 3, "layout": "pip", "main": "pantalla", "side": "camara", "side_pos": "left"},
            {"start": 6, "layout": "full", "source": "caja"},   # 3.0s -> 3.0 de toma, cabe
            {"start": 9, "layout": "full", "source": "camara"},
        ]), WORDS, project(), 15.0)

    def test_unknown_audio_and_missing_channels(self):
        self.assertIn("'nada' no existe", self.errs([{"start": 0, "layout": "full", "source": "nada"}]))
        self.assertIn("solo audio", self.errs([{"start": 0, "layout": "full", "source": "mic"}]))
        self.assertIn("faltan canales", self.errs([{"start": 0, "layout": "pip", "main": "pantalla"}]))

    def test_pip_rules(self):
        base = {"start": 0, "layout": "pip", "main": "pantalla"}
        self.assertIn("mismo canal", self.errs([{**base, "side": "pantalla"}]))
        self.assertIn("side_pos", self.errs([{**base, "side": "camara", "side_pos": "arriba"}]))
        self.assertIn("producto no va como lateral", self.errs([{**base, "side": "caja"}]))

    def test_ordering_and_word_range(self):
        self.assertIn("ordenados", self.errs([
            {"start": 4, "layout": "full", "source": "camara"}, {"start": 4, "layout": "full", "source": "pantalla"}]))
        self.assertIn("no existe (0-9)", self.errs([{"start": 50, "layout": "full", "source": "camara"}]))

    def test_product_shot_longer_than_its_file(self):
        msg = self.errs([{"start": 2, "layout": "full", "source": "caja"},   # hasta el final: 12s > 3s
                         ])
        self.assertIn("'caja' dura 3.0s", msg)

    def test_non_integer_start(self):
        with self.assertRaises(InvalidDecisions):
            sh.parse_shots([{"start": "2", "layout": "full", "source": "camara"}])


class PieceTests(unittest.TestCase):
    def test_split_at_shot_changes_and_product_play_accumulates(self):
        shots = [sh.Shot(0, "full", source="camara"),
                 sh.Shot(2, "full", source="caja"),    # 3.0s
                 sh.Shot(6, "full", source="camara")]  # 7.0s
        segs = [Interval(0.0, 5.0), Interval(6.0, 9.0)]  # corte entre 5 y 6
        pieces = sh.split_into_pieces(segs, shots, WORDS, project())
        got = [(round(p.interval.start, 2), round(p.interval.end, 2), p.shot.source, round(p.play_from, 2)) for p in pieces]
        self.assertEqual(got, [
            (0.0, 3.0, "camara", 0.0),
            (3.0, 5.0, "caja", 0.0),
            (6.0, 7.0, "caja", 2.0),    # la toma sigue donde iba, no salta el trozo cortado
            (7.0, 9.0, "camara", 0.0),
        ])

    def test_opening_uses_default_when_plan_starts_late(self):
        pieces = sh.split_into_pieces([Interval(0.0, 6.0)], [sh.Shot(3, "full", source="pantalla")], WORDS, project())
        self.assertEqual([p.shot.source for p in pieces], ["camara", "pantalla"])

    def test_sync_range_catches_bad_offset(self):
        data = json.loads(json.dumps(DATA))
        data["sources"]["camara"]["offset"] = 2.0
        p = parse_project(data, check_files=False)
        p.durations.update({"pantalla": 15.0, "camara": 15.0, "caja": 3.0, "mic": 15.0})
        pieces = sh.split_into_pieces([Interval(0.0, 14.0)], [sh.Shot(0, "full", source="camara")], WORDS, p)
        with self.assertRaises(InvalidDecisions) as cm:
            sh.check_sync_range(pieces, p)
        self.assertIn("offset", str(cm.exception))


class AiShotsTests(unittest.TestCase):
    def test_retry_after_unknown_channel_and_channels_are_described(self):
        replies = ['{"shots": [{"start": 0, "layout": "full", "source": "webcam", "reason": "r"}]}',
                   '{"shots": [{"start": 0, "layout": "full", "source": "camara", "reason": "r"}]}']
        seen = []

        def caller(system, messages, model):
            seen.append(messages)
            return replies[len(seen) - 1]

        out = ai.propose_shots(WORDS, project(), 15.0, "m", caller)
        self.assertEqual(out[0].source, "camara")
        first = seen[0][0]["content"]
        self.assertIn("camara [camera]: yo hablando", first)
        self.assertIn("[0]p0", first)
        self.assertIn("'webcam' no existe", seen[1][-1]["content"])


class FakeClip:
    def __init__(self, path, fps="30"):
        self.path, self.fps = path, fps

    def GetClipProperty(self, k):
        return {"File Path": self.path, "FPS": self.fps}.get(k)


class FakeItem:
    def __init__(self):
        self.props = {}

    def SetProperty(self, k, v):
        self.props[k] = v
        return True


class FakeTL:
    tracks = 1

    def GetSetting(self, k):
        return {"timelineFrameRate": "30", "timelineResolutionWidth": "1920", "timelineResolutionHeight": "1080"}[k]

    def GetStartFrame(self):
        return 108000

    def GetTrackCount(self, t):
        return self.tracks

    def AddTrack(self, t):
        self.tracks += 1
        return True


class FakeResolve:
    def __init__(self, files):
        self.infos, self.items, self.tl, self._files = None, [], FakeTL(), files
        r = self
        class Pool:
            def ImportMedia(s, paths): return [FakeClip(p) for p in paths]
            def CreateEmptyTimeline(s, n): return r.tl
            def AppendToTimeline(s, infos):
                r.infos = infos
                r.items = [FakeItem() for _ in infos]
                return r.items
        class Proj:
            def GetMediaPool(s): return Pool()
            def SetCurrentTimeline(s, t): pass
        class PM:
            def GetCurrentProject(s): return Proj()
        self.pm = PM()

    def GetProjectManager(self):
        return self.pm


class ResolveBuildTests(unittest.TestCase):
    def test_tracks_audio_video_and_pip(self):
        with tempfile.TemporaryDirectory() as d:
            data = json.loads(json.dumps(DATA))
            for v in data["sources"].values():
                v["file"] = str(Path(d) / v["file"])
            data["sources"]["camara"]["offset"] = 0.5
            p = parse_project(data, check_files=False)
            shots = [sh.Shot(0, "pip", main="pantalla", side="camara", side_pos="right"),
                     sh.Shot(3, "full", source="caja")]
            pieces = sh.split_into_pieces([Interval(0.0, 5.0)], shots, WORDS, p)
            r = FakeResolve(None)
            build_multicam_timeline(p, pieces, "t", r)
            info = r.infos
            # trozo 1 (0-4s, pip): audio A1 + pantalla V1 + cámara V2; trozo 2 (4-5s): audio + caja
            self.assertEqual([(i["mediaType"], i["trackIndex"]) for i in info],
                             [(2, 1), (1, 1), (1, 2), (2, 1), (1, 1)])
            self.assertEqual(info[0]["recordFrame"], 108000)
            self.assertEqual(info[3]["recordFrame"], 108000 + 4 * 30)     # la palabra 3 empieza en 4.0s
            self.assertEqual(info[3]["startFrame"], 4 * 30)               # la voz sigue continua en el maestro
            self.assertEqual(info[4]["startFrame"], 0)                    # la toma de producto arranca en su inicio
            cam = info[2]
            self.assertEqual(cam["startFrame"], round(0.5 * 30))           # offset de sincronía aplicado
            self.assertEqual(r.items[2].props["ZoomX"], 0.28)
            self.assertGreater(r.items[2].props["Pan"], 0)                  # derecha
            self.assertLess(r.items[2].props["Tilt"], 0)                    # abajo
            self.assertEqual(r.tl.tracks, 2)

    def test_pip_left_mirrors_pan(self):
        right, left = pip_properties("right", 1920, 1080), pip_properties("left", 1920, 1080)
        self.assertEqual(right["Pan"], -left["Pan"])
        self.assertEqual(right["Tilt"], left["Tilt"])


class EndToEndTests(unittest.TestCase):
    def test_apply_plan_on_real_media(self):
        def make(path, args):
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args, str(path)], check=True)

        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            # pantalla: video + voz con 2s de silencio en 7-9; cámara: solo imagen; caja: 3s
            make(d / "pantalla.mp4", ["-f", "lavfi", "-i", "testsrc=d=15:s=320x180:r=30",
                 "-f", "lavfi", "-i", "sine=f=440:d=7", "-f", "lavfi", "-i", "anullsrc=d=2",
                 "-f", "lavfi", "-i", "sine=f=660:d=6", "-filter_complex", "[1][2][3]concat=n=3:v=0:a=1[a]",
                 "-map", "0:v", "-map", "[a]", "-c:v", "mpeg4", "-shortest"])
            make(d / "camara.mp4", ["-f", "lavfi", "-i", "color=c=blue:d=15:s=320x180:r=30", "-c:v", "mpeg4"])
            make(d / "caja.mp4", ["-f", "lavfi", "-i", "color=c=red:d=3:s=320x180:r=30", "-c:v", "mpeg4"])
            proj = {"audio": "pantalla", "default": "camara", "sources": {
                "pantalla": {"file": "pantalla.mp4", "role": "screen"},
                "camara": {"file": "camara.mp4", "role": "camera"},
                "caja": {"file": "caja.mp4", "role": "product"}}}
            (d / "demo.json").write_text(json.dumps(proj))
            save_words(words_file(d, "demo"), WORDS)
            plan = {"shots": [
                {"start": 0, "layout": "full", "source": "camara", "reason": "intro"},
                {"start": 3, "layout": "pip", "main": "pantalla", "side": "camara", "reason": "explica"},
                {"start": 6, "layout": "full", "source": "caja", "reason": "producto"},
                {"start": 9, "layout": "full", "source": "camara", "reason": "cierre"}]}
            (d / "demo.planos.json").write_text(json.dumps(plan))
            self.assertEqual(main(["multicam", str(d / "demo.json"), "--apply-plan", str(d / "demo.planos.json")]), 0)
            self.assertTrue((d / "demo.srt").is_file())
            self.assertTrue((d / "demo.guion.md").is_file())

            # un plan con un canal inventado se rechaza con un mensaje claro y no escribe nada nuevo
            plan["shots"][1]["main"] = "nada"
            (d / "malo.json").write_text(json.dumps(plan))
            with self.assertRaises(SystemExit) as cm:
                main(["multicam", str(d / "demo.json"), "--apply-plan", str(d / "malo.json")])
            self.assertIn("'nada' no existe", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
