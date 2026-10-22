"""
Vercel Serverless Function entry point для Telegram Webhook.
"""

from http.server import BaseHTTPRequestHandler
import json
import asyncio
import os
import sys
import logging

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from aiogram import Bot
from aiogram.types import Update
from bot import dp
import config

logger = logging.getLogger("vercel_webhook")


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        """Проверка статуса сервера и быстрая привязка вебхука."""
        if "action=set_webhook" in self.path:
            try:
                webhook_url = config.WEBHOOK_URL
                if not webhook_url:
                    host = self.headers.get("Host", "")
                    webhook_url = f"https://{host}/api"

                async def _set_wh():
                    async with Bot(token=config.BOT_TOKEN) as current_bot:
                        return await current_bot.set_webhook(url=webhook_url, drop_pending_updates=True)

                res = asyncio.run(_set_wh())
                msg = f"Webhook успешно установлен на: {webhook_url} (Результат: {res})"
                status_code = 200
            except Exception as e:
                msg = f"Ошибка установки вебхука: {e}"
                status_code = 500

            self.send_response(status_code)
            self.send_header("Content-type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(msg.encode("utf-8"))
            return

        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"OK")

    def do_POST(self):
        """Прием и обработка входящих сообщений (Update) от Telegram."""
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)

        async def _handle():
            async with Bot(token=config.BOT_TOKEN) as current_bot:
                update_data = json.loads(post_data.decode("utf-8"))
                update = Update.model_validate(update_data, context={"bot": current_bot})
                await dp.feed_update(current_bot, update)

        try:
            asyncio.run(_handle())
        except Exception as e:
            logger.exception("Ошибка при обработке вебхука:")

        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))
