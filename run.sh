#!/bin/bash
# Запуск PetriDish Monitor Bot

# Установка зависимостей
pip install -r requirements.txt -q

# Установка браузеров для Playwright
playwright install chromium

# Запуск бота
python bot.py
