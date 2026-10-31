"""Week rollover is normal only with a freshly verified published bundle."""
import contextlib
from datetime import date, datetime
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "review-gate.py"


class WeekRolloverTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("rollover_gate", SCRIPT)
        assert spec is not None and spec.loader is not None
        self.gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.gate)
        self.old_url = "https://cdn.imweb.me/thumbnail/20261026/reviewed.png"
        self.next_url = "https://cdn.imweb.me/thumbnail/20261030/upcoming.png"
        header = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", 1920, 2479)
        self.old_raw = header + b"fixture-reviewed-image"
        self.next_raw = header + b"fixture-next-week-image"
        self.official = {"sourceImage": self.old_url, "weekStart": "2026-10-26",
                         "sha256": hashlib.sha256(self.old_raw).hexdigest()}
        self.cards = {"sourceImages": [self.old_url], "sourceSha256": self.official["sha256"],
                      "days": {f"2026-10-{d}": [{"period": "lunch", "name": "검증 메뉴", "price": 5500}]
                               for d in range(26, 31)}}

    def run_probe(self, when=date(2026, 10, 31), *, page=None, old_raw=None):
        gate = self.gate
        pages = {gate.SOURCE: self.next_url.encode() if page is None else page,
                 gate.CARDS: json.dumps(self.cards).encode(),
                 gate.OFFICIAL: json.dumps(self.official).encode(),
                 self.next_url: self.next_raw,
                 self.old_url: self.old_raw if old_raw is None else old_raw}
        def fetch_fixture(url):
            value = pages[url]
            if isinstance(value, Exception):
                raise value
            return value
        original = gate.find_candidate
        def candidate_fixture(*args, **kwargs):
            kwargs["fetcher"] = fetch_fixture
            return original(*args, **kwargs)
        class FrozenDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(when.year, when.month, when.day, 12, tzinfo=tz)
        output = io.StringIO()
        with patch.object(gate, "fetch", side_effect=fetch_fixture), patch.object(gate, "find_candidate", side_effect=candidate_fixture), patch.object(gate, "datetime", FrozenDateTime):
            with contextlib.redirect_stdout(output):
                gate.main()
        return json.loads(output.getvalue())

    def test_saturday_source_rollover_is_not_a_failure_or_model_wakeup(self):
        result = self.run_probe()
        self.assertFalse(result["wakeAgent"], result)
        self.assertEqual(result["candidate"]["sourceListingStatus"], "advanced_to_next_week")
        self.assertEqual(result["candidate"]["sourceImage"], self.old_url)
        self.assertEqual(result["candidate"]["nextSourceImage"], self.next_url)


    def test_friday_rollover_keeps_current_week_without_early_adoption(self):
        result = self.run_probe(date(2026, 10, 30))
        self.assertFalse(result["wakeAgent"], result)
        self.assertEqual(result["candidate"]["weekStart"], "2026-10-26")

    def test_sunday_still_wakes_to_review_next_week(self):
        result = self.run_probe(date(2026, 11, 1))
        self.assertTrue(result["wakeAgent"], result)
        self.assertNotIn("error", result)
        self.assertEqual(result["candidate"]["sourceImage"], self.next_url)
        self.assertEqual(result["candidate"]["weekStart"], "2026-11-02")
        self.assertNotIn("sourceListingStatus", result["candidate"])

    def test_changed_archived_source_bytes_still_wake_review(self):
        result = self.run_probe(old_raw=self.old_raw + b"changed")
        self.assertTrue(result["wakeAgent"], result)
        self.assertIn("source_bytes_changed_or_unverified", result["reasons"])

    def test_archived_source_download_failure_is_not_silently_ignored(self):
        result = self.run_probe(old_raw=TimeoutError("fixture source timeout"))
        self.assertTrue(result["wakeAgent"], result)
        self.assertEqual(result["reasons"], ["probe_error"])

    def test_missing_current_cards_do_not_become_quiet_rollover(self):
        del self.cards["days"]["2026-10-30"]
        result = self.run_probe()
        self.assertTrue(result["wakeAgent"], result)
        self.assertIn("week_or_days_incomplete", result["reasons"])

    def test_missing_page_images_still_report_a_real_probe_failure(self):
        result = self.run_probe(page=b"<html>No menu images</html>")
        self.assertTrue(result["wakeAgent"], result)
        self.assertEqual(result["reasons"], ["probe_error"])

    def test_invalid_archived_png_is_a_real_failure(self):
        result = self.run_probe(old_raw=b"invalid-image")
        self.assertTrue(result["wakeAgent"], result)
        self.assertEqual(result["reasons"], ["probe_error"])

    def test_current_link_has_priority_over_future_link(self):
        result = self.run_probe(page=(self.old_url + " " + self.next_url).encode())
        self.assertFalse(result["wakeAgent"], result)
        self.assertEqual(result["candidate"]["sourceImage"], self.old_url)
        self.assertNotIn("sourceListingStatus", result["candidate"])


if __name__ == "__main__":
    unittest.main()
