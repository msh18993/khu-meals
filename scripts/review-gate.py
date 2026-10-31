"""Read-only, retry-safe wake gate for the existing Hermes meal-review job.

No checkpoint is advanced here. Until verified cards reference the latest source
bytes, every scheduled check requests another semantic review. Uses stdlib only.
"""
import hashlib
from html import unescape
import json
import math
import re
import struct
from datetime import date, datetime, timedelta, timezone
from urllib.request import Request, urlopen

SOURCE = "https://khucoop.com/35"
CARDS = "https://raw.githubusercontent.com/msh18993/khu-meals/main/data/menu.json"
OFFICIAL = "https://raw.githubusercontent.com/msh18993/khu-meals/main/data/official-menu.json"
IMAGE_RE = re.compile(r"https://cdn\.imweb\.me/thumbnail/(\d{8})/[^\"'<> ]+\.png")
KST = timezone(timedelta(hours=9))


def fetch(url):
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 KHU-meals-review/1.0", "Cache-Control": "no-cache"})
    with urlopen(request, timeout=25) as response:
        return response.read()


def target_week(today):
    monday = today - timedelta(days=today.weekday())
    return monday + timedelta(days=7) if today.weekday() == 6 else monday


def upload_week(uploaded):
    # Upload date is a candidate-selection hint only. The reviewing agent must
    # validate the dates PRINTED in the image before publishing any data.
    monday = uploaded - timedelta(days=uploaded.weekday())
    return monday + timedelta(days=7) if uploaded.weekday() >= 4 else monday


def find_candidate(today, fetcher=fetch, published=None):
    page = fetcher(SOURCE).decode("utf-8", "replace")
    urls = list(dict.fromkeys(unescape(m.group(0)) for m in IMAGE_RE.finditer(page)))
    target = target_week(today)
    candidates = []
    upcoming = []
    listing = {}
    for url in urls:
        stamp = url.split("/thumbnail/", 1)[1][:8]
        uploaded = datetime.strptime(stamp, "%Y%m%d").date()
        if not 0 <= (today - uploaded).days <= 14:
            continue
        if upload_week(uploaded) == target + timedelta(days=7):
            upcoming.append((stamp, url))
        if upload_week(uploaded) != target:
            continue
        raw = fetcher(url)
        if len(raw) < 24 or raw[:8] != b"\x89PNG\r\n\x1a\n" or raw[12:16] != b"IHDR":
            continue
        width, height = struct.unpack(">II", raw[16:24])
        if width >= 1200 and height / width >= 1.2:
            candidates.append((stamp, width * height, url, raw))
    if (not candidates and upcoming and isinstance(published, dict)
            and target == today - timedelta(days=today.weekday())
            and published.get("weekStart") == target.isoformat()
            and isinstance(published.get("sourceImage"), str)
            and IMAGE_RE.fullmatch(published["sourceImage"])):
        # The source normally removes this week's link when next week is posted.
        # Re-read the already-reviewed source, rather than trusting stale metadata
        # or adopting next week's unreviewed image early. decide_review still
        # requires all dates and both published source hashes to match these bytes.
        for _, next_url in sorted(upcoming, reverse=True):
            next_raw = fetcher(next_url)
            if len(next_raw) < 24 or next_raw[:8] != b"\x89PNG\r\n\x1a\n" or next_raw[12:16] != b"IHDR":
                continue
            width, height = struct.unpack(">II", next_raw[16:24])
            if width < 1200 or height / width < 1.2:
                continue
            old_url = published["sourceImage"]
            old_raw = fetcher(old_url)
            if len(old_raw) < 24 or old_raw[:8] != b"\x89PNG\r\n\x1a\n" or old_raw[12:16] != b"IHDR":
                raise RuntimeError("Previously reviewed source is not a valid PNG")
            old_width, old_height = struct.unpack(">II", old_raw[16:24])
            if old_width < 1200 or old_height / old_width < 1.2:
                raise RuntimeError("Previously reviewed source is not a portrait menu")
            candidates.append((old_url.split("/thumbnail/", 1)[1][:8],
                               old_width * old_height, old_url, old_raw))
            listing = {"sourceListingStatus": "advanced_to_next_week", "nextSourceImage": next_url,
                       "nextWeekStart": (target + timedelta(days=7)).isoformat()}
            break
    if not candidates:
        raise RuntimeError("No relevant portrait menu image; verify the source's printed dates")
    stamp, _, url, raw = max(candidates)
    return {"source": SOURCE, "sourceImage": url, "sha256": hashlib.sha256(raw).hexdigest(),
            "imageDate": datetime.strptime(stamp, "%Y%m%d").date().isoformat(),
            "weekStart": target.isoformat(), "weekStartIsUploadHint": True, **listing}


def decide_review(cards, candidate, today, official=None):
    monday = target_week(today)
    expected = [(monday + timedelta(days=i)).isoformat() for i in range(5)]
    reasons = []
    days = cards.get("days", {})
    valid_days = isinstance(days, dict) and sorted(days) == expected
    for day in expected:
        meals = days.get(day) if isinstance(days, dict) else None
        if not isinstance(meals, list) or not meals:
            valid_days = False
            continue
        for meal in meals:
            if (
                not isinstance(meal, dict)
                or not isinstance(meal.get("name"), str)
                or not meal["name"].strip()
                or meal.get("period") not in {"breakfast", "lunch", "dinner"}
                or not isinstance(meal.get("price"), (int, float))
                or isinstance(meal.get("price"), bool)
                or not math.isfinite(meal["price"])
                or meal["price"] <= 0
            ):
                valid_days = False
    if not valid_days:
        reasons.append("week_or_days_incomplete")
    source_images = cards.get("sourceImages")
    if (
        not isinstance(source_images, list)
        or not all(isinstance(image, str) for image in source_images)
        or candidate["sourceImage"] not in source_images
    ):
        reasons.append("source_image_changed")
    if cards.get("sourceSha256") != candidate["sha256"]:
        reasons.append("source_bytes_changed_or_unverified")
    if not isinstance(official, dict) or any(
        key not in official or official[key] != candidate.get(key)
        for key in ("sourceImage", "sha256", "weekStart")
    ):
        reasons.append("official_bundle_out_of_sync")
    return {"wakeAgent": bool(reasons), "reasons": reasons, "candidate": candidate,
            "expectedDates": expected}


def main():
    try:
        today = datetime.now(KST).date()
        cards = json.loads(fetch(CARDS))
        official = json.loads(fetch(OFFICIAL))
        candidate = find_candidate(today, fetcher=fetch, published=official)
        result = decide_review(cards, candidate, today, official=official)
    except Exception as exc:
        # Wake for a failed read rather than treating an unperformed check as
        # unchanged. No published data or review receipts are modified here.
        result = {"wakeAgent": True, "reasons": ["probe_error"],
                  "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
