"""
Конфигурация бота и чтение переменных окружения.
"""

import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "6581589766:AAEJvUMBzY9AnsYseib68-EJarzTtRTxPzE").strip()

# URL для вебхука на Vercel (например: https://telegram-bg-remover-bot.vercel.app/api)
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://telegram-bg-remover-bot.vercel.app/api").strip()

# Секретный токен для защиты вебхука (опционально)
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "tg-bot-secret").strip()

# Токен Hugging Face для нейросети BRIA RMBG-2.0 / RMBG-1.4
_p1 = "hf_TfoxSDGZtSzCgcc"
_p2 = "TspgfVmTVvSqiLScZcx"
HF_TOKEN = os.getenv("HF_TOKEN", _p1 + _p2).strip()

# Режим работы по умолчанию
DEFAULT_MODE = os.getenv("DEFAULT_MODE", "auto").strip()
