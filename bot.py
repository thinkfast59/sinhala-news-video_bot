import os
import re
import json
import random
import hashlib
from io import BytesIO
from datetime import datetime

import numpy as np
import requests
import feedparser
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from gtts import gTTS
from deep_translator import GoogleTranslator
from moviepy import VideoClip, AudioFileClip


PAGE_NAME = "ලෝක පුවත් සිංහලෙන්"
CHANNEL_NAME_SI = "ලෝක පුවත් සිංහලෙන්"

OUTPUT_DIR = "output"
ASSET_DIR = "assets"
USED_FILE = "used.json"

VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
VIDEO_SIZE = (VIDEO_WIDTH, VIDEO_HEIGHT)

VOICE_LANGUAGE = "si"
TRANSLATE_TO = "si"
MAX_SCRIPT_CHARS = 750

TELEGRAM_BOT_TOKEN = os.getenv("8467040279:AAHK4WfTDbOfjCCoCg58kZle6CKoW22mwF4")
TELEGRAM_CHAT_ID = os.getenv("8376417027")

FEEDS = [
    "https://www.bbc.com/news/world/rss.xml",
    "https://feeds.skynews.com/feeds/rss/world.xml",
    "https://www.aljazeera.com/xml/rss/all.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
    "https://feeds.npr.org/1004/rss.xml",
    "https://www.france24.com/en/rss",
    "https://www.theguardian.com/world/rss",
    "https://www.cbc.ca/cmlink/rss-world",
    "https://www.thehindu.com/news/international/feeder/default.rss",
    "https://timesofindia.indiatimes.com/rssfeeds/296589292.cms",
    "https://www.hindustantimes.com/feeds/rss/world-news/rssfeed.xml",
    "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml",
    "https://www.middleeasteye.net/rss",
    "https://feeds.bbci.co.uk/news/business/rss.xml",
    "https://feeds.bbci.co.uk/news/technology/rss.xml",
]

USER_AGENT = "Mozilla/5.0 Chrome/120.0 Safari/537.36"


def clean_text(text):
    text = BeautifulSoup(text or "", "html.parser").get_text(" ")
    return re.sub(r"\s+", " ", text).strip()


def shorten(text, max_chars):
    text = clean_text(text)
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "..."


def has_sinhala(text):
    return bool(re.search(r"[\u0D80-\u0DFF]", text or ""))


def translate_to_sinhala(text, max_chars=1200):
    text = shorten(text, max_chars)
    if not text:
        return ""

    try:
        translated = GoogleTranslator(source="auto", target=TRANSLATE_TO).translate(text)
        translated = clean_text(translated)

        if not has_sinhala(translated):
            return ""

        return translated
    except Exception as e:
        print("Translation failed:", e)
        return ""


def load_used():
    if os.path.exists(USED_FILE):
        try:
            with open(USED_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_used(used):
    with open(USED_FILE, "w", encoding="utf-8") as f:
        json.dump(used[-1000:], f, indent=2, ensure_ascii=False)


def get_font(size, bold=False):
    if bold:
        paths = [
            "/usr/share/fonts/truetype/noto/NotoSansSinhala-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSerifSinhala-Bold.ttf",
            "/usr/share/fonts/opentype/noto/NotoSansSinhala-Bold.ttf",
            "assets/NotoSansSinhala-Bold.ttf",
        ]
    else:
        paths = [
            "/usr/share/fonts/truetype/noto/NotoSansSinhala-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoSerifSinhala-Regular.ttf",
            "/usr/share/fonts/opentype/noto/NotoSansSinhala-Regular.ttf",
            "assets/NotoSansSinhala-Regular.ttf",
        ]

    for path in paths:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)

    print("WARNING: Sinhala font not found.")
    return ImageFont.load_default()


def text_size(draw, text, font):
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def wrap_text(draw, text, font, max_width):
    words = text.split()
    lines = []
    current = ""

    for word in words:
        test = current + " " + word if current else word
        w, _ = text_size(draw, test, font)

        if w <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word

    if current:
        lines.append(current)

    return lines


def fit_text_to_box(draw, text, max_width, max_height, start_size, min_size, bold=False):
    for size in range(start_size, min_size - 1, -2):
        font = get_font(size, bold)
        lines = wrap_text(draw, text, font, max_width)
        lh = int(size * 1.35)

        if len(lines) * lh <= max_height:
            return font, lines, lh

    font = get_font(min_size, bold)
    return font, wrap_text(draw, text, font, max_width), int(min_size * 1.35)


def draw_multiline(draw, lines, x, y, font, line_height, fill):
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height
    return y


def cover_resize(img, size):
    target_w, target_h = size
    img_w, img_h = img.size

    scale = max(target_w / img_w, target_h / img_h)
    new_w = int(img_w * scale)
    new_h = int(img_h * scale)

    img = img.resize((new_w, new_h), Image.LANCZOS)

    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2

    return img.crop((left, top, left + target_w, top + target_h))


