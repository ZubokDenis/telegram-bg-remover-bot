"""
Конфигурация бота и чтение переменных окружения.
"""

import os
from dotenv import load_dotenv

# Загружаем .env файл при локальной разработке
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# URL для вебхука на Vercel (например: https://your-project.vercel.app/api)
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()

# Секретный токен для защиты вебхука от посторонних запросов (опционально)
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "tg-bot-secret").strip()

# Режим работы по умолчанию: 'auto', 'floodfill', 'grabcut'
DEFAULT_MODE = os.getenv("DEFAULT_MODE", "auto").strip()
