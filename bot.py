"""
PetriDish.pw Server Monitor — Telegram Bot
Чекает серверы каждые 20 секунд.
Уведомляет если онлайн вырос на 5+ игроков.
"""

import asyncio
import logging
import re
import os
from datetime import datetime

import aiohttp
from bs4 import BeautifulSoup
from telegram import Bot
from telegram.constants import ParseMode

# ──────────────────────────────────────────────
# НАСТРОЙКИ — заполни перед запуском
# ──────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TG_TOKEN", "ВАШ_ТОКЕН_БОТА")
TELEGRAM_CHAT_ID = os.getenv("TG_CHAT",  "ВАШ_CHAT_ID")

CHECK_INTERVAL   = 20      # секунд между проверками
MIN_GROWTH       = 5       # минимальный прирост игроков для уведомления
MIN_PLAYERS      = 1       # игнорировать серверы с онлайном ниже этого
# ──────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}

# Хранилище: { server_name: player_count }
previous: dict[str, int] = {}


async def fetch_servers(session: aiohttp.ClientSession) -> dict[str, int]:
    """
    Получает список серверов с petridish.pw.
    Парсит JS-переменную с данными о серверах прямо из HTML.
    Возвращает словарь {имя_сервера: онлайн}.
    """
    servers: dict[str, int] = {}

    try:
        async with session.get(
            "https://petridish.pw/en/",
            headers=HEADERS,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            html = await resp.text()
    except Exception as e:
        log.warning(f"Ошибка при загрузке страницы: {e}")
        return servers

    # Сначала пробуем найти JSON с серверами в JS
    # Паттерн типа: servers=[{name:"ffa1",online:12,...},...]
    # или serverList = [{...}]
    json_patterns = [
        r'serverList\s*=\s*(\[.*?\]);',
        r'servers\s*=\s*(\[.*?\]);',
        r'"servers"\s*:\s*(\[.*?\])',
    ]
    for pat in json_patterns:
        m = re.search(pat, html, re.DOTALL)
        if m:
            try:
                import json
                data = json.loads(m.group(1))
                for s in data:
                    name   = s.get("name") or s.get("id") or s.get("server", "")
                    online = int(s.get("online") or s.get("players") or s.get("cnt") or 0)
                    if name:
                        servers[name] = online
                if servers:
                    log.info(f"Найдено {len(servers)} серверов через JS-JSON")
                    return servers
            except Exception:
                pass

    # Запасной вариант — парсим HTML таблицу серверов
    soup = BeautifulSoup(html, "html.parser")

    # Паттерн для inline-данных в атрибутах / data-атрибутах
    for tag in soup.find_all(True, attrs={"data-online": True}):
        name   = tag.get("data-name") or tag.get("data-server") or tag.get("id", "")
        online = tag.get("data-online", "0")
        try:
            servers[name] = int(online)
        except ValueError:
            pass

    if servers:
        log.info(f"Найдено {len(servers)} серверов через data-атрибуты")
        return servers

    # Последний вариант: ищем паттерны вида  "ffa1":{"online":7}
    inline_matches = re.findall(
        r'"([a-z0-9_]+)"\s*:\s*\{[^}]*?"online"\s*:\s*(\d+)', html
    )
    for name, cnt in inline_matches:
        servers[name] = int(cnt)

    # Также паттерн: addServer('ffa1', 7, ...)
    call_matches = re.findall(
        r"addServer\(\s*['\"]([^'\"]+)['\"]\s*,\s*(\d+)", html
    )
    for name, cnt in call_matches:
        servers[name] = int(cnt)

    if servers:
        log.info(f"Найдено {len(servers)} серверов через regex")
    else:
        log.warning("Серверы не найдены — возможно изменился формат страницы")

    return servers


def build_message(name: str, old: int, new: int) -> str:
    growth = new - old
    arrow  = "📈" if growth > 0 else "📉"
    mode   = name.rstrip("0123456789")   # ffa, hardcore, megasplit …
    url    = f"https://petridish.pw/en/#server={name}"

    return (
        f"{arrow} *{name.upper()}* — онлайн вырос!\n"
        f"├ Было: `{old}` → Стало: `{new}` *(+{growth})*\n"
        f"├ Режим: `{mode}`\n"
        f"└ [Подключиться]({url})"
    )


async def check_and_notify(bot: Bot, session: aiohttp.ClientSession):
    global previous

    current = await fetch_servers(session)
    if not current:
        return

    notified = 0
    for name, online in current.items():
        if online < MIN_PLAYERS:
            continue

        old = previous.get(name, 0)
        growth = online - old

        if growth >= MIN_GROWTH:
            msg = build_message(name, old, online)
            try:
                await bot.send_message(
                    chat_id=TELEGRAM_CHAT_ID,
                    text=msg,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True,
                )
                log.info(f"✉ Уведомление: {name} {old}→{online} (+{growth})")
                notified += 1
            except Exception as e:
                log.error(f"Ошибка отправки: {e}")

    previous = current
    total = sum(current.values())
    log.info(
        f"Проверено {len(current)} серверов | "
        f"Всего онлайн: {total} | "
        f"Уведомлений: {notified}"
    )


async def main():
    log.info("🚀 PetriDish Monitor запущен")
    log.info(f"   Интервал: {CHECK_INTERVAL}с | Мин. прирост: {MIN_GROWTH}")

    bot = Bot(token=TELEGRAM_TOKEN)
    me = await bot.get_me()
    log.info(f"   Telegram бот: @{me.username}")

    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        while True:
            try:
                await check_and_notify(bot, session)
            except Exception as e:
                log.error(f"Неожиданная ошибка: {e}")
            await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
