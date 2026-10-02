import unittest

from silence_cutter.core import (
    Interval, parse_silencedetect, remap_time, speech_segments, total_length,
)
from silence_cutter.script import Word, build_cues, to_srt

LOG = """\
[silencedetect @ 0x1] silence_start: -0.0012
[silencedetect @ 0x1] silence_end: 1.5 | silence_duration: 1.5
[silencedetect @ 0x1] silence_start: 5
[silencedetect @ 0x1] silence_end: 7.25 | silence_duration: 2.25
[silencedetect @ 0x1] silence_start: 9.5
"""


class CoreTests(unittest.TestCase):
    def test_parse_clamps_and_closes_open_silence(self):
        s = parse_silencedetect(LOG, 10.0)
        self.assertEqual(s, [Interval(0.0, 1.5), Interval(5.0, 7.25), Interval(9.5, 10.0)])

    def test_speech_segments_inverts_with_padding(self):
        s = parse_silencedetect(LOG, 10.0)
        seg = speech_segments(s, 10.0, padding=0.1)
        self.assertEqual(seg, [Interval(1.4, 5.1), Interval(7.15, 9.6)])

    def test_padding_merges_close_segments(self):
        seg = speech_segments([Interval(2.0, 2.1)], 5.0, padding=0.1, min_speech=0.0)
        self.assertEqual(seg, [Interval(0.0, 5.0)])

    def test_short_blips_dropped(self):
        seg = speech_segments([Interval(0, 1), Interval(1.05, 5)], 5.0, padding=0, min_speech=0.15)
        self.assertEqual(seg, [])

    def test_remap_time(self):
        seg = [Interval(1.0, 3.0), Interval(5.0, 6.0)]
        self.assertEqual(remap_time(2.0, seg), 1.0)
        self.assertEqual(remap_time(5.5, seg), 2.5)
        self.assertIsNone(remap_time(4.0, seg))
        self.assertEqual(total_length(seg), 3.0)


class ScriptTests(unittest.TestCase):
    def test_cues_drop_cut_words_and_shift_times(self):
        seg = [Interval(1.0, 3.0), Interval(5.0, 6.0)]
        words = [
            Word(1.2, 1.6, "hola"), Word(2.0, 2.5, "mundo"),
            Word(3.5, 3.9, "relleno"),  # en el silencio cortado
            Word(5.1, 5.6, "chao"),
        ]
        cues = build_cues(words, seg)
        self.assertEqual([c.text for c in cues], ["hola mundo", "chao"])
        self.assertAlmostEqual(cues[0].start, 0.2)
        self.assertAlmostEqual(cues[1].start, 2.1)

    def test_srt_format(self):
        cues = build_cues([Word(0.0, 1.0, "hola")], [Interval(0.0, 2.0)])
        self.assertTrue(to_srt(cues).startswith("1\n00:00:00,000 --> 00:00:01,000\nhola"))


if __name__ == "__main__":
    unittest.main()
