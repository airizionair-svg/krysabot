"""
PetriDish.pw Server Monitor — Telegram Bot
Чекает серверы каждые 20 секунд через Playwright (headless браузер).
Уведомляет если онлайн вырос на 5+ игроков.
"""

import asyncio
import logging
import os
from datetime import datetime

from telegram import Bot
from telegram.constants import ParseMode
from playwright.async_api import async_playwright

# ──────────────────────────────────────────────
# НАСТРОЙКИ — через переменные окружения
# ──────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TG_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TG_CHAT", "")

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

# Хранилище: { server_name: player_count }
previous: dict[str, int] = {}


async def fetch_servers() -> dict[str, int]:
    """
    Загружает страницу petridish.pw через Playwright,
    ждёт загрузки списка серверов и парсит онлайн.
    """
    servers: dict[str, int] = {}

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = await context.new_page()

            # Загружаем страницу
            await page.goto("https://petridish.pw/en/", wait_until="networkidle", timeout=30000)

            # Ждём появления списка серверов (FFA режим по умолчанию)
            await page.wait_for_selector(".server-list", timeout=10000)

            # Кликаем на FFA чтобы увидеть список серверов
            ffa_btn = await page.query_selector(".mode-item:has-text('FFA')")
            if ffa_btn:
                await ffa_btn.click()
                await asyncio.sleep(1)

            # Получаем все элементы серверов
            server_items = await page.query_selector_all(".server-item")

            for item in server_items:
                # Название сервера
                name_el = await item.query_selector(".server-name")
                name = await name_el.inner_text() if name_el else ""
                name = name.strip()

                # Онлайн (формат "12/300")
                online_el = await item.query_selector(".server-online")
                online_text = await online_el.inner_text() if online_el else "0/0"

                # Парсим число игроков
                try:
                    current = int(online_text.split("/")[0].strip())
                except (ValueError, IndexError):
                    current = 0

                if name and current >= MIN_PLAYERS:
                    servers[name] = current

            await browser.close()

        if servers:
            log.info(f"Найдено {len(servers)} серверов через Playwright")
        else:
            log.warning("Серверы не найдены — возможно изменился формат страницы")

    except Exception as e:
        log.warning(f"Ошибка при загрузке страницы: {e}")

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


async def check_and_notify(bot: Bot):
    global previous

    current = await fetch_servers()
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

    while True:
        try:
            await check_and_notify(bot)
        except Exception as e:
            log.error(f"Неожиданная ошибка: {e}")
        await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
