import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from silence_cutter import ai
from silence_cutter.cli import main
from silence_cutter.core import Interval
from silence_cutter.edit import (
    Decision, InvalidDecisions, cuts_to_intervals, parse_decisions, proposal_from_json,
    proposal_to_json, subtract, validate,
)
from silence_cutter.pipeline import analyze, save_words, words_file
from silence_cutter.script import Word

WORDS = [Word(i + 1.0, i + 1.8, f"p{i}") for i in range(10)]  # p0 en 1.0-1.8 ... p9 en 10.0-10.8


def dec(start, end, kind="repeat", reason="x", apply=True):
    return Decision(start, end, kind, reason, apply)


class ValidateTests(unittest.TestCase):
    def errors(self, decisions, n=10, frac=0.5):
        with self.assertRaises(InvalidDecisions) as cm:
            validate(decisions, n, frac)
        return cm.exception.errors

    def test_valid_passes(self):
        validate([dec(1, 2), dec(5, 5)], 10)

    def test_out_of_range_and_inverted(self):
        self.assertTrue(self.errors([dec(8, 12)]))
        self.assertTrue(self.errors([dec(5, 3)]))
        self.assertTrue(self.errors([dec(-1, 2)]))

    def test_overlap(self):
        self.assertIn("se solapan", " ".join(self.errors([dec(1, 3), dec(3, 4)])))

    def test_unknown_kind_and_missing_reason(self):
        msg = " ".join(self.errors([dec(1, 2, kind="magia", reason="")]))
        self.assertIn("magia", msg)
        self.assertIn("motivo", msg)

    def test_too_much_cut(self):
        self.assertIn("máximo", " ".join(self.errors([dec(0, 6)])))

    def test_apply_false_does_not_count_toward_limit(self):
        validate([dec(0, 8, apply=False)], 10)

    def test_non_integer_indices_rejected(self):
        with self.assertRaises(InvalidDecisions):
            parse_decisions([{"start": "1", "end": 2}])
        with self.assertRaises(InvalidDecisions):
            parse_decisions([{"start": True, "end": 2}])


class CutMathTests(unittest.TestCase):
    def test_cuts_use_word_times_and_skip_unapplied(self):
        cuts = cuts_to_intervals([dec(2, 3), dec(6, 6, apply=False)], WORDS)
        self.assertEqual(cuts, [Interval(3.0, 4.8)])

    def test_subtract_splits_and_drops_slivers(self):
        segs = [Interval(0, 10)]
        out = subtract(segs, [Interval(3, 4), Interval(9.9, 10)], min_length=0.15)
        self.assertEqual(out, [Interval(0, 3), Interval(4, 9.9)])

    def test_subtract_cut_spanning_segments(self):
        out = subtract([Interval(0, 2), Interval(3, 5)], [Interval(1, 4)])
        self.assertEqual(out, [Interval(0, 1), Interval(4, 5)])

    def test_roundtrip_keeps_apply_flag(self):
        txt = proposal_to_json([dec(1, 2), dec(5, 5, apply=False)], WORDS, "v.mp4", "m")
        back = proposal_from_json(txt)
        self.assertEqual([d.apply for d in back], [True, False])
        self.assertEqual(json.loads(txt)["decisions"][0]["text"], "p1 p2")


class AiTests(unittest.TestCase):
    def test_extract_json_from_fenced_and_chatty(self):
        self.assertEqual(ai.extract_json('```json\n{"decisions": []}\n```')["decisions"], [])
        self.assertEqual(ai.extract_json('Claro: {"decisions": []} listo')["decisions"], [])
        with self.assertRaises(InvalidDecisions):
            ai.extract_json("no hay json")

    def test_transcript_numbers_words_and_breaks_on_pauses(self):
        words = [Word(0, 0.5, "hola"), Word(0.6, 1.0, "mundo"), Word(3.0, 3.4, "otra")]
        self.assertEqual(ai.format_transcript(words), "(0.0s) [0]hola [1]mundo\n(3.0s) [2]otra")

    def test_retries_once_with_errors_then_succeeds(self):
        replies = ['{"decisions": [{"start": 5, "end": 99, "kind": "repeat", "reason": "r"}]}',
                   '{"decisions": [{"start": 5, "end": 6, "kind": "repeat", "reason": "r"}]}']
        seen = []

        def caller(system, messages, model):
            seen.append(messages)
            return replies[len(seen) - 1]

        out = ai.propose_cuts(WORDS, "m", caller=caller)
        self.assertEqual((out[0].start, out[0].end), (5, 6))
        self.assertEqual(len(seen), 2)
        self.assertIn("no es válida", seen[1][-1]["content"])

    def test_gives_up_after_second_invalid_reply(self):
        bad = '{"decisions": [{"start": 5, "end": 99, "kind": "repeat", "reason": "r"}]}'
        with self.assertRaises(InvalidDecisions):
            ai.propose_cuts(WORDS, "m", caller=lambda *_: bad)

    def test_empty_proposal_is_fine(self):
        self.assertEqual(ai.propose_cuts(WORDS, "m", caller=lambda *_: '{"decisions": []}'), [])


