"""Read-only PetriDish public player-count monitor with Telegram alerts."""

from __future__ import annotations

import json
import logging
import time
import argparse
import ssl
from urllib.parse import urlencode
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state.json"
SOURCE_URL = "https://petridish.pw/en/"
USER_AGENT = "PetriDishOnlineChecker/1.0 (read-only public online monitor)"
MAX_TELEGRAM_TEXT = 3500

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("petridish-monitor")


def verified_ssl_context() -> ssl.SSLContext:
    """Обычная проверка TLS + доверенные сертификаты из хранилища Windows."""
    context = ssl.create_default_context()
    # Python 3.13+ включает строгий режим, который ломается на корпоративных/антивирусных корнях
    if hasattr(ssl, "VERIFY_X509_STRICT"):
        context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    if hasattr(ssl, "enum_certificates"):
        for store in ("ROOT", "CA"):
            try:
                for cert_bytes, encoding, trust in ssl.enum_certificates(store):
                    if encoding != "x509_asn":
                        continue
                    if trust is True or "1.3.6.1.5.5.7.3.1" in trust:
                        try:
                            context.load_verify_locations(
                                cadata=ssl.DER_cert_to_PEM_cert(cert_bytes))
                        except (ssl.SSLError, ValueError):
                            continue
            except OSError as exc:
                log.warning("Не удалось прочитать хранилище Windows (%s): %s", store, exc)
    return context


SSL_CONTEXT = verified_ssl_context()

# Только для чтения публичной страницы PetriDish, если её сертификат не проходит проверку.
# Telegram всегда использует SSL_CONTEXT с полной проверкой.
INSECURE_CONTEXT = ssl.create_default_context()
INSECURE_CONTEXT.check_hostname = False
INSECURE_CONTEXT.verify_mode = ssl.CERT_NONE


def telegram_context(cfg: dict) -> ssl.SSLContext:
    if cfg.get("telegram_verify_ssl", True) is False:
        return INSECURE_CONTEXT
    return SSL_CONTEXT


class ServerParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.servers: dict[str, dict] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "li":
            return
        a = {key.lower(): value or "" for key, value in attrs}
        if "server-item" not in a.get("class", "").split():
            return
        if a.get("serverstatus", "").lower() != "on":
            return
        try:
            online = int(a.get("data-nowplay", ""))
        except ValueError:
            return
        name = a.get("data-name") or a.get("autorun")
        if not name:
            return
        region = a.get("data-country", "")
        location = a.get("data-loc", "")
        key = "|".join((a.get("autorun", name), region, location))
        self.servers[key] = {
            "name": name,
            "mode": a.get("mode", "Unknown"),
            "region": region,
            "online": online,
            "capacity": a.get("data-maxplay", ""),
        }


def load_config(require_chat: bool = True) -> dict:
    if not CONFIG_PATH.exists():
        example_path = ROOT / "config.example.json"
        if not example_path.exists():
            raise RuntimeError("Нет config.json и config.example.json рядом со скриптом.")
        CONFIG_PATH.write_text(example_path.read_text(encoding="utf-8"), encoding="utf-8")
        log.info("Создал config.json рядом со скриптом. Заполни bot_token и запусти снова.")
        raise RuntimeError("Конфиг создан автоматически; добавь новый bot_token в config.json.")
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        cfg = json.load(f)
    required = ("bot_token", "chat_id") if require_chat else ("bot_token",)
    for key in required:
        if not str(cfg.get(key, "")).strip():
            raise RuntimeError(f"Заполни поле {key} в config.json")
    token = str(cfg["bot_token"]).strip()
    if not token.isascii() or ":" not in token or " " in token:
        raise RuntimeError(
            "bot_token в config.json не заполнен или неверный. Вставь настоящий токен от "
            "@BotFather (вид 123456789:AA...), без русских букв и пробелов.")
    if "chat_id" in cfg and str(cfg["chat_id"]).strip() and not str(cfg["chat_id"]).strip().lstrip("-").isdigit():
        raise RuntimeError("chat_id в config.json должен быть числом, например -1001234567890")
    cfg["poll_seconds"] = max(60, int(cfg.get("poll_seconds", 60)))
    cfg["increase_by"] = max(1, int(cfg.get("increase_by", 5)))
    return cfg


def discover_chat_ids(cfg: dict) -> None:
    """Print chat IDs from recent bot updates without displaying message contents."""
    token = str(cfg["bot_token"]).strip()
    url = f"https://api.telegram.org/bot{token}/getUpdates?" + urlencode({
        "limit": 100,
        "allowed_updates": json.dumps(["message", "edited_message", "channel_post"]),
    })
    req = Request(url, headers={"User-Agent": "PetriDishOnlineChecker/1.0"})
    try:
        with urlopen(req, timeout=20, context=telegram_context(cfg)) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except HTTPError as exc:
        raise RuntimeError(f"Telegram getUpdates вернул HTTP {exc.code}; проверь новый токен.") from None
    except URLError as exc:
        raise RuntimeError(f"Не удалось подключиться к Telegram: {exc.reason}") from None
    if not payload.get("ok"):
        raise RuntimeError("Telegram Bot API не принял запрос getUpdates.")

    chats = {}
    for update in payload.get("result", []):
        for key in ("message", "edited_message", "channel_post"):
            message = update.get(key) or {}
            chat = message.get("chat") or {}
            if "id" not in chat:
                continue
            chat_id = str(chat["id"])
            chats[chat_id] = {
                "title": chat.get("title") or chat.get("username") or chat.get("first_name") or "Без названия",
                "type": chat.get("type", "unknown"),
            }

    if not chats:
        print("Пока нет новых сообщений для бота.")
        print("Добавь бота в нужную беседу и отправь там команду /start@ИмяТвоегоБота.")
        print("Затем запусти этот режим ещё раз. Текст сообщений скрипт не выводит.")
        return

    print("Найденные беседы (выбери chat_id нужной группы/канала):")
    for chat_id, chat in chats.items():
        print(f"chat_id: {chat_id} | {chat['type']} | {chat['title']}")
    print("Скопируй только нужный chat_id в config.json.")



