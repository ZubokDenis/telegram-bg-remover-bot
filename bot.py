"""
Telegram-бот для удаления фона и конвертации форматов.
Работает без лишнего текста и сообщений — только результат в виде файла.
"""

import asyncio
import io
import logging
from typing import Optional

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    BufferedInputFile,
)

import config
import image_processor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("tg_bg_bot")

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()


def detect_target_format(text: Optional[str]) -> str:
    """Определяет желаемый формат из подписи: svg, png, jpeg (по умолчанию png)."""
    if not text:
        return "png"
    text_lower = text.lower().strip()
    if "/svg" in text_lower or text_lower == "svg":
        return "svg"
    elif "/jpeg" in text_lower or text_lower == "jpeg" or "/jpg" in text_lower or text_lower == "jpg":
        return "jpeg"
    elif "/png" in text_lower or text_lower == "png":
        return "png"
    return "png"


@dp.message(CommandStart())
async def cmd_start(message: Message):
    """Минималистичный ответ на старт."""
    await message.answer("👌")


async def extract_image_bytes(message: Message, current_bot: Bot) -> Optional[bytes]:
    """Извлекает байты изображения из фото или документа."""
    file_id = None
    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.document and message.document.mime_type and message.document.mime_type.startswith("image/"):
        file_id = message.document.file_id

    if not file_id:
        return None

    file_info = await current_bot.get_file(file_id)
    if not file_info.file_path:
        return None

    buf = io.BytesIO()
    await current_bot.download_file(file_info.file_path, destination=buf)
    return buf.getvalue()


@dp.message(F.photo | (F.document & F.document.mime_type.startswith("image/")))
async def on_image_received(message: Message, bot: Bot):
    """
    Обработка изображения:
    - Вырезает фон и сохраняет в запрошенном формате (PNG по умолчанию, либо SVG / JPEG / PNG при приписке).
    - Никакого текста, только итоговый файл.
    """
    img_bytes = await extract_image_bytes(message, bot)
    if not img_bytes:
        return

    caption = message.caption or ""
    target_format = detect_target_format(caption)

    try:
        out_bytes, filename, mime_type = await asyncio.to_thread(
            image_processor.process_image,
            img_bytes,
            target_format,
            "auto"
        )

        input_file = BufferedInputFile(out_bytes, filename=filename)

        if filename.endswith(".jpg") or filename.endswith(".jpeg"):
            await message.answer_photo(photo=input_file)
        else:
            await message.answer_document(document=input_file)

    except Exception as e:
        logger.exception("Ошибка при обработке изображения:")


@dp.message(F.reply_to_message & (F.text.startswith("/") | F.text.in_({"svg", "png", "jpeg", "jpg"})))
async def on_reply_format(message: Message, bot: Bot):
    """Ответ командой /svg, /png, /jpeg на ранее отправленное фото."""
    replied = message.reply_to_message
    img_bytes = await extract_image_bytes(replied, bot)
    if not img_bytes:
        return

    target_format = detect_target_format(message.text)

    try:
        out_bytes, filename, mime_type = await asyncio.to_thread(
            image_processor.process_image,
            img_bytes,
            target_format,
            "auto"
        )
        input_file = BufferedInputFile(out_bytes, filename=filename)

        if filename.endswith(".jpg") or filename.endswith(".jpeg"):
            await replied.answer_photo(photo=input_file)
        else:
            await replied.answer_document(document=input_file)
    except Exception as e:
        logger.exception("Ошибка при обработке по реплаю:")


async def main():
    logger.info("Запуск Telegram-бота...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
