"""
Vercel Serverless Function entry point для Telegram Webhook.
"""

from http.server import BaseHTTPRequestHandler
import json
import asyncio
import os
import sys

# Добавляем корневую директорию проекта в sys.path для корректных импортов
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from aiogram.types import Update
from bot import dp, bot
import config


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        """Проверка статуса сервера и быстрая привязка вебхука."""
        if "action=set_webhook" in self.path:
            try:
                webhook_url = config.WEBHOOK_URL
                if not webhook_url:
                    host = self.headers.get("Host", "")
                    webhook_url = f"https://{host}/api"

                res = asyncio.run(bot.set_webhook(url=webhook_url, drop_pending_updates=True))
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
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        html = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Telegram Background Removal Bot</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; text-align: center; padding: 60px 20px; background: #0d1117; color: #c9d1d9; }
        .card { max-width: 500px; margin: 0 auto; background: #161b22; padding: 30px; border-radius: 12px; border: 1px solid #30363d; }
        h1 { color: #58a6ff; font-size: 24px; }
        .status { color: #3fb950; font-weight: bold; font-size: 18px; margin: 20px 0; }
        a.btn { display: inline-block; background: #238636; color: white; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: bold; margin-top: 15px; }
        a.btn:hover { background: #2ea043; }
    </style>
</head>
<body>
    <div class="card">
        <h1>✂️ Telegram BG Removal Bot</h1>
        <div class="status">🟢 Сервер работает 24/7 на Vercel!</div>
        <p>Для привязки бота к этому серверу нажмите кнопку ниже:</p>
        <a class="btn" href="?action=set_webhook">Привязать Telegram Webhook</a>
    </div>
</body>
</html>"""
        self.wfile.write(html.encode("utf-8"))

    def do_POST(self):
        """Прием и обработка входящих сообщений (Update) от Telegram."""
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)

        try:
            update_data = json.loads(post_data.decode("utf-8"))
            update = Update.model_validate(update_data, context={"bot": bot})
            asyncio.run(dp.feed_update(bot, update))
        except Exception as e:
            print(f"Ошибка при обработке вебхука: {e}")

        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))
