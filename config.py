"""
Конфигурация бота и чтение переменных окружения.
"""

import os
from dotenv import load_dotenv

# Загружаем .env файл при локальной разработке
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "6581589766:AAEJvUMBzY9AnsYseib68-EJarzTtRTxPzE").strip()

# URL для вебхука на Vercel (например: https://your-project.vercel.app/api)
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()

# Секретный токен для защиты вебхука от посторонних запросов (опционально)
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "tg-bot-secret").strip()

# Токен Hugging Face для бесплатной нейросети RMBG-1.4 (опционально)
HF_TOKEN = os.getenv("HF_TOKEN", "").strip()

# Режим работы по умолчанию: 'auto', 'floodfill', 'grabcut'
DEFAULT_MODE = os.getenv("DEFAULT_MODE", "auto").strip()

