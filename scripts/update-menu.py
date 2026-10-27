"""Publish the official weekly menu image without unverified OCR transcription."""

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from html import unescape
from io import BytesIO
from pathlib import Path
from urllib.request import Request, urlopen

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SOURCE = "https://khucoop.com/35"
META = DATA / "official-menu.json"
FULL = DATA / "official-menu.png"
DAY_FILES = [DATA / f"official-day-{day}.png" for day in range(5)]
HEADERS = {"User-Agent": "Mozilla/5.0 KHU-meals-bot/1.0"}
IMAGE_RE = re.compile(r"https://cdn\.imweb\.me/thumbnail/(\d{8})/[^\"'<> ]+\.png")
KST = timezone(timedelta(hours=9))


def fetch(url):
    return urlopen(Request(url, headers=HEADERS), timeout=30).read()


def find_official_image():
    page = fetch(SOURCE).decode("utf-8", "ignore")
    candidates = list(dict.fromkeys(unescape(m.group(0)) for m in IMAGE_RE.finditer(page)))
    if not candidates:
        raise RuntimeError("공식 페이지에서 식단 이미지 주소를 찾지 못했습니다")

    portraits = []
    for url in sorted(candidates, key=lambda item: item.split("/thumbnail/")[1][:8], reverse=True):
        try:
            raw = fetch(url)
            image = Image.open(BytesIO(raw))
            image.verify()
            image = Image.open(BytesIO(raw))
            width, height = image.size
            if image.format == "PNG" and width >= 1200 and height / width >= 1.2:
                portraits.append((url.split("/thumbnail/")[1][:8], width * height, url, raw))
        except Exception:
            continue
    if not portraits:
        raise RuntimeError("검증 가능한 학생회관 세로형 식단 이미지를 찾지 못했습니다")
    image_date, _, url, raw = max(portraits)
    uploaded = datetime.strptime(image_date, "%Y%m%d").date()
    today = datetime.now(KST).date()
    if not 0 <= (today - uploaded).days <= 14:
        raise RuntimeError(f"공식 식단 이미지의 등록일이 현재 주간과 맞지 않습니다: {uploaded}")
    return url, uploaded, raw


def crop_days(raw):
    image = Image.open(BytesIO(raw)).convert("RGB")
    width, height = image.size
    # Preserve the printed dates and all student meals; no menu text is inferred.
    top = (int(height * .038), int(height * .062))
    body_top = int(height * .205)
    sample_x = range(40, width - 40, 12)
    for y in range(int(height * .18), int(height * .25)):
        dark = sum(max(image.getpixel((x, y))) < 125 for x in sample_x)
        if dark > len(sample_x) * .65:
            body_top = y + 2
            break
    # The purple origin-of-ingredients block starts after the final dinner row.
    origin_top = int(height * .91)
    for y in range(int(height * .78), int(height * .94)):
        red, green, blue = image.getpixel((int(width * .05), y))
        if blue > red + 15 and blue > green + 15 and red > 140:
            origin_top = y
            break
    body = (body_top, origin_top)
    output = []
    for day in range(5):
        left = int(width * (.159 + day * .1625)) + 2
        right = int(width * (.159 + (day + 1) * .1625)) - 2
        header = image.crop((left, top[0], right, top[1]))
        meals = image.crop((left, body[0], right, body[1]))
        strip = Image.new("RGB", (right - left, header.height + meals.height), "white")
        strip.paste(header, (0, 0))
        strip.paste(meals, (0, header.height))
        buffer = BytesIO()
        strip.save(buffer, format="PNG", optimize=True)
        output.append(buffer.getvalue())
    return output


