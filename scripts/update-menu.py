import json, re, sys
from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from PIL import Image, ImageEnhance, ImageFilter
import pytesseract

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "menu.json"
SOURCE = "https://khucoop.com/35"
UA = {"User-Agent": "Mozilla/5.0 KHU-meals-bot/1.0"}

def fetch(url):
    return urlopen(Request(url, headers=UA), timeout=30).read()

def latest_image_url():
    html = fetch(SOURCE).decode("utf-8", "ignore")
    urls = re.findall(r'https://cdn\.imweb\.me/thumbnail/[^"\'<> ]+\.png', html)
    urls = list(dict.fromkeys(u.replace("&amp;", "&") for u in urls))
    if not urls:
        raise RuntimeError("공식 학생회관 식단 이미지를 찾지 못했습니다")
    # 페이지 35에는 여러 캠퍼스/식당 이미지가 함께 들어 있다. 세로형 학생회관 표를 고른다.
    dated = sorted(urls, key=lambda u: re.search(r'/thumbnail/(\d{8})/', u).group(1), reverse=True)
    candidates = []
    for url in dated[:8]:
        try:
            image = Image.open(BytesIO(fetch(url)))
            candidates.append((image.height / image.width, image.width * image.height, url))
        except Exception:
            pass
    portrait = [x for x in candidates if x[0] > 1.2]
    if not portrait:
        raise RuntimeError("학생회관 세로형 식단 이미지를 찾지 못했습니다")
    return max(portrait, key=lambda x: (re.search(r'/thumbnail/(\d{8})/', x[2]).group(1), x[1]))[2]

def clean_text(img):
    scale = 2
    img = img.resize((img.width * scale, img.height * scale))
    img = ImageEnhance.Contrast(img.convert("L")).enhance(1.8)
    img = img.filter(ImageFilter.SHARPEN)
    return pytesseract.image_to_string(img, lang="kor+eng", config="--psm 6")

def lines(text):
    bad = ("kcal", "국내산", "외국산", "호주산", "브라질산", "원산지", "알레르기")
    out = []
    for raw in text.splitlines():
        s = re.sub(r"\s+", " ", raw).strip(" -|_.,")
        if len(s) < 2 or any(x in s for x in bad):
            continue
        out.append(s)
    return out

def price_from(s, default):
    nums = [int(x) for x in re.findall(r"(?<!\d)([4-9]\d{2,3})(?:원)?", s)]
    return nums[0] if nums else default

def parse_card(text, period, kind, default):
    ls = lines(text)
    if not ls:
        return None
    price = 1000 if period == "breakfast" else price_from(" ".join(ls), default)
    filtered = [re.sub(r"\s*[4-9]\d{2,3}원?\s*", "", x).strip() for x in ls]
    filtered = [x for x in filtered if x and not re.fullmatch(r"[\d원 ]+", x)]
    if not filtered:
        return None
    return {"period": period, "kind": kind, "name": filtered[0], "price": price,
            **({"detail": filtered[1:6]} if len(filtered) > 1 else {})}

def main():
    url = latest_image_url()
    img = Image.open(BytesIO(fetch(url))).convert("RGB")
    w, h = img.size
    # 학생회관 양식: 좌측 레이블 16%, 날짜 열 5개. 각 행 비율은 주간표에서 고정된다.
    xs = [int(w * (0.16 + i * 0.168)) for i in range(6)]
    header = clean_text(img.crop((int(w*.15), int(h*.015), w, int(h*.085))))
    normalized_header = header.replace("O", "0").replace("o", "0")
    compact_header = re.sub(r"\s+", "", normalized_header)
    dates = re.findall(r"(\d{1,2})월(\d{1,2})일", compact_header)
    if len(dates) < 5:
        dates = re.findall(r"(\d{1,2})[./-](\d{1,2})", compact_header)
    # OCR이 일부 날짜를 놓치면 첫 날짜부터 평일 5일을 복원한다.
    if not dates:
        raise RuntimeError(f"날짜 OCR 실패: {header[:160]!r}")
    year = datetime.now(ZoneInfo("Asia/Seoul")).year
    first = datetime(year, int(dates[0][0]), int(dates[0][1]))
    from datetime import timedelta
    iso = [(first + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(5)]
    rows = [
        ("breakfast", "조식", .285, .395, 1000),
        ("lunch", "든든 A", .405, .535, 5500),
        ("lunch", "우아 B", .535, .655, 5500),
        ("lunch", "푸짐 C", .655, .775, 5500),
        ("dinner", "든든 A", .785, .915, 5500),
        ("dinner", "스페셜 B", .915, .955, 6500),
    ]
    days = {d: [] for d in iso}
    for i, date in enumerate(iso):
        for period, kind, y1, y2, default in rows:
            text = clean_text(img.crop((xs[i]+3, int(h*y1), xs[i+1]-3, int(h*y2))))
            card = parse_card(text, period, kind, default)
            if card: days[date].append(card)
    count = sum(map(len, days.values()))
    if count < 25 or any(not days[d] for d in days):
        raise RuntimeError(f"OCR 검증 실패: {count}개 메뉴, 날짜별 {[len(v) for v in days.values()]}")
    now = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M KST")
    data = {"updatedAt": now, "checkedAt": now, "source": SOURCE, "sourceImages": [url],
            "venue": "국제캠퍼스 학생회관식당", "defaultPrice": 5500, "days": days}
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"갱신 완료: {iso[0]}~{iso[-1]}, {count}개 메뉴")

if __name__ == "__main__":
    try: main()
    except Exception as e:
        print(f"갱신 실패(기존 데이터 보존): {e}", file=sys.stderr)
        sys.exit(1)