class CallClaudeTests(unittest.TestCase):
    def test_request_shape_and_response_parsing(self):
        captured = {}

        def fake_urlopen(req, timeout):
            captured["req"] = req
            body = {"content": [{"type": "text", "text": '{"decisions": []}'}]}
            return io.BytesIO(json.dumps(body).encode())

        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k-test"}), \
                mock.patch("urllib.request.urlopen", fake_urlopen):
            text = ai.call_claude("sys", [{"role": "user", "content": "hola"}], "m-1")
        req = captured["req"]
        self.assertEqual(text, '{"decisions": []}')
        self.assertEqual(req.full_url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(req.get_header("X-api-key"), "k-test")
        self.assertEqual(req.get_header("Anthropic-version"), "2023-06-01")
        sent = json.loads(req.data)
        self.assertEqual((sent["model"], sent["system"]), ("m-1", "sys"))

    def test_missing_key_explains(self):
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(SystemExit) as cm:
            ai.call_claude("s", [], "m")
        self.assertIn("ANTHROPIC_API_KEY", str(cm.exception))


class EndToEndTests(unittest.TestCase):
    def test_analyze_then_apply_on_real_audio(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            wav = d / "t.wav"
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=440:d=7",
                 "-f", "lavfi", "-i", "anullsrc=d=2", "-f", "lavfi", "-i", "sine=f=660:d=6",
                 "-filter_complex", "[0][1][2]concat=n=3:v=0:a=1", str(wav)], check=True)
            save_words(words_file(d, "t"), WORDS)  # evita depender de Whisper
            reply = ('{"decisions": [{"start": 2, "end": 3, "kind": "repeat", "reason": "toma repetida"},'
                     '{"start": 6, "end": 6, "kind": "filler", "reason": "muletilla"}]}')
            cuts, report, n = analyze(str(wav), d, "t", "small", None, None, 0.5, caller=lambda *_: reply)
            self.assertEqual(n, 2)
            self.assertIn("toma repetida", report.read_text(encoding="utf-8"))

            # la persona descarta el segundo corte
            data = json.loads(cuts.read_text(encoding="utf-8"))
            data["decisions"][1]["apply"] = False
            cuts.write_text(json.dumps(data), encoding="utf-8")

            self.assertEqual(main([str(wav), "--apply-cuts", str(cuts)]), 0)
            segs = json.loads((d / "t.segments.json").read_text())
            gaps = [(a["end"], b["start"]) for a, b in zip(segs, segs[1:])]
            # corte de p2-p3 (3.0-4.8) está; el de p6 (7.0-7.8) se conservó
            self.assertTrue(any(abs(g0 - 3.0) < 0.01 and abs(g1 - 4.8) < 0.01 for g0, g1 in gaps), gaps)
            self.assertFalse(any(abs(g0 - 7.0) < 0.2 and g1 < 8.0 for g0, g1 in gaps), gaps)
            self.assertTrue((d / "t.srt").is_file())

    def test_apply_without_words_file_explains(self):
        with tempfile.TemporaryDirectory() as d:
            wav = Path(d) / "t.wav"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                            "sine=f=440:d=2", str(wav)], check=True)
            with self.assertRaises(SystemExit) as cm:
                main([str(wav), "--apply-cuts", "x.json"])
            self.assertIn("--analyze", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
