# PetriDish.pw Server Monitor Bot

Telegram-бот мониторинга серверов petridish.pw.
Уведомляет когда онлайн на сервере вырастает на 5+ игроков.

## Быстрый старт

### 1. Получить токен Telegram бота
1. Открой @BotFather в Telegram
2. Напиши `/newbot` → задай имя → получи токен вида `123456789:AABBcc...`

### 2. Получить Chat ID
1. Добавь бота в нужный чат (или напиши ему лично)
2. Открой: `https://api.telegram.org/bot<ВАШ_ТОКЕН>/getUpdates`
3. Найди поле `"chat":{"id": -100XXXXXXXXXX}` — это и есть chat_id

### 3. Установка зависимостей
```bash
pip install -r requirements.txt
```

### 4. Запуск

**Вариант A — через переменные окружения (рекомендуется):**
```bash
export TG_TOKEN="123456789:AABBcc..."
export TG_CHAT="-1001234567890"
python bot.py
```

**Вариант B — вписать прямо в bot.py:**
Открой `bot.py`, найди строки:
```python
TELEGRAM_TOKEN   = os.getenv("TG_TOKEN", "ВАШ_ТОКЕН_БОТА")
TELEGRAM_CHAT_ID = os.getenv("TG_CHAT",  "ВАШ_CHAT_ID")
```
Замени `"ВАШ_ТОКЕН_БОТА"` и `"ВАШ_CHAT_ID"` на свои данные.

## Настройки (в bot.py)

| Параметр | По умолчанию | Описание |
|----------|-------------|----------|
| `CHECK_INTERVAL` | `20` | Секунд между проверками |
| `MIN_GROWTH` | `5` | Минимальный прирост для уведомления |
| `MIN_PLAYERS` | `1` | Игнорировать серверы с онлайном ниже |

## Пример уведомления в Telegram

```
📈 MEGASPLIT3 — онлайн вырос!
├ Было: 4 → Стало: 11 (+7)
├ Режим: megasplit
└ Подключиться
```

## Автозапуск (Linux/VPS)

Создай systemd-сервис `/etc/systemd/system/petridish.service`:
```ini
[Unit]
Description=PetriDish Monitor Bot
After=network.target

[Service]
WorkingDirectory=/путь/к/petridish_bot
Environment=TG_TOKEN=123456789:AABBcc...
Environment=TG_CHAT=-1001234567890
ExecStart=/usr/bin/python3 bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Затем:
```bash
sudo systemctl enable petridish
sudo systemctl start petridish
sudo systemctl status petridish
```

## Важно

Petridish.pw не имеет публичного API — бот парсит данные с сайта.
Если разработчики изменят структуру страницы, может потребоваться обновление парсера в функции `fetch_servers()`.