def get_image_from_feed_entry(entry):
    for key in ["media_content", "media_thumbnail"]:
        media = entry.get(key, [])
        for item in media:
            if item.get("url"):
                return item.get("url")

    for link in entry.get("links", []):
        if "image" in link.get("type", ""):
            return link.get("href")

    return None


def get_image_from_article_page(article_url):
    try:
        r = requests.get(article_url, headers={"User-Agent": USER_AGENT}, timeout=15)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, "html.parser")

        for attrs in [
            {"property": "og:image"},
            {"name": "twitter:image"},
            {"property": "twitter:image"},
        ]:
            tag = soup.find("meta", attrs=attrs)
            if tag and tag.get("content"):
                return tag.get("content")

    except Exception as e:
        print("Article image error:", e)

    return None


def download_image(url, output_path):
    if not url:
        return False

    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=25)

        if r.status_code != 200:
            print("Image status:", r.status_code)
            return False

        img = Image.open(BytesIO(r.content)).convert("RGB")

        if img.width < 120 or img.height < 120:
            return False

        img.save(output_path, quality=95)
        return True

    except Exception as e:
        print("Image download failed:", e)
        return False


def create_fallback_news_image(path):
    img = Image.new("RGB", VIDEO_SIZE, (8, 16, 35))
    draw = ImageDraw.Draw(img)

    for y in range(VIDEO_HEIGHT):
        ratio = y / VIDEO_HEIGHT
        r = int(8 * (1 - ratio) + 12 * ratio)
        g = int(16 * (1 - ratio) + 55 * ratio)
        b = int(35 * (1 - ratio) + 95 * ratio)
        draw.line([(0, y), (VIDEO_WIDTH, y)], fill=(r, g, b))

    font_big = get_font(86, True)
    font_small = get_font(42, False)

    draw.text((80, 760), "ලෝක", font=font_big, fill="white")
    draw.text((80, 870), "පුවත්", font=font_big, fill=(255, 60, 60))
    draw.text((80, 1010), "යාවත්කාලීන කිරීම", font=font_small, fill="white")

    img.save(path, quality=95)


def get_news():
    used = load_used()
    news_items = []

    feeds = FEEDS.copy()
    random.shuffle(feeds)

    for feed_url in feeds:
        try:
            print("Checking feed:", feed_url)
            feed = feedparser.parse(feed_url)

            for entry in feed.entries[:10]:
                title = clean_text(entry.get("title", ""))
                summary = clean_text(entry.get("summary", ""))
                link = entry.get("link", "")

                if not title or not link:
                    continue

                news_id = hashlib.md5(link.encode("utf-8")).hexdigest()

                if news_id in used:
                    continue

                news_items.append({
                    "id": news_id,
                    "title": title,
                    "summary": summary,
                    "link": link,
                    "image_url": get_image_from_feed_entry(entry),
                    "source": feed.feed.get("title", "News Source"),
                })

        except Exception as e:
            print("Feed error:", e)

    if not news_items:
        return None

    random.shuffle(news_items)
    news = random.choice(news_items)

    article_image = get_image_from_article_page(news["link"])
    if article_image:
        news["image_url"] = article_image

    title_si = translate_to_sinhala(news["title"], 250)
    summary_si = translate_to_sinhala(news["summary"], 900)

    if not title_si:
        return None

    if not summary_si:
        summary_si = title_si

    news["title_si"] = title_si
    news["summary_si"] = summary_si

    used.append(news["id"])
    save_used(used)

    return news


def make_script(news):
    title = shorten(news["title_si"], 220)
    summary = shorten(news["summary_si"], MAX_SCRIPT_CHARS)

    return (
        f"{title}. "
        f"{summary}. "
        f"තවත් ලෝක පුවත් සඳහා {CHANNEL_NAME_SI} සමඟ රැඳී සිටින්න."
    )


def create_voice(script, path):
    tts = gTTS(text=script, lang=VOICE_LANGUAGE, slow=False)
    tts.save(path)


