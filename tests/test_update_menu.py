"""Regression tests for automatic refresh; no network or repository data writes."""

import ast
import contextlib
import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("update_menu", ROOT / "scripts/update-menu.py")
assert SPEC is not None and SPEC.loader is not None
updater = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(updater)


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 27, 12, tzinfo=tz)


def menu_image(meal):
    image = Image.new("RGB", (400, 600), "white")
    ImageDraw.Draw(image).text((100, 200), meal, fill="black")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class UpdateMenuTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name) / "data"
        self.data.mkdir()
        self.meta_path = self.data / "official-menu.json"
        self.cards_path = self.data / "menu.json"
        self.pending_path = self.data / "pending-menu.json"
        self.full = self.data / "official-menu.png"
        self.day_files = [self.data / f"official-day-{day}.png" for day in range(5)]
        self.old_raw = menu_image("Lunch: rice and chicken")
        self.new_raw = menu_image("Lunch: noodles and beef")
        self.old_url = "https://cdn.imweb.me/thumbnail/20261023/old.png"
        self.new_url = "https://cdn.imweb.me/thumbnail/20261026/replacement.png"
        self.old = {
            "source": updater.SOURCE,
            "sourceImage": self.old_url,
            "imageDate": "2026-10-23",
            "weekStart": "2026-10-26",
            "updatedAt": "2026-10-26 09:00 KST",
            "sha256": hashlib.sha256(self.old_raw).hexdigest(),
            "layoutVersion": 4,
            "fullImage": "./data/official-menu.png",
            "dayImages": [f"./data/{path.name}" for path in self.day_files],
        }
        self.cards = {
            "sourceImages": [self.old_url],
            "days": {
                (date(2026, 10, 26) + timedelta(days=day)).isoformat(): [
                    {"period": "lunch", "name": "rice and chicken"}
                ] for day in range(5)
            },
        }
        self.write_json(self.meta_path, self.old)
        self.write_json(self.cards_path, self.cards)
        self.full.write_bytes(self.old_raw)
        for path, raw in zip(self.day_files, updater.crop_days(self.old_raw), strict=True):
            path.write_bytes(raw)
        self.paths = [self.meta_path, self.cards_path, self.full, *self.day_files]
        self.original = {path: path.read_bytes() for path in self.paths}
        self.addCleanup(patch.stopall)
        patch.multiple(updater, DATA=self.data, META=self.meta_path, FULL=self.full,
                       DAY_FILES=self.day_files, datetime=FrozenDateTime).start()

    @staticmethod
    def write_json(path, data):
        path.write_text(json.dumps(data), encoding="utf-8")

    def run_update(self, url=None, raw=None, uploaded=date(2026, 10, 26), cli=False, **kwargs):
        with patch.object(updater, "find_official_image", return_value=(
            url or self.new_url, uploaded, raw if raw is not None else self.new_raw
        )), contextlib.redirect_stdout(io.StringIO()) as output:
            if cli:
                entry = ast.parse((ROOT / "scripts/update-menu.py").read_text(encoding="utf-8")).body[-1]
                command = ["update-menu.py"] + (["--publish-reviewed"] if kwargs.get("publish_reviewed") else [])
                with patch.object(sys, "argv", command), patch.dict(updater.__dict__, {"__name__": "__main__"}):
                    exec(compile(ast.Module(body=[entry], type_ignores=[]), "update-menu.py", "exec"), updater.__dict__)
            else:
                updater.main(**kwargs)
        return output.getvalue()

    def assert_bundle_unchanged(self):
        for path, raw in self.original.items():
            with self.subTest(file=path.name):
                self.assertEqual(path.read_bytes(), raw)

    def test_changed_meal_image_is_staged_without_invalidating_verified_cards(self):
        self.run_update()
        self.assert_bundle_unchanged()
        pending = json.loads(self.pending_path.read_text(encoding="utf-8"))
        self.assertEqual(pending, {
            "source": updater.SOURCE,
            "sourceImage": self.new_url,
            "imageDate": "2026-10-26",
            "weekStart": "2026-10-26",
            "updatedAt": "2026-10-27 12:00 KST",
            "sha256": hashlib.sha256(self.new_raw).hexdigest(),
            "layoutVersion": 4,
            "status": "review_required",
        })
        self.assertEqual({path.name for path in self.data.iterdir()},
                         {path.name for path in self.paths} | {"pending-menu.json"})

    def test_midweek_replacement_upload_is_staged_for_current_week(self):
        self.run_update(uploaded=date(2026, 10, 27))
        self.assertTrue(self.pending_path.exists(), "Tuesday replacement belongs to the current week")
        self.assert_bundle_unchanged()
        pending = json.loads(self.pending_path.read_text(encoding="utf-8"))
        self.assertEqual(pending["weekStart"], "2026-10-26")
        self.assertEqual(pending["imageDate"], "2026-10-27")

    def test_staging_rerun_is_idempotent_even_after_clock_changes(self):
        self.run_update()
        pending = self.pending_path.read_bytes()
        with patch.object(FrozenDateTime, "now", return_value=datetime(2026, 10, 27, 18)):
            self.run_update()
        self.assertEqual(self.pending_path.read_bytes(), pending)
        self.assert_bundle_unchanged()

    def test_pending_clears_after_reviewed_bundle_publication_and_stays_cleared(self):
        self.run_update()
        self.old.update(sourceImage=self.new_url, sha256=hashlib.sha256(self.new_raw).hexdigest())
        self.cards.update(sourceImages=[self.new_url], sourceSha256=self.old["sha256"])
        self.write_json(self.meta_path, self.old)
        self.write_json(self.cards_path, self.cards)
        self.full.write_bytes(self.new_raw)
        for path, raw in zip(self.day_files, updater.crop_days(self.new_raw), strict=True):
            path.write_bytes(raw)
        published = {path: path.read_bytes() for path in self.paths}
        self.run_update()
        self.assertFalse(self.pending_path.exists())
        self.run_update()
        self.assertFalse(self.pending_path.exists())
        self.assertEqual({path: path.read_bytes() for path in self.paths}, published)

    def test_publish_reviewed_current_bundle_clears_pending_and_is_idempotent(self):
        self.run_update()
        self.cards.update(sourceImages=[self.new_url], sourceSha256=hashlib.sha256(self.new_raw).hexdigest())
        self.write_json(self.cards_path, self.cards)
        cards_before = self.cards_path.read_bytes()
        self.run_update(cli=True, publish_reviewed=True)
        self.assertFalse(self.pending_path.exists())
        self.assertEqual(self.full.read_bytes(), self.new_raw)
        self.assertEqual([path.read_bytes() for path in self.day_files], updater.crop_days(self.new_raw))
        meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
        self.assertEqual(meta["sourceImage"], self.new_url)
        self.assertEqual(meta["sha256"], self.cards["sourceSha256"])
        self.assertEqual(meta["weekStart"], "2026-10-26")
        self.assertNotIn("status", meta)
        published = {path: path.read_bytes() for path in self.paths}
        self.run_update(publish_reviewed=True)
        self.assertEqual({path: path.read_bytes() for path in self.paths}, published)
        self.assertEqual(self.cards_path.read_bytes(), cards_before)

    def test_same_url_changed_digest_still_requires_review(self):
        self.cards["sourceSha256"] = self.old["sha256"]
        self.write_json(self.cards_path, self.cards)
        self.original[self.cards_path] = self.cards_path.read_bytes()
        self.run_update(url=self.old_url)
        self.assert_bundle_unchanged()
        pending = json.loads(self.pending_path.read_text(encoding="utf-8"))
        self.assertEqual(pending["sourceImage"], self.old_url)
        self.assertEqual(pending["sha256"], hashlib.sha256(self.new_raw).hexdigest())
        self.assertNotEqual(pending["sha256"], self.old["sha256"])

    def test_identical_verified_url_and_digest_needs_no_pending(self):
        self.run_update(url=self.old_url, raw=self.old_raw, uploaded=date(2026, 10, 23))
        self.assert_bundle_unchanged()
        self.assertFalse(self.pending_path.exists())

    def test_changed_url_requires_review_even_if_image_bytes_are_identical(self):
        self.run_update(raw=self.old_raw)
        self.assert_bundle_unchanged()
        pending = json.loads(self.pending_path.read_text(encoding="utf-8"))
        self.assertEqual(pending["sourceImage"], self.new_url)
        self.assertEqual(pending["sha256"], self.old["sha256"])

    def test_publish_reviewed_accepts_same_url_only_with_exact_new_digest(self):
        self.run_update(url=self.old_url)
        self.cards["sourceSha256"] = hashlib.sha256(self.new_raw).hexdigest()
        self.write_json(self.cards_path, self.cards)
        self.run_update(url=self.old_url, cli=True, publish_reviewed=True)
        meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
        self.assertEqual(meta["sourceImage"], self.old_url)
        self.assertEqual(meta["sha256"], self.cards["sourceSha256"])
        self.assertEqual(self.full.read_bytes(), self.new_raw)
        self.assertFalse(self.pending_path.exists())

    def test_incomplete_unbound_or_stale_cards_keep_official_fallback(self):
        invalid_cards = {
            "missing": None,
            "stale_week": {"sourceImages": [self.old_url], "days": {"2026-10-19": [{}]}},
            "missing_friday": {**self.cards, "days": {key: value for key, value in self.cards["days"].items() if key != "2026-10-30"}},
            "empty_friday": {**self.cards, "days": {**self.cards["days"], "2026-10-30": []}},
            "non_list_meals": {**self.cards, "days": {**self.cards["days"], "2026-10-30": "lunch"}},
            "wrong_url": {**self.cards, "sourceImages": [self.new_url]},
            "string_urls": {**self.cards, "sourceImages": self.old_url},
            "wrong_hash": {**self.cards, "sourceSha256": "0" * 64},
            "null_hash": {**self.cards, "sourceSha256": None},
            "null_days": {**self.cards, "days": None},
            "null_cards": "null",
            "broken_json": "{broken",
        }
        for reason, cards in invalid_cards.items():
            with self.subTest(reason=reason):
                self.write_json(self.meta_path, self.old)
                self.full.write_bytes(self.old_raw)
                if cards is None:
                    self.cards_path.unlink(missing_ok=True)
                elif isinstance(cards, str):
                    self.cards_path.write_text(cards, encoding="utf-8")
                else:
                    self.write_json(self.cards_path, cards)
                before = self.cards_path.read_bytes() if self.cards_path.exists() else None
                self.run_update()
                published = json.loads(self.meta_path.read_text(encoding="utf-8"))
                self.assertEqual(published["sourceImage"], self.new_url)
                self.assertEqual(published["sha256"], hashlib.sha256(self.new_raw).hexdigest())
                self.assertEqual(self.full.read_bytes(), self.new_raw)
                self.assertFalse(self.pending_path.exists())
                self.assertEqual(self.cards_path.read_bytes() if self.cards_path.exists() else None, before)
                self.assertEqual([path.read_bytes() for path in self.day_files], updater.crop_days(self.new_raw))

    def test_stale_official_bundle_is_not_protected_by_current_cards(self):
        self.old["weekStart"] = "2026-10-19"
        self.write_json(self.meta_path, self.old)
        self.run_update()
        self.assertEqual(self.full.read_bytes(), self.new_raw)
        self.assertFalse(self.pending_path.exists())

    def test_no_existing_official_bundle_uses_image_fallback(self):
        self.meta_path.unlink()
        self.run_update()
        self.assertEqual(self.full.read_bytes(), self.new_raw)
        self.assertEqual(json.loads(self.meta_path.read_text(encoding="utf-8"))["sourceImage"], self.new_url)
        self.assertFalse(self.pending_path.exists())

    def test_ordinary_future_week_update_preserves_bundle_and_pending(self):
        self.run_update()
        pending = self.pending_path.read_bytes()
        self.run_update(uploaded=date(2026, 10, 30))
        self.assert_bundle_unchanged()
        self.assertEqual(self.pending_path.read_bytes(), pending)

    def test_cli_publish_reviewed_refuses_mismatched_cards_without_writing(self):
        before = {path: path.read_bytes() for path in self.data.iterdir()}
        with self.assertRaises(RuntimeError):
            self.run_update(cli=True, publish_reviewed=True)
        self.assertEqual({path: path.read_bytes() for path in self.data.iterdir()}, before)

    def test_publish_reviewed_rejects_mismatched_cards_without_any_mutation(self):
        self.run_update()
        valid = {**self.cards, "sourceImages": [self.new_url],
                 "sourceSha256": hashlib.sha256(self.new_raw).hexdigest()}
        invalid = {
            "url": {**valid, "sourceImages": [self.old_url]},
            "sha": {**valid, "sourceSha256": self.old["sha256"]},
            "no_sha": {key: value for key, value in valid.items() if key != "sourceSha256"},
            "missing_day": {**valid, "days": {key: value for key, value in valid["days"].items() if key != "2026-10-30"}},
            "empty_day": {**valid, "days": {**valid["days"], "2026-10-30": []}},
            "stale_week": {**valid, "days": {"2026-10-19": [{}]}},
        }
        for reason, cards in invalid.items():
            with self.subTest(reason=reason):
                self.write_json(self.cards_path, cards)
                before = {path: path.read_bytes() for path in self.data.iterdir()}
                with self.assertRaises(RuntimeError):
                    self.run_update(publish_reviewed=True)
                self.assertEqual({path: path.read_bytes() for path in self.data.iterdir()}, before)

    def test_publish_reviewed_allows_upcoming_week_only_on_sunday(self):
        self.cards.update(
            sourceImages=[self.new_url], sourceSha256=hashlib.sha256(self.new_raw).hexdigest(),
            days={(date(2026, 11, 2) + timedelta(days=day)).isoformat(): [{"period": "lunch", "name": "noodles and beef"}] for day in range(5)})
        self.write_json(self.cards_path, self.cards)
        before = {path: path.read_bytes() for path in self.data.iterdir()}
        with self.assertRaises(RuntimeError):
            self.run_update(publish_reviewed=True, uploaded=date(2026, 10, 30))
        self.assertEqual({path: path.read_bytes() for path in self.data.iterdir()}, before)
        with patch.object(FrozenDateTime, "now", return_value=datetime(2026, 11, 1, 9, tzinfo=updater.KST)):
            # Ordinary refresh still waits, even on Sunday with matching next-week cards.
            self.run_update(uploaded=date(2026, 10, 30))
            self.assertEqual({path: path.read_bytes() for path in self.data.iterdir()}, before)
            try:
                self.run_update(publish_reviewed=True, uploaded=date(2026, 10, 30))
            except RuntimeError as error:
                self.fail(f"Sunday reviewed next-week bundle must be publishable: {error}")
        self.assertEqual(self.full.read_bytes(), self.new_raw)
        self.assertEqual(json.loads(self.meta_path.read_text(encoding="utf-8"))["weekStart"], "2026-11-02")
        self.assertFalse(self.pending_path.exists())

    def test_publish_reviewed_refuses_past_or_distant_future_week_even_on_sunday(self):
        for monday, uploaded in [(date(2026, 10, 19), date(2026, 10, 19)),
                                 (date(2026, 11, 9), date(2026, 11, 6))]:
            with self.subTest(monday=monday):
                self.cards.update(
                    sourceImages=[self.new_url], sourceSha256=hashlib.sha256(self.new_raw).hexdigest(),
                    days={(monday + timedelta(days=day)).isoformat(): [{"name": "reviewed"}] for day in range(5)})
                self.write_json(self.cards_path, self.cards)
                before = {path: path.read_bytes() for path in self.data.iterdir()}
                with patch.object(FrozenDateTime, "now", return_value=datetime(2026, 11, 1, 9, tzinfo=updater.KST)):
                    with self.assertRaises(RuntimeError):
                        self.run_update(uploaded=uploaded, publish_reviewed=True)
                self.assertEqual({path: path.read_bytes() for path in self.data.iterdir()}, before)


class UpdateWorkflowTests(unittest.TestCase):
    def test_workflow_runs_regressions_before_updater_and_stages_pending_deletion(self):
        workflow = (ROOT / ".github/workflows/update-menu.yml").read_text(encoding="utf-8")
        python_tests = "python -m unittest discover -s tests -v"
        frontend_tests = "node --test tests/test_frontend.cjs"
        self.assertIn(python_tests, workflow)
        self.assertIn(frontend_tests, workflow)
        self.assertLess(workflow.index(python_tests), workflow.index("python scripts/update-menu.py"))
        self.assertLess(workflow.index(frontend_tests), workflow.index("python scripts/update-menu.py"))
        self.assertIn("git add -A -- data", workflow)


if __name__ == "__main__":
    unittest.main()
