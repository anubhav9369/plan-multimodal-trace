"""Tests for plan_multimodal_trace.py (stdlib only)."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import plan_multimodal_trace as pmt

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLES = os.path.join(HERE, "..", "examples")


def load(name):
    return pmt.load_plan(os.path.join(EXAMPLES, "plan.json")), \
        pmt.load_trace(os.path.join(EXAMPLES, name))


class TestMultimodalTrace(unittest.TestCase):
    def test_good_trace_fully_traced(self):
        plan, events = load("trace.jsonl")
        problems = pmt.validate_trace(plan, events)
        self.assertEqual(problems, [])
        cov = pmt.coverage(plan, events)
        self.assertEqual(pmt.verdict(problems, cov), "FULLY TRACED")
        self.assertTrue(all(info["covered"] for info in cov.values()))

    def test_irreversible_step_needs_two_modalities(self):
        plan, events = load("trace.jsonl")
        # Drop the image and audio evidence for s4; only the text send remains.
        events = [e for e in events
                  if not (e["step_id"] == "s4" and e["modality"] != "text")]
        cov = pmt.coverage(plan, events)
        self.assertFalse(cov["s4"]["covered"])
        self.assertIn("needs 2", cov["s4"]["gap"])
        self.assertEqual(pmt.verdict([], cov), "GAPS")

    def test_gaps_example_names_missing_steps(self):
        plan, events = load("trace-gaps.jsonl")
        self.assertEqual(pmt.validate_trace(plan, events), [])
        cov = pmt.coverage(plan, events)
        self.assertEqual(pmt.verdict([], cov), "GAPS")
        self.assertEqual(cov["s3"]["gap"], "no evidence in any modality")
        self.assertFalse(cov["s4"]["covered"])

    def test_invalid_example_lists_every_problem(self):
        plan, events = load("trace-invalid.jsonl")
        problems = pmt.validate_trace(plan, events)
        self.assertEqual(len(problems), 4)
        joined = " ".join(problems)
        self.assertIn("unknown step_id 's9'", joined)
        self.assertIn("unknown modality 'hologram'", joined)
        self.assertIn("before the previous event", joined)
        self.assertIn("bad timestamp 'not-a-date'", joined)
        self.assertEqual(pmt.verdict(problems, pmt.coverage(plan, events)),
                         "INVALID")

    def test_timeline_is_chronological(self):
        plan, events = load("trace.jsonl")
        shuffled = list(reversed(events))
        timeline = pmt.build_timeline(shuffled)
        stamps = [e["ts"] for e in timeline]
        self.assertEqual(stamps, sorted(stamps))
        self.assertEqual([e["step_id"] for e in timeline],
                         ["s1", "s1", "s2", "s2", "s3", "s3", "s4", "s4", "s4"])

    def test_missing_ref_flagged_only_with_check_refs(self):
        plan, events = load("trace.jsonl")
        with tempfile.TemporaryDirectory() as tmp:
            # No ref files exist under tmp, so --check-refs must flag them.
            problems = pmt.validate_trace(plan, events, tmp, check_refs=True)
            self.assertTrue(any("referenced file missing" in p for p in problems))
            # Without the flag, the same trace is clean.
            self.assertEqual(pmt.validate_trace(plan, events), [])

    def test_ref_check_passes_when_files_exist(self):
        plan, events = load("trace.jsonl")
        with tempfile.TemporaryDirectory() as tmp:
            for event in events:
                path = os.path.join(tmp, event["ref"])
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    f.write("evidence")
            self.assertEqual(
                pmt.validate_trace(plan, events, tmp, check_refs=True), [])

    def test_json_report_shape(self):
        plan, events = load("trace.jsonl")
        rep = pmt.report(plan, events, [], pmt.coverage(plan, events))
        self.assertEqual(rep["verdict"], "FULLY TRACED")
        self.assertEqual(rep["rules_version"], "1.0.0")
        self.assertEqual(rep["coverage"]["s4"]["modalities"],
                         ["audio", "image", "text"])
        self.assertEqual(len(rep["timeline"]), 9)

    def test_markdown_report_names_steps_and_modalities(self):
        plan, events = load("trace.jsonl")
        text = pmt.render_markdown(
            pmt.report(plan, events, [], pmt.coverage(plan, events)))
        self.assertIn("## Verdict: FULLY TRACED", text)
        self.assertIn("| s4 | no | audio, image, text | 3 | yes |", text)
        self.assertIn("Spoken review", text)

    def test_uncaptioned_event_marked_in_timeline(self):
        plan, events = load("trace.jsonl")
        del events[0]["note"]
        text = pmt.render_markdown(
            pmt.report(plan, events, [], pmt.coverage(plan, events)))
        self.assertIn("— (uncaptioned)", text)

    def test_cli_exit_codes(self):
        good = os.path.join(EXAMPLES, "trace.jsonl")
        gaps = os.path.join(EXAMPLES, "trace-gaps.jsonl")
        bad = os.path.join(EXAMPLES, "trace-invalid.jsonl")
        plan_path = os.path.join(EXAMPLES, "plan.json")
        self.assertEqual(pmt.main([plan_path, good, "--json"]), 0)
        self.assertEqual(pmt.main([plan_path, gaps, "--json"]), 1)
        self.assertEqual(pmt.main([plan_path, bad, "--json"]), 2)
        self.assertEqual(pmt.main([plan_path, "/nonexistent.jsonl"]), 3)


if __name__ == "__main__":
    unittest.main()
