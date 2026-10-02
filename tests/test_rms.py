import unittest

from silence_cutter.core import (
    Interval, auto_threshold, parse_rms_levels, silences_from_levels,
)

SAMPLE = """frame:0    pts:0       pts_time:0
lavfi.astats.Overall.RMS_level=-inf
frame:1    pts:800     pts_time:0.05
lavfi.astats.Overall.RMS_level=-38.5
frame:2    pts:1600    pts_time:0.1
lavfi.astats.Overall.RMS_level=-27.25
"""


class RmsTests(unittest.TestCase):
    def test_parse_maps_inf_to_floor(self):
        self.assertEqual(parse_rms_levels(SAMPLE), [-120.0, -38.5, -27.25])

    def test_noisy_room_is_still_silence(self):
        # ruido a -39 dB con habla a -27 dB: el umbral cae entre ambos y separa las pausas
        levels = [-39.0] * 20 + [-27.0] * 20 + [-39.0] * 20
        thr = auto_threshold(levels)
        self.assertTrue(-39.0 < thr < -27.0, thr)
        sil = silences_from_levels(levels, thr, min_silence=0.5, duration=3.0)
        self.assertEqual(sil, [Interval(0.0, 1.0), Interval(2.0, 3.0)])

    def test_short_dips_between_words_are_not_cut(self):
        levels = [-27.0] * 10 + [-39.0] * 4 + [-27.0] * 10  # 0.2 s entre palabras
        thr = auto_threshold(levels + [-39.0] * 10)
        self.assertEqual(silences_from_levels(levels, thr, 0.5, 1.2), [])

    def test_open_silence_at_end_is_closed_at_duration(self):
        levels = [-27.0] * 10 + [-39.0] * 20
        sil = silences_from_levels(levels, -33.0, 0.5, 1.5)
        self.assertEqual(sil, [Interval(0.5, 1.5)])

    def test_constant_level_cuts_nothing(self):
        levels = [-30.0] * 100
        self.assertEqual(silences_from_levels(levels, auto_threshold(levels), 0.5, 5.0), [])

    def test_empty(self):
        self.assertEqual(auto_threshold([]), -60.0)


class RenderTests(unittest.TestCase):
    def test_render_cut_duration_matches_segments(self):
        import subprocess, tempfile
        from pathlib import Path

        from silence_cutter.core import render_cut

        with tempfile.TemporaryDirectory() as d:
            src, out = Path(d) / "s.mp4", Path(d) / "o.mp4"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                            "testsrc=d=6:s=320x180:r=24", "-f", "lavfi", "-i", "sine=f=440:d=6",
                            "-shortest", "-c:v", "libx264", str(src)], check=True)
            render_cut(str(src), [Interval(0.0, 2.0), Interval(4.0, 5.0)], str(out), height=144)
            dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                        "-of", "default=nw=1:nk=1", str(out)],
                                       capture_output=True, text=True, check=True).stdout)
            self.assertAlmostEqual(dur, 3.0, delta=0.2)

    def test_render_cut_outputs_8bit_bt709_even_for_10bit_bt2020_source(self):
        import subprocess, tempfile
        from pathlib import Path

        from silence_cutter.core import render_cut

        with tempfile.TemporaryDirectory() as d:
            src, out = Path(d) / "s.mov", Path(d) / "o.mp4"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                            "testsrc=d=3:s=320x180:r=24", "-f", "lavfi", "-i", "sine=f=440:d=3",
                            "-shortest", "-pix_fmt", "yuv420p10le", "-c:v", "libx265",
                            "-colorspace", "bt2020nc", "-color_primaries", "bt2020",
                            str(src)], check=True)
            render_cut(str(src), [Interval(0.0, 2.0)], str(out), height=144)
            info = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
                                   "stream=pix_fmt,color_space", "-of", "csv=p=0", str(out)],
                                  capture_output=True, text=True, check=True).stdout.strip()
            self.assertEqual(info, "yuv420p,bt709")


if __name__ == "__main__":
    unittest.main()