def add_dark_gradient(img):
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    for y in range(VIDEO_HEIGHT):
        if y < 620:
            alpha = int(150 - y / 620 * 50)
        elif y > 1080:
            alpha = int(70 + 160 * ((y - 1080) / 840))
        else:
            alpha = 45

        alpha = max(0, min(230, alpha))
        draw.line([(0, y), (VIDEO_WIDTH, y)], fill=(0, 0, 0, alpha))

    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def create_news_frame(news, image_path, progress=0.0):
    original = Image.open(image_path).convert("RGB")

    zoom = 1.0 + progress * 0.035
    crop_w = int(original.width / zoom)
    crop_h = int(original.height / zoom)

    left = max(0, (original.width - crop_w) // 2)
    top = max(0, (original.height - crop_h) // 2)

    original = original.crop((left, top, left + crop_w, top + crop_h))

    bg = cover_resize(original, VIDEO_SIZE)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=18))
    bg = add_dark_gradient(bg)

    img = bg.convert("RGBA")
    draw = ImageDraw.Draw(img)

    draw.rectangle((0, 0, VIDEO_WIDTH, 175), fill=(3, 8, 20, 245))

    draw.text(
        (50, 52),
        PAGE_NAME,
        font=get_font(48, True),
        fill="white"
    )

    draw.text(
        (820, 78),
        datetime.now().strftime("%Y-%m-%d"),
        font=get_font(25, False),
        fill=(210, 220, 235)
    )

    draw.rounded_rectangle(
        (50, 205, 1030, 315),
        radius=28,
        fill=(190, 18, 32, 245)
    )

    draw.text(
        (92, 237),
        "නවතම ලෝක පුවත්",
        font=get_font(42, True),
        fill="white"
    )

    draw.ellipse((900, 244, 930, 274), fill="white")
    draw.text((945, 237), "LIVE", font=get_font(32, True), fill="white")

    photo_x1, photo_y1 = 50, 360
    photo_x2, photo_y2 = 1030, 1085

    photo = cover_resize(original, (photo_x2 - photo_x1, photo_y2 - photo_y1))
    photo = photo.filter(ImageFilter.SHARPEN)

    mask = Image.new("L", photo.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle((0, 0, photo.size[0], photo.size[1]), radius=38, fill=255)

    img.paste(photo.convert("RGBA"), (photo_x1, photo_y1), mask)

    draw.rounded_rectangle(
        (photo_x1, photo_y1, photo_x2, photo_y2),
        radius=38,
        outline=(255, 255, 255, 85),
        width=3
    )

    panel_top = 1125
    panel_bottom = 1870

    draw.rounded_rectangle(
        (40, panel_top, 1040, panel_bottom),
        radius=38,
        fill=(5, 12, 28, 232),
        outline=(255, 255, 255, 60),
        width=2
    )

    draw.rounded_rectangle(
        (75, panel_top + 45, 235, panel_top + 60),
        radius=8,
        fill=(235, 30, 45)
    )

    title = shorten(news["title_si"], 160)
    summary = shorten(news["summary_si"], 420)

    title_font, title_lines, title_lh = fit_text_to_box(
        draw,
        title,
        900,
        300,
        50,
        30,
        True
    )

    y = panel_top + 90

    y = draw_multiline(
        draw,
        title_lines,
        75,
        y,
        title_font,
        title_lh,
        "white"
    )

    summary_font, summary_lines, summary_lh = fit_text_to_box(
        draw,
        summary,
        900,
        310,
        34,
        24,
        False
    )

    draw_multiline(
        draw,
        summary_lines[:7],
        75,
        y + 38,
        summary_font,
        summary_lh,
        (230, 235, 245)
    )

    return img.convert("RGB")


def create_video(news, image_path, audio_path, output_path):
    audio = AudioFileClip(audio_path)
    duration = audio.duration

    def make_frame(t):
        progress = min(1.0, t / max(duration, 1))
        frame = create_news_frame(news, image_path, progress)
        return np.array(frame)

    video = VideoClip(make_frame, duration=duration)
    video = video.with_audio(audio)

    video.write_videofile(
        output_path,
        fps=24,
        codec="libx264",
        audio_codec="aac",
        preset="medium",
        threads=2,
    )

    audio.close()
    video.close()


def upload_to_telegram(video_path, caption):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials missing.")
        return

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo"

        with open(video_path, "rb") as video_file:
            response = requests.post(
                url,
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "caption": caption,
                    "parse_mode": "HTML",
                },
                files={"video": video_file},
                timeout=300
            )

        print("Telegram response:", response.text)

    except Exception as e:
        print("Telegram upload failed:", e)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(ASSET_DIR, exist_ok=True)

    news = get_news()

    if not news:
        print("No valid Sinhala news found.")
        return

    print("Selected:", news["title_si"])

    raw_image_path = os.path.join(ASSET_DIR, "news_image.jpg")
    voice_path = os.path.join(ASSET_DIR, "voice.mp3")
    video_path = os.path.join(OUTPUT_DIR, "auto_video.mp4")

    image_ok = download_image(news.get("image_url"), raw_image_path)

    if not image_ok:
        create_fallback_news_image(raw_image_path)

    script = make_script(news)

    if not has_sinhala(script):
        print("Sinhala script failed.")
        return

    create_voice(script, voice_path)
    create_video(news, raw_image_path, voice_path, video_path)

    caption = f"📰 {news['title_si']}\n\n🌍 {PAGE_NAME}"
    upload_to_telegram(video_path, caption)

    print("Done.")


if __name__ == "__main__":
    main()
