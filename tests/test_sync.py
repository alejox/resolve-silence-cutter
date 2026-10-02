import array
import json
import random
import tempfile
import unittest
import wave
from pathlib import Path

from silence_cutter.cli import main
from silence_cutter.project import load_project
from silence_cutter.sync import has_audio, sync_offset

RATE = 8000


def speechlike(seconds, seed):
    """Ráfagas de ruido (palabras) separadas por pausas de duración irregular."""
    rng = random.Random(seed)
    out, t = [], 0.0
    while t < seconds:
        gap = rng.uniform(0.15, 0.9)
        burst = rng.uniform(0.2, 1.1)
        out += [0.0] * int(gap * RATE)
        out += [rng.uniform(-0.5, 0.5) for _ in range(int(burst * RATE))]
        t += gap + burst
    return out[: int(seconds * RATE)]


def write_wav(path, samples, gain=1.0, noise=0.01, seed=99):
    rng = random.Random(seed)
    data = array.array("h", [int(max(-1, min(1, s * gain + rng.uniform(-noise, noise))) * 32767) for s in samples])
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(data.tobytes())


class SyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        cls.sig = speechlike(45, seed=1)
        cls.master = d / "master.wav"
        write_wav(cls.master, cls.sig)
        # el canal oye lo mismo 3.37 s más tarde, más bajo y con más ruido de fondo
        cls.late = d / "late.wav"
        write_wav(cls.late, [0.0] * int(3.37 * RATE) + cls.sig, gain=0.4, noise=0.03)
        # el canal empezó a grabar 2.0 s DESPUÉS del maestro
        cls.early = d / "early.wav"
        write_wav(cls.early, cls.sig[int(2.0 * RATE):], gain=0.7, noise=0.02)
        cls.other = d / "other.wav"
        write_wav(cls.other, speechlike(45, seed=7))
        cls.d = d

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_positive_offset(self):
        r = sync_offset(str(self.master), str(self.late))
        self.assertAlmostEqual(r.offset, 3.37, delta=0.03)
        self.assertGreaterEqual(r.confidence, 0.5)

    def test_negative_offset(self):
        r = sync_offset(str(self.master), str(self.early))
        self.assertAlmostEqual(r.offset, -2.0, delta=0.03)
        self.assertGreaterEqual(r.confidence, 0.5)

    def test_unrelated_audio_has_low_confidence(self):
        r = sync_offset(str(self.master), str(self.other))
        self.assertLess(r.confidence, 0.5)

    def test_channel_without_audio_is_explained(self):
        import subprocess
        silent = self.d / "mudo.mp4"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        "color=c=blue:d=2:s=160x90:r=24", "-c:v", "libx264", str(silent)], check=True)
        self.assertFalse(has_audio(str(silent)))
        with self.assertRaises(ValueError):
            sync_offset(str(self.master), str(silent))

    def test_sync_flag_writes_offsets_that_project_loading_applies(self):
        d = self.d
        proj = {"audio": "pantalla", "default": "camara", "sources": {
            "pantalla": {"file": "master.wav", "role": "screen"},
            "camara": {"file": "late.wav", "role": "camera"}}}
        (d / "p.json").write_text(json.dumps(proj))
        self.assertEqual(main(["multicam", str(d / "p.json"), "--sync"]), 0)
        saved = json.loads((d / "p.offsets.json").read_text())["offsets"]
        self.assertAlmostEqual(saved["camara"], 3.37, delta=0.03)
        self.assertNotIn("pantalla", saved)  # el maestro no se desplaza
        loaded = load_project(str(d / "p.json"), check_files=False)
        self.assertAlmostEqual(loaded.sources["camara"].offset, 3.37, delta=0.03)
        self.assertEqual(loaded.sources["pantalla"].offset, 0.0)


if __name__ == "__main__":
    unittest.main()
