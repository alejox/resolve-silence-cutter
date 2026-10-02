import unittest

from silence_cutter.core import Interval
from silence_cutter.overlays import place_overlays

SEGS = [Interval(1.0, 3.0), Interval(5.0, 6.0)]


def item(at, dur, t="keyword"):
    return {"file": f"/x/{t}.mov", "at": at, "dur": dur, "type": t}


class PlaceOverlayTests(unittest.TestCase):
    def test_start_is_remapped_across_cuts(self):
        placed, skipped = place_overlays([item(1.5, 1.0), item(5.2, 0.5)], SEGS)
        self.assertEqual(skipped, [])
        self.assertAlmostEqual(placed[0].start, 0.5)
        self.assertAlmostEqual(placed[1].start, 2.2)  # 2s del primer tramo + 0.2

    def test_beat_in_removed_silence_is_skipped(self):
        placed, skipped = place_overlays([item(4.0, 1.0)], SEGS)
        self.assertEqual(placed, [])
        self.assertEqual(len(skipped), 1)

    def test_duration_trimmed_to_remaining_segment(self):
        placed, _ = place_overlays([item(2.5, 4.0)], SEGS)
        self.assertAlmostEqual(placed[0].duration, 0.5)

    def test_duration_kept_when_it_fits(self):
        placed, _ = place_overlays([item(1.0, 1.5)], SEGS)
        self.assertAlmostEqual(placed[0].duration, 1.5)


if __name__ == "__main__":
    unittest.main()
