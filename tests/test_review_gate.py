"""Regression for the weekday replacement image missed by the weekly cron."""
import importlib.util
from datetime import date
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "review-gate.py"


class ReviewGateTests(unittest.TestCase):
    def load_gate(self):
        self.assertTrue(SCRIPT.exists(), "Missing daily semantic-review wake gate")
        spec = importlib.util.spec_from_file_location("review_gate", SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_weekday_replacement_wakes_review_even_with_complete_cards(self):
        gate = self.load_gate()
        candidate = {"sourceImage": "https://cdn.imweb.me/thumbnail/20261026/new.png",
                     "weekStart": "2026-10-26", "sha256": "new-hash"}
        cards = {"sourceImages": ["https://cdn.imweb.me/thumbnail/20261023/old.png"],
                 "sourceSha256": "old-hash",
                 "days": {f"2026-10-{d}": [{"period": "lunch", "name": "메뉴", "price": 5500}]
                          for d in range(26, 31)}}
        result = gate.decide_review(cards, candidate, date(2026, 10, 27))
        self.assertTrue(result["wakeAgent"])
        self.assertIn("source_image_changed", result["reasons"])


    def test_invalid_meal_never_silently_suppresses_review(self):
        gate = self.load_gate()
        candidate = {"sourceImage": "same.png", "sha256": "same"}
        cards = {"sourceImages": ["same.png"], "sourceSha256": "same",
                 "days": {f"2026-10-{d}": [{"name": "", "period": "lunch", "price": 5500}]
                          for d in range(26, 31)}}
        self.assertTrue(gate.decide_review(cards, candidate, date(2026, 10, 27))["wakeAgent"])


    def valid_bundle(self):
        candidate = {"sourceImage": "same.png", "sha256": "same", "weekStart": "2026-10-26"}
        cards = {"sourceImages": ["same.png"], "sourceSha256": "same",
                 "days": {f"2026-10-{d}": [{"period": "lunch", "name": "메뉴", "price": 5500}]
                          for d in range(26, 31)}}
        return cards, candidate

    def test_unchanged_verified_bundle_skips_agent(self):
        gate = self.load_gate()
        cards, candidate = self.valid_bundle()
        self.assertFalse(gate.decide_review(cards, candidate, date(2026, 10, 27), official=dict(candidate))["wakeAgent"])

    def test_same_url_new_bytes_wakes_agent(self):
        gate = self.load_gate()
        cards, candidate = self.valid_bundle()
        candidate["sha256"] = "replacement-bytes"
        result = gate.decide_review(cards, candidate, date(2026, 10, 27))
        self.assertTrue(result["wakeAgent"])
        self.assertIn("source_bytes_changed_or_unverified", result["reasons"])

    def test_failed_review_remains_pending_on_each_check(self):
        gate = self.load_gate()
        cards, candidate = self.valid_bundle()
        candidate["sourceImage"] = "replacement.png"
        first = gate.decide_review(cards, candidate, date(2026, 10, 27))
        second = gate.decide_review(cards, candidate, date(2026, 10, 27))
        self.assertEqual(first, second)
        self.assertTrue(second["wakeAgent"])

    def test_sunday_targets_next_week(self):
        gate = self.load_gate()
        self.assertEqual(gate.target_week(date(2026, 11, 1)), date(2026, 11, 2))
        self.assertEqual(gate.target_week(date(2026, 10, 31)), date(2026, 10, 26))

    def test_old_official_metadata_does_not_lose_pending_review(self):
        gate = self.load_gate()
        cards, candidate = self.valid_bundle()
        official = dict(candidate, sourceImage="old.png")
        result = gate.decide_review(cards, candidate, date(2026, 10, 27), official=official)
        self.assertTrue(result["wakeAgent"])
        self.assertIn("official_bundle_out_of_sync", result["reasons"])


    def test_candidate_ignores_landscape_and_future_week(self):
        import struct
        gate = self.load_gate()
        urls = ["https://cdn.imweb.me/thumbnail/20261026/current.png",
                "https://cdn.imweb.me/thumbnail/20261026/landscape.png",
                "https://cdn.imweb.me/thumbnail/20261030/future.png"]
        def png(width, height):
            return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", width, height)
        pages = {gate.SOURCE: " ".join(urls).encode(), urls[0]: png(1920, 2479),
                 urls[1]: png(1920, 1000), urls[2]: png(1920, 2479)}
        found = gate.find_candidate(date(2026, 10, 30), fetcher=pages.__getitem__)
        self.assertEqual(found["sourceImage"], urls[0])

    def test_sunday_can_find_friday_next_week_image(self):
        import struct
        gate = self.load_gate()
        url = "https://cdn.imweb.me/thumbnail/20261030/future.png"
        png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", 1920, 2479)
        pages = {gate.SOURCE: url.encode(), url: png}
        found = gate.find_candidate(date(2026, 11, 1), fetcher=pages.__getitem__)
        self.assertEqual(found["weekStart"], "2026-11-02")

    def test_failed_probe_wakes_agent_instead_of_silent_success(self):
        import contextlib
        import io
        import json
        from unittest.mock import patch
        gate = self.load_gate()
        output = io.StringIO()
        with patch.object(gate, "find_candidate", side_effect=TimeoutError("fixture timeout")):
            with contextlib.redirect_stdout(output):
                gate.main()
        result = json.loads(output.getvalue())
        self.assertTrue(result["wakeAgent"])
        self.assertEqual(result["reasons"], ["probe_error"])


    def test_null_official_bundle_wakes_review(self):
        gate = self.load_gate()
        cards, candidate = self.valid_bundle()
        result = gate.decide_review(cards, candidate, date(2026, 10, 27), official=None)
        self.assertTrue(result["wakeAgent"])
        self.assertIn("official_bundle_out_of_sync", result["reasons"])

    def test_string_source_images_cannot_pass_substring_membership(self):
        gate = self.load_gate()
        cards, candidate = self.valid_bundle()
        cards["sourceImages"] = "not-an-array:same.png:suffix"
        result = gate.decide_review(cards, candidate, date(2026, 10, 27), official=dict(candidate))
        self.assertTrue(result["wakeAgent"])
        self.assertIn("source_image_changed", result["reasons"])

    def test_nonfinite_price_wakes_review(self):
        gate = self.load_gate()
        for price in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(price=price):
                cards, candidate = self.valid_bundle()
                cards["days"]["2026-10-27"][0]["price"] = price
                result = gate.decide_review(cards, candidate, date(2026, 10, 27), official=dict(candidate))
                self.assertTrue(result["wakeAgent"])
                self.assertIn("week_or_days_incomplete", result["reasons"])

    def test_main_null_official_response_cannot_skip_review(self):
        import contextlib
        import io
        import json
        from unittest.mock import patch
        gate = self.load_gate()
        cards, candidate = self.valid_bundle()
        output = io.StringIO()
        payloads = {gate.CARDS: json.dumps(cards).encode(), gate.OFFICIAL: b"null"}
        class FrozenDateTime:
            @classmethod
            def now(cls, tz):
                from datetime import datetime
                return datetime(2026, 10, 27, 12, tzinfo=tz)
        with patch.object(gate, "find_candidate", return_value=candidate), patch.object(gate, "fetch", side_effect=payloads.__getitem__), patch.object(gate, "datetime", FrozenDateTime):
            with contextlib.redirect_stdout(output):
                gate.main()
        self.assertTrue(json.loads(output.getvalue())["wakeAgent"])


if __name__ == "__main__":
    unittest.main()
