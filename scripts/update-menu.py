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


def main():
    url, uploaded, raw = find_official_image()
    image_week = uploaded + timedelta(days=(-uploaded.weekday()) % 7)
    today = datetime.now(KST).date()
    current_week = today - timedelta(days=today.weekday())
    if image_week > current_week:
        print(f"다음 주 식단표 대기: {image_week} (이번 주 {current_week} 이미지 유지)")
        return
    digest = hashlib.sha256(raw).hexdigest()
    if META.exists():
        old = json.loads(META.read_text(encoding="utf-8"))
        if old.get("sha256") == digest and old.get("sourceImage") == url and old.get("layoutVersion") == 4 and FULL.exists() and all(p.exists() for p in DAY_FILES):
            print(f"변경 없음: {uploaded} 공식 식단 이미지")
            return

    days = crop_days(raw)
    DATA.mkdir(exist_ok=True)
    FULL.write_bytes(raw)
    for path, content in zip(DAY_FILES, days, strict=True):
        path.write_bytes(content)
    metadata = {
        "source": SOURCE,
        "sourceImage": url,
        "imageDate": uploaded.isoformat(),
        "weekStart": image_week.isoformat(),
        "updatedAt": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
        "sha256": digest,
        "layoutVersion": 4,
        "fullImage": "./data/official-menu.png",
        "dayImages": [f"./data/{path.name}" for path in DAY_FILES],
    }
    META.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"공식 식단 이미지 갱신: {uploaded}, {len(raw)} bytes, 5일 이미지")


if __name__ == "__main__":
    main()
