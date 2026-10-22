"""
Telegram-бот для удаления фона и конвертации форматов.
Работает без лишнего текста и сообщений — только результат в виде файла.
"""

import asyncio
import io
import logging
from typing import Optional, Tuple

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


def detect_target_format(text: Optional[str]) -> Optional[str]:
    """Определяет желаемый формат из подписи или возвращает None, если приписки нет."""
    if not text:
        return None
    text_lower = text.lower().strip()
    if "/svg" in text_lower or text_lower == "svg":
        return "svg"
    elif "/jpeg" in text_lower or text_lower == "jpeg" or "/jpg" in text_lower or text_lower == "jpg":
        return "jpeg"
    elif "/png" in text_lower or text_lower == "png":
        return "png"
    return None


@dp.message(CommandStart())
async def cmd_start(message: Message):
    """Минималистичный ответ на старт."""
    await message.answer("👌")


async def extract_image_bytes(message: Message) -> Optional[bytes]:
    """Извлекает байты изображения из фото или документа."""
    file_id = None
    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.document and message.document.mime_type and message.document.mime_type.startswith("image/"):
        file_id = message.document.file_id

    if not file_id:
        return None

    file_info = await bot.get_file(file_id)
    if not file_info.file_path:
        return None

    downloaded = await bot.download_file(file_info.file_path)
    return downloaded.read()


@dp.message(F.photo | (F.document & F.document.mime_type.startswith("image/")))
async def on_image_received(message: Message):
    """
    Обработка изображения:
    - Без приписки: удаление фона (PNG).
    - С припиской (/svg, /png, /jpeg): конвертация в нужный формат.
    Никаких лишних текстовых сообщений, только итоговый файл.
    """
    img_bytes = await extract_image_bytes(message)
    if not img_bytes:
        return

    caption = message.caption or ""
    target_format = detect_target_format(caption)

    try:
        if target_format:
            # Приписка есть -> делаем картинку в нужном формате
            out_bytes, filename, mime_type = await asyncio.to_thread(
                image_processor.convert_format,
                img_bytes,
                target_format
            )
        else:
            # Приписки нет -> удаляем фон
            out_bytes, filename, mime_type = await asyncio.to_thread(
                image_processor.process_image,
                img_bytes,
                "png",
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
async def on_reply_format(message: Message):
    """Ответ командой /svg, /png, /jpeg на ранее отправленное фото."""
    target_format = detect_target_format(message.text)
    if not target_format:
        return

    replied = message.reply_to_message
    img_bytes = await extract_image_bytes(replied)
    if not img_bytes:
        return

    try:
        out_bytes, filename, mime_type = await asyncio.to_thread(
            image_processor.convert_format,
            img_bytes,
            target_format
        )
        input_file = BufferedInputFile(out_bytes, filename=filename)

        if filename.endswith(".jpg") or filename.endswith(".jpeg"):
            await replied.answer_photo(photo=input_file)
        else:
            await replied.answer_document(document=input_file)
    except Exception as e:
        logger.exception("Ошибка при конвертации:")


async def main():
    logger.info("Запуск Telegram-бота...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
