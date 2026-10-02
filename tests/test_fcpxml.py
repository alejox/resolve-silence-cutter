import json
import os
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

from silence_cutter.cli import main
from silence_cutter.core import Interval
from silence_cutter.fcpxml import MediaInfo, build_fcpxml, parse_timecode, probe_media

try:
    import opentimelineio as otio
    otio.adapters.read_from_string  # noqa: B018
    HAS_FCPX = "fcpx_xml" in otio.adapters.available_adapter_names()
except Exception:  # pip install opentimelineio otio-fcpx-xml-adapter
    otio, HAS_FCPX = None, False

REPO = Path(__file__).resolve().parent.parent


def info(path="/media/Mi video & prueba.mov", fps=Fraction(24), tc=0, audio=True):
    return MediaInfo(path, fps, 1920, 1080, 26.16875, audio, 48000, 2, tc)


class TimecodeTests(unittest.TestCase):
    def test_non_drop(self):
        self.assertEqual(parse_timecode("14:22:49:00", Fraction(24)), 1242456)
        self.assertEqual(parse_timecode("00:00:01:12", Fraction(24)), 36)

    def test_drop_frame_known_values(self):
        fps = Fraction(30000, 1001)
        self.assertEqual(parse_timecode("00:01:00;02", fps), 1800)    # primer fotograma tras el salto
        self.assertEqual(parse_timecode("00:10:00;00", fps), 17982)   # cada 10 minutos no se salta

    def test_invalid(self):
        with self.assertRaises(ValueError):
            parse_timecode("abc", Fraction(24))


class BuildTests(unittest.TestCase):
    def parse(self, xml):
        return ET.fromstring(xml.split("<!DOCTYPE fcpxml>", 1)[1])

    def test_structure_offsets_and_total(self):
        root = self.parse(build_fcpxml(info(), [Interval(0, 2.0), Interval(4.0, 5.5)], "t"))
        clips = root.findall(".//spine/asset-clip")
        self.assertEqual([c.get("offset") for c in clips], ["0s", "2s"])
        self.assertEqual([c.get("duration") for c in clips], ["2s", "3/2s"])
        self.assertEqual(root.find(".//sequence").get("duration"), "7/2s")  # 2 s + 1,5 s

    def test_embedded_timecode_is_the_source_start(self):
        # sin esto Resolve podría leer el medio desde el segundo 0 y desfasar todo
        x = build_fcpxml(info(tc=1242456), [Interval(10.0, 12.0)], "t")
        root = self.parse(x)
        self.assertEqual(root.find(".//asset").get("start"), "51769s")
        self.assertEqual(root.find(".//asset-clip").get("start"), "51779s")  # 51769 + 10 s

    def test_fractional_frame_rates_stay_exact(self):
        x = build_fcpxml(info(fps=Fraction(30000, 1001)), [Interval(0, 1.0)], "t")
        self.assertEqual(self.parse(x).find(".//format").get("frameDuration"), "1001/30000s")
        self.assertIn('duration="1001/1000s"', x)  # 30 fotogramas a 29,97 fps: exacto, sin decimales

    def test_special_characters_are_escaped_and_url_is_encoded(self):
        x = build_fcpxml(info(path='/media/Mi "video" & prueba.mov'), [Interval(0, 1)], 'a & b "c"')
        root = self.parse(x)  # si el escape fallara, esto no parsea
        self.assertEqual(root.find(".//project").get("name"), 'a & b "c"')
        self.assertIn("%20", root.find(".//asset").get("src"))
        self.assertTrue(root.find(".//asset").get("src").startswith("file:///"))

    def test_video_only_media_has_no_audio_attributes(self):
        root = self.parse(build_fcpxml(info(audio=False), [Interval(0, 1)], "t"))
        self.assertIsNone(root.find(".//asset").get("hasAudio"))

    def test_empty_segments_rejected(self):
        with self.assertRaises(ValueError):
            build_fcpxml(info(), [], "t")
        with self.assertRaises(ValueError):
            build_fcpxml(info(), [Interval(1.0, 1.001)], "t")  # menos de un fotograma


@unittest.skipUnless(HAS_FCPX, "falta opentimelineio y otio-fcpx-xml-adapter")
class IndependentReaderTests(unittest.TestCase):
    def test_otio_reads_the_same_durations_and_sources(self):
        x = build_fcpxml(info("/media/clip.mov", tc=1242456), [Interval(0, 8.0), Interval(10.0, 14.5)], "demo")
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "t.fcpxml"
            f.write_text(x, encoding="utf-8")
            result = otio.adapters.read_from_file(str(f), adapter_name="fcpx_xml")
        tl = next(c for c in result.find_children(descended_from_type=otio.schema.Timeline))
        self.assertAlmostEqual(tl.duration().to_seconds(), 12.5, places=2)
        clips = [c for c in tl.find_clips()]
        self.assertEqual(len(clips), 2)
        self.assertAlmostEqual(clips[0].source_range.start_time.to_seconds(), 51769.0, places=2)
        self.assertAlmostEqual(clips[1].source_range.start_time.to_seconds(), 51779.0, places=2)  # +10 s


class EndToEndTests(unittest.TestCase):
    def test_cli_writes_fcpxml_and_the_latest_copy_for_the_menu_script(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            clip = d / "mi clip.mov"
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                 "-f", "lavfi", "-i", "testsrc=d=15:s=320x180:r=24",
                 "-f", "lavfi", "-i", "sine=f=440:d=7", "-f", "lavfi", "-i", "anullsrc=d=2",
                 "-f", "lavfi", "-i", "sine=f=660:d=6",
                 "-filter_complex", "[1][2][3]concat=n=3:v=0:a=1[a]", "-map", "0:v", "-map", "[a]",
                 "-c:v", "libx264", "-timecode", "14:22:49:00", "-shortest", str(clip)], check=True)
            self.assertEqual(probe_media(str(clip)).tc_start_frames, 1242456)

            latest = d / "latest.fcpxml"
            os.environ["SILENCE_CUTTER_LATEST"] = str(latest)
            try:
                self.assertEqual(main([str(clip), "--no-transcribe", "--fcpxml"]), 0)
            finally:
                os.environ.pop("SILENCE_CUTTER_LATEST")
            out = d / "mi clip.fcpxml"
            self.assertTrue(out.is_file())
            self.assertEqual(out.read_text(encoding="utf-8"), latest.read_text(encoding="utf-8"))
            root = ET.fromstring(out.read_text(encoding="utf-8").split("<!DOCTYPE fcpxml>", 1)[1])
            clips = root.findall(".//spine/asset-clip")
            self.assertEqual(len(clips), 2)  # el silencio de 2 s separó el audio en dos tramos
            self.assertEqual(clips[0].get("start"), "51769s")  # arranca en el timecode del archivo
            self.assertIn("mi%20clip.mov", root.find(".//asset").get("src"))


if __name__ == "__main__":
    unittest.main()
