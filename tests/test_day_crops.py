"""Day-image coverage across the reviewed short and tall table layouts."""

import importlib.util
from io import BytesIO
from pathlib import Path
import unittest

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("crop_updater", ROOT / "scripts/update-menu.py")
assert SPEC is not None and SPEC.loader is not None
updater = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(updater)


class DayCropTests(unittest.TestCase):
    def test_day_strips_preserve_dates_and_every_student_row_without_faculty_or_origin(self):
        # Border and weekday coordinates vary with page margins and layout.
        for height, student_top, student_bottom, bounds in [
            (2782, 467, 2350, (49, 317, 626, 936, 1245, 1554, 1863)),
            (2479, 482, 2046, (12, 317, 629, 941, 1253, 1565, 1877)),
            (2865, 461, 2453, (0, 282, 610, 937, 1264, 1592, 1919)),
        ]:
            with self.subTest(height=height):
                image = Image.new("RGB", (1920, height), "white")
                draw = ImageDraw.Draw(image)
                for top, bottom in [(100, 101), (145, 146), (student_top - 2, student_top - 1),
                                    (885, 885), (1543, 1543), (1888, 1888),
                                    (student_bottom, student_bottom)]:
                    draw.rectangle((40, top, 1880, bottom), fill="black")
                # The weekday rules can be thin, gray and dotted.
                for x in bounds:
                    for y in range(100, student_bottom):
                        if y % 3 != 0:
                            image.putpixel((x, y), (200, 200, 200))
                # Mark printed dates, faculty meals, first/last student rows and origin notes.
                for day in range(5):
                    left, right = bounds[day + 1] + 1, bounds[day + 2]
                    for top, bottom, color in [(110, 135, "blue"), (160, 200, "magenta"),
                                               (student_top + 3, student_top + 30, "green"),
                                               (student_bottom - 30, student_bottom - 3, "orange"),
                                               (student_bottom + 10, student_bottom + 30, "red")]:
                        draw.rectangle((left, top, right - 1, bottom), fill=color)
                # An antialiased rule pixel must not be mistaken for the origin block.
                image.putpixel((96, int(height * .785)), (159, 169, 194))
                buffer = BytesIO()
                image.save(buffer, format="PNG")
                strips = updater.crop_days(buffer.getvalue())
                self.assertEqual(len(strips), 5)
                for day, raw in enumerate(strips):
                    left, right = bounds[day + 1] + 1, bounds[day + 2]
                    expected = Image.new("RGB", (right - left, 43 + student_bottom - student_top), "white")
                    expected.paste(image.crop((left, 102, right, 145)), (0, 0))
                    expected.paste(image.crop((left, student_top, right, student_bottom)), (0, 43))
                    actual = Image.open(BytesIO(raw)).convert("RGB")
                    self.assertEqual(actual.size, expected.size, "full breakfast through special dinner must survive")
                    self.assertIsNone(ImageChops.difference(actual, expected).getbbox())

    def test_missing_weekday_boundary_fails_closed(self):
        image = Image.new("RGB", (400, 600), "white")
        draw = ImageDraw.Draw(image)
        for y in (24, 35, 120, 500):
            draw.line((0, y, 399, y), fill="black")
        for x in (0, 60, 128, 196, 332, 399):
            draw.line((x, 24, x, 500), fill="black")
        buf = BytesIO()
        image.save(buf, format="PNG")
        with self.assertRaisesRegex(RuntimeError, "요일 열 경계선"):
            updater.crop_days(buf.getvalue())


if __name__ == "__main__":
    unittest.main()
