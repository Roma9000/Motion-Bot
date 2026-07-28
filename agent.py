#!/usr/bin/env python3
"""
Motion Design Job Agent
Моніторить Upwork і Freelancehunt і надсилає нові вакансії в Telegram
"""

import feedparser
import requests
import json
import time
import hashlib
import os
import logging
from datetime import datetime
from pathlib import Path

# ─── НАЛАШТУВАННЯ ────────────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
CHECK_INTERVAL     = 10 * 60               # кожні 10 хвилин (секунди)
SEEN_FILE          = "seen_jobs.json"

# ─── КЛЮЧОВІ СЛОВА для фільтрації ────────────────────────────────────────────

KEYWORDS_EN = [
    "motion", "animation", "animate", "motion design", "motion designer",
    "motion graphic", "after effects", "lottie", "explainer video",
    "logo animation", "ui animation", "kinetic typography",
    "product demo", "saas explainer", "promo video",
    "social media ad", "web animation", "2d animation",
    "video editor", "ae template", "premiere", "cinema 4d", "c4d",
]

KEYWORDS_UK = [
    "моушн", "анімація", "аніматор", "відео", "моушн дизайн",
    "анімація логотипу", "explainer", "моушн дизайнер",
    "after effects", "lottie", "промо відео", "рекламний ролик",
    "соц мережі", "відео реклама", "кінетична типографіка",
]

# ─── RSS СТРІЧКИ ──────────────────────────────────────────────────────────────

RSS_FEEDS = [
    {
        "name": "Upwork 🌍",
        "url": "https://www.upwork.com/ab/feed/jobs/rss?q=motion+design&sort=recency&paging=0%3B10",
        "lang": "en",
        "emoji": "🟢",
    },
    {
        "name": "Upwork Animation 🌍",
        "url": "https://www.upwork.com/ab/feed/jobs/rss?q=motion+graphics+animation&sort=recency&paging=0%3B10",
        "lang": "en",
        "emoji": "🟢",
    },
    {
        "name": "Freelancehunt 🇺🇦",
        "url": "https://freelancehunt.com/projects/feed",
        "lang": "uk",
        "emoji": "🔵",
    },
]

# ─── ЛОГУВАННЯ ───────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("agent.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ─── СТАН: вже бачені вакансії ───────────────────────────────────────────────

def load_seen() -> set:
    if Path(SEEN_FILE).exists():
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_seen(seen: set):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen), f)

def job_id(title: str, link: str) -> str:
    return hashlib.md5(f"{title}{link}".encode()).hexdigest()

# ─── ФІЛЬТР ──────────────────────────────────────────────────────────────────

def is_relevant(title: str, summary: str, lang: str) -> bool:
    text = (title + " " + summary).lower()
    keywords = KEYWORDS_EN if lang == "en" else KEYWORDS_UK
    # Для Freelancehunt перевіряємо обидві мови
    if lang == "uk":
        keywords = KEYWORDS_EN + KEYWORDS_UK
    return any(kw.lower() in text for kw in keywords)

# ─── TELEGRAM ────────────────────────────────────────────────────────────────

def send_telegram(message: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            return True
        else:
            log.error(f"Telegram помилка: {resp.status_code} — {resp.text}")
            return False
    except Exception as e:
        log.error(f"Telegram виключення: {e}")
        return False

def format_job_message(feed_name: str, emoji: str, title: str, link: str, summary: str) -> str:
    # Обрізаємо summary до 300 символів
    short_summary = summary[:300].strip()
    if len(summary) > 300:
        short_summary += "…"

    # Прибираємо HTML теги зі summary
    import re
    short_summary = re.sub(r"<[^>]+>", "", short_summary).strip()

    now = datetime.now().strftime("%H:%M")
    return (
        f"{emoji} <b>Нова вакансія!</b> [{feed_name}] • {now}\n\n"
        f"📌 <b>{title}</b>\n\n"
        f"{short_summary}\n\n"
        f"🔗 <a href='{link}'>Відкрити проєкт</a>"
    )

# ─── ПЕРЕВІРКА ОДНОГО ФІДУ ───────────────────────────────────────────────────

def check_feed(feed_config: dict, seen: set) -> list[str]:
    new_ids = []
    try:
        log.info(f"Перевіряю: {feed_config['name']}")
        parsed = feedparser.parse(feed_config["url"])

        if parsed.bozo:
            log.warning(f"⚠️ Проблема з RSS: {feed_config['name']}")

        for entry in parsed.entries:
            title   = getattr(entry, "title", "Без назви")
            link    = getattr(entry, "link", "")
            summary = getattr(entry, "summary", "")

            jid = job_id(title, link)
            if jid in seen:
                continue

            if is_relevant(title, summary, feed_config["lang"]):
                msg = format_job_message(
                    feed_config["name"],
                    feed_config["emoji"],
                    title, link, summary
                )
                if send_telegram(msg):
                    log.info(f"✅ Надіслано: {title[:60]}")
                    new_ids.append(jid)
                    time.sleep(1)  # щоб не заспамити Telegram
            else:
                # Позначаємо як переглянуте, навіть якщо не релевантне
                new_ids.append(jid)

    except Exception as e:
        log.error(f"Помилка при перевірці {feed_config['name']}: {e}")

    return new_ids

# ─── ГОЛОВНИЙ ЦИКЛ ───────────────────────────────────────────────────────────

def main():
    log.info("🎬 Motion Design Job Agent запущено!")
    log.info(f"Перевірка кожні {CHECK_INTERVAL // 60} хвилин")

    # Перевіряємо конфіг
    if "ВАШ_ТОКЕН" in TELEGRAM_BOT_TOKEN or "ВАШ_CHAT_ID" in TELEGRAM_CHAT_ID:
        log.error("❌ Заповни TELEGRAM_BOT_TOKEN та TELEGRAM_CHAT_ID у скрипті!")
        return

    # Стартове повідомлення
    send_telegram(
        "🎬 <b>Motion Job Agent запущено!</b>\n\n"
        "Моніторю Upwork і Freelancehunt по ключовим словам:\n"
        "motion, animation, after effects, lottie, explainer, logo animation та інші\n\n"
        "Буду надсилати нові вакансії сюди 🚀"
    )

    seen = load_seen()
    log.info(f"Завантажено {len(seen)} переглянутих вакансій")

    while True:
        for feed in RSS_FEEDS:
            new_ids = check_feed(feed, seen)
            seen.update(new_ids)

        save_seen(seen)
        log.info(f"💤 Сплю {CHECK_INTERVAL // 60} хвилин...")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
