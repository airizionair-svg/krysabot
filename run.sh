#!/bin/bash
# Запуск PetriDish Monitor Bot

# Установка зависимостей (если нужно)
pip install -r requirements.txt -q

# Запуск бота
# Можно передать токен и chat_id через переменные окружения:
# TG_TOKEN="123:AAA..." TG_CHAT="-1001234567" python bot.py

python bot.py