def current_cards_match(old, current_week, *, require_hash=False):
    """Check all five dates and source binding for the supplied week/image.

    Legacy preserved cards may omit a hash; explicit reviewed publication may not.
    """
    try:
        cards = json.loads((DATA / "menu.json").read_text(encoding="utf-8"))
        days = cards.get("days", {})
        return (
            old.get("weekStart") == current_week.isoformat()
            and isinstance(cards.get("sourceImages"), list)
            and old.get("sourceImage") in cards["sourceImages"]
            and (not require_hash or "sourceSha256" in cards)
            and ("sourceSha256" not in cards or cards["sourceSha256"] == old.get("sha256"))
            and all(isinstance(days.get((current_week + timedelta(days=day)).isoformat()), list)
                    and days[(current_week + timedelta(days=day)).isoformat()]
                    for day in range(5))
        )
    except (OSError, ValueError, AttributeError, TypeError):
        return False


def main(*, publish_reviewed=False):
    url, uploaded, raw = find_official_image()
    # Match the review gate's upload hint: Mon–Thu replacements are for this
    # week; Fri–Sun uploads normally announce next week. Review still checks
    # the dates printed in the image before --publish-reviewed is used.
    image_week = uploaded - timedelta(days=uploaded.weekday())
    if uploaded.weekday() >= 4:
        image_week += timedelta(days=7)
    today = datetime.now(KST).date()
    current_week = today - timedelta(days=today.weekday())
    if image_week > current_week and not publish_reviewed:
        print(f"다음 주 식단표 대기: {image_week} (이번 주 {current_week} 이미지 유지)")
        return
    digest = hashlib.sha256(raw).hexdigest()
    metadata = {
        "source": SOURCE,
        "sourceImage": url,
        "imageDate": uploaded.isoformat(),
        "weekStart": image_week.isoformat(),
        "updatedAt": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
        "sha256": digest,
        "layoutVersion": 4,
    }
    review_week_allowed = image_week == current_week or (
        today.weekday() == 6 and image_week == current_week + timedelta(days=7))
    if publish_reviewed and (not review_week_allowed or not current_cards_match(
            metadata, image_week, require_hash=True)):
        raise RuntimeError("검토된 식단의 주간·출처 URL·SHA-256·월~금 메뉴가 공식 이미지와 일치하지 않습니다")
    if META.exists():
        old = json.loads(META.read_text(encoding="utf-8"))
        if (not publish_reviewed and image_week == current_week and current_cards_match(old, current_week)
                and (old.get("sourceImage") != url or old.get("sha256") != digest)):
            metadata["status"] = "review_required"
            pending_path = DATA / "pending-menu.json"
            try:
                pending = json.loads(pending_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pending = {}
            if (isinstance(pending, dict)
                    and {key: value for key, value in pending.items() if key != "updatedAt"}
                    == {key: value for key, value in metadata.items() if key != "updatedAt"}):
                print(f"공식 식단 변경 검토 대기 유지: {uploaded}")
                return
            pending_path.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"공식 식단 변경 검토 대기: {uploaded} (기존 검증 식단 유지)")
            return
        if old.get("sha256") == digest and old.get("sourceImage") == url and old.get("layoutVersion") == 4 and FULL.exists() and all(p.exists() for p in DAY_FILES):
            (DATA / "pending-menu.json").unlink(missing_ok=True)
            print(f"변경 없음: {uploaded} 공식 식단 이미지")
            return

    days = crop_days(raw)
    DATA.mkdir(exist_ok=True)
    FULL.write_bytes(raw)
    for path, content in zip(DAY_FILES, days, strict=True):
        path.write_bytes(content)
    metadata.update({
        "fullImage": "./data/official-menu.png",
        "dayImages": [f"./data/{path.name}" for path in DAY_FILES],
    })
    META.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (DATA / "pending-menu.json").unlink(missing_ok=True)
    print(f"공식 식단 이미지 갱신: {uploaded}, {len(raw)} bytes, 5일 이미지")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish-reviewed", action="store_true",
                        help="Publish only with matching reviewed URL, SHA-256 and all five weekdays")
    args = parser.parse_args()
    main(publish_reviewed=args.publish_reviewed)