def fetch_servers() -> dict[str, dict]:
    req = Request(
        SOURCE_URL,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/130.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
        },
    )

    try:
        with urlopen(req, timeout=25, context=SSL_CONTEXT) as response:
            body = response.read(8_000_000).decode(
                "utf-8", errors="replace"
            )
    except HTTPError as exc:
        log.error(
            "PetriDish HTTP %s; server=%s; content-type=%s",
            exc.code,
            exc.headers.get("Server"),
            exc.headers.get("Content-Type"),
        )
        raise
    except URLError as exc:
        if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
            raise
        log.error("Ошибка проверки TLS-сертификата PetriDish.")
        raise

    parser = ServerParser()
    parser.feed(body)

    if len(parser.servers) < 10:
        raise RuntimeError(
            f"Найдено только {len(parser.servers)} активных серверов."
        )

    return parser.servers


def load_state() -> dict | None:
    try:
        with STATE_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Не удалось прочитать состояние: %s. Начинаю с нового baseline.", exc)
        return None


def save_state(servers: dict[str, dict]) -> None:
    state = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "servers": {key: value["online"] for key, value in servers.items()},
    }
    temp_path = STATE_PATH.with_suffix(".tmp")
    temp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(STATE_PATH)


def telegram_send(cfg: dict, text: str) -> None:
    token = str(cfg["bot_token"]).strip()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urlencode({
        "chat_id": str(cfg["chat_id"]).strip(),
        "text": text,
        "disable_web_page_preview": "true",
    }).encode("utf-8")
    req = Request(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urlopen(req, timeout=20, context=telegram_context(cfg)) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except HTTPError as exc:
        raise RuntimeError(f"Telegram sendMessage вернул HTTP {exc.code} (проверь токен и chat_id).") from None
    except URLError as exc:
        raise RuntimeError(f"Ошибка соединения с Telegram (не с сайтом игры): {exc.reason}") from None
    if not payload.get("ok"):
        raise RuntimeError("Telegram Bot API вернул ошибку: " + str(payload.get("description", "unknown")))


def format_events(events: list[dict], checked_at: str, threshold: int) -> list[str]:
    header = f"🥣 PetriDish: прирост игроков за интервал не менее +{threshold}\nПроверка: {checked_at} UTC\n\n"
    messages = []
    current = header
    for event in events:
        line = (
            f"• {event['mode']} / {event['name']} ({event['region'] or 'регион не указан'}): "
            f"{event['before']} → {event['online']} (+{event['delta']})"
        )
        if event["capacity"]:
            line += f"/{event['capacity']}"
        line += "\n"
        if len(current) + len(line) > MAX_TELEGRAM_TEXT:
            messages.append(current.rstrip())
            current = header + line
        else:
            current += line
    if current != header:
        messages.append(current.rstrip())
    return messages


def check_once(cfg: dict) -> None:
    servers = fetch_servers()
    previous = load_state()
    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    if previous is None or not isinstance(previous.get("servers"), dict):
        save_state(servers)
        log.info("Первый замер: сохранён baseline для %d серверов, уведомлений пока нет.", len(servers))
        return

    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(previous["checked_at"])).total_seconds()
    except (KeyError, TypeError, ValueError):
        age = None
    if age is None or age > 600:
        save_state(servers)
        log.info("Старый замер (устарел), сохранён новый baseline для %d серверов.", len(servers))
        return

    old = previous["servers"]
    threshold = cfg["increase_by"]
    events = []
    for key, server in servers.items():
        try:
            before = int(old.get(key, server["online"]))
        except (TypeError, ValueError):
            before = server["online"]
        delta = server["online"] - before
        if delta >= threshold:
            events.append({**server, "before": before, "delta": delta})

    if not events:
        save_state(servers)
        log.info("Проверено %d серверов; прироста на +%d за интервал нет.", len(servers), threshold)
        return

    events.sort(key=lambda e: (-e["delta"], e["mode"], e["name"]))
    messages = format_events(events, checked_at, threshold)
    for message in messages:
        telegram_send(cfg, message)
    # Save only after successful delivery so Telegram failures retry against the prior sample.
    save_state(servers)
    log.info("Отправлено уведомлений по серверам: %d", len(events))


def main() -> None:
    cli = argparse.ArgumentParser(description="PetriDish public online monitor")
    cli.add_argument("--discover-chat", action="store_true",
                     help="показать chat_id из последних обновлений бота")
    args = cli.parse_args()
    cfg = load_config(require_chat=not args.discover_chat)
    if args.discover_chat:
        discover_chat_ids(cfg)
        return
    log.info(
        "Монитор запущен: источник %s, интервал %d сек., порог +%d.",
        SOURCE_URL, cfg["poll_seconds"], cfg["increase_by"],
    )
    while True:
        try:
            check_once(cfg)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
            log.error("Проверка не удалась: %s", exc)
        except Exception:
            log.exception("Неожиданная ошибка цикла")
        time.sleep(cfg["poll_seconds"])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Монитор остановлен пользователем.")
