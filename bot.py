"""
Основной модуль Telegram-бота для удаления фона и конвертации форматов.
Работает как в режиме локального запуска (Polling), так и через Webhook на Vercel.
"""

import asyncio
import io
import logging
from typing import Optional, Tuple
from collections import OrderedDict

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    BufferedInputFile,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

import config
import image_processor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("tg_bg_bot")

# Инициализируем бота и диспетчер
DUMMY_TOKEN = "123456789:AAG_DUMMY_TOKEN_FOR_IMPORT_ONLY_1234567"
bot = Bot(token=config.BOT_TOKEN if config.BOT_TOKEN else DUMMY_TOKEN)
dp = Dispatcher()

# Простое LRU-кэширование исходных байтов изображений в памяти для быстрых переключений формата
# ключ: file_unique_id, значение: image_bytes
class SimpleLRUCache:
    def __init__(self, capacity: int = 50):
        self.cache: OrderedDict[str, bytes] = OrderedDict()
        self.capacity = capacity

    def get(self, key: str) -> Optional[bytes]:
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        return None

    def set(self, key: str, value: bytes):
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        if len(self.cache) > self.capacity:
            self.cache.popitem(last=False)

image_cache = SimpleLRUCache(capacity=50)

# Хранилище режима для пользователей: user_id -> mode ('auto', 'floodfill', 'grabcut')
user_modes: dict[int, str] = {}


def get_format_keyboard(file_uid: str) -> InlineKeyboardMarkup:
    """Генерирует инлайн-кнопки для быстрой смены формата изображения."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🖼 Скачать PNG", callback_data=f"fmt:png:{file_uid}"),
                InlineKeyboardButton(text="📐 Скачать SVG", callback_data=f"fmt:svg:{file_uid}"),
                InlineKeyboardButton(text="🎨 Скачать JPEG", callback_data=f"fmt:jpeg:{file_uid}"),
            ]
        ]
    )


def detect_target_format(text: Optional[str]) -> str:
    """Определяет желаемый формат из подписи или команды."""
    if not text:
        return "png"
    text_lower = text.lower()
    if "/svg" in text_lower or "svg" in text_lower:
        return "svg"
    elif "/jpeg" in text_lower or "jpeg" in text_lower or "/jpg" in text_lower or "jpg" in text_lower:
        return "jpeg"
    elif "/png" in text_lower or "png" in text_lower:
        return "png"
    return "png"


@dp.message(CommandStart())
async def cmd_start(message: Message):
    """Приветственное сообщение."""
    text = (
        "👋 **Привет! Я бот для удаления фона без использования сторонних платных API и ИИ.**\n\n"
        "✨ **Как со мной работать:**\n"
        "1. Просто отправь мне любое фото или картинку.\n"
        "2. Я аккуратно вырежу фон и пришлю результат в высоком качестве.\n\n"
        "🎯 **Выбор формата:**\n"
        "При отправке фото добавь в подпись нужный формат:\n"
        "• `/png` — прозрачный фон (по умолчанию)\n"
        "• `/svg` — масштабируемый векторный формат\n"
        "• `/jpeg` — на чистом белом фоне\n\n"
        "💡 Также под каждым результатом будут кнопки для мгновенного скачивания в других форматах!\n\n"
        "⚙️ `/mode` — переключение алгоритма (Авто / Студийный фон / Сложное фото)"
    )
    await message.answer(text, parse_mode="Markdown")


@dp.message(Command("help"))
async def cmd_help(message: Message):
    """Справка по боту."""
    text = (
        "ℹ️ **Справка по командам:**\n\n"
        "• Пришли картинку с подписью `/svg`, `/png` или `/jpeg`.\n"
        "• Либо ответь командой `/svg` на уже отправленное ранее фото.\n"
        "• `/mode` — выбрать метод удаления фона (Авто / FloodFill / GrabCut).\n"
        "• `/ping` — проверка отклика бота."
    )
    await message.answer(text, parse_mode="Markdown")


@dp.message(Command("ping"))
async def cmd_ping(message: Message):
    await message.answer("🏓 Понг! Бот активен и готов к работе.")


@dp.message(Command("mode"))
async def cmd_mode(message: Message):
    """Настройка алгоритма обработки."""
    user_id = message.from_user.id if message.from_user else 0
    current_mode = user_modes.get(user_id, config.DEFAULT_MODE)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{'✅ ' if current_mode == 'auto' else ''}🤖 Авто (рекомендуется)",
                    callback_data="set_mode:auto"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{'✅ ' if current_mode == 'floodfill' else ''}🧼 Однородный / Студийный фон (FloodFill)",
                    callback_data="set_mode:floodfill"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{'✅ ' if current_mode == 'grabcut' else ''}📸 Сложное фото с фоном (GrabCut)",
                    callback_data="set_mode:grabcut"
                )
            ],
        ]
    )
    await message.answer(
        f"⚙️ **Текущий алгоритм:** `{current_mode}`\n\n"
        "Выберите желаемый метод:",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )


@dp.callback_query(F.data.startswith("set_mode:"))
async def callback_set_mode(query: CallbackQuery):
    """Обработка переключения режима алгоритма."""
    new_mode = query.data.split(":")[1]
    user_id = query.from_user.id
    user_modes[user_id] = new_mode

    await query.answer(f"Режим изменен на: {new_mode}")
    if query.message:
        await query.message.edit_text(
            f"✅ **Режим успешно обновлен на:** `{new_mode}`\n\n"
            "Теперь отправьте фото для обработки.",
            parse_mode="Markdown"
        )


async def extract_image_bytes(message: Message) -> Optional[Tuple[bytes, str, str]]:
    """
    Извлекает байты изображения из сообщения (фото или документ).
    Возвращает (image_bytes, file_id, file_unique_id) или None.
    """
    file_id = None
    file_uid = None

    if message.photo:
        photo = message.photo[-1]
        file_id = photo.file_id
        file_uid = photo.file_unique_id
    elif message.document and message.document.mime_type and message.document.mime_type.startswith("image/"):
        file_id = message.document.file_id
        file_uid = message.document.file_unique_id

    if not file_id or not file_uid:
        return None

    # Проверяем кэш
    cached = image_cache.get(file_uid)
    if cached:
        return cached, file_id, file_uid

    # Скачиваем из Telegram
    file_info = await bot.get_file(file_id)
    if not file_info.file_path:
        return None

    downloaded = await bot.download_file(file_info.file_path)
    img_bytes = downloaded.read()
    image_cache.set(file_uid, img_bytes)
    return img_bytes, file_id, file_uid


async def handle_image_processing(message: Message, target_format: str):
    """Общий обработчик логики вырезания фона и отправки файла."""
    data = await extract_image_bytes(message)
    if not data:
        await message.answer("❌ Не удалось получить изображение. Пожалуйста, отправьте фото.")
        return

    raw_bytes, file_id, file_uid = data
    user_id = message.from_user.id if message.from_user else 0
    mode = user_modes.get(user_id, config.DEFAULT_MODE)

    # Индикация действия бота
    await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_DOCUMENT)
    status_msg = await message.answer("✂️ Удаляю фон и генерирую формат, секунду...")

    try:
        # Выполняем ресурсоемкую обработку в отдельном потоке
        out_bytes, filename, mime_type = await asyncio.to_thread(
            image_processor.process_image,
            raw_bytes,
            target_format,
            mode
        )

        input_file = BufferedInputFile(out_bytes, filename=filename)
        keyboard = get_format_keyboard(file_uid)

        caption = f"✅ Готово! Формат: **{target_format.upper()}** (алгоритм: `{mode}`)"

        # Для PNG и SVG отправляем как документ, чтобы Telegram не сжимал и не терял прозрачность/вектор
        if target_format in ("png", "svg"):
            await message.answer_document(
                document=input_file,
                caption=caption,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        else:
            # Для JPEG можно отправить как фото
            await message.answer_photo(
                photo=input_file,
                caption=caption,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )

        # Удаляем сообщение со статусом
        try:
            await status_msg.delete()
        except Exception:
            pass

    except Exception as e:
        logger.exception("Ошибка при обработке изображения:")
        await status_msg.edit_text(f"❌ Произошла ошибка при обработке: {e}")


@dp.message(F.photo | (F.document & F.document.mime_type.startswith("image/")))
async def on_photo_received(message: Message):
    """Срабатывает при отправке фото или изображения в виде документа."""
    caption = message.caption or ""
    target_format = detect_target_format(caption)
    await handle_image_processing(message, target_format)


@dp.message(F.reply_to_message & (F.text.startswith("/") | F.text.in_({"svg", "png", "jpeg", "jpg"})))
async def on_reply_format(message: Message):
    """Срабатывает, если пользователь ответил командой (например /svg) на предыдущее фото."""
    replied = message.reply_to_message
    if not (replied.photo or (replied.document and replied.document.mime_type and replied.document.mime_type.startswith("image/"))):
        return

    target_format = detect_target_format(message.text)
    await handle_image_processing(replied, target_format)


@dp.callback_query(F.data.startswith("fmt:"))
async def on_format_callback(query: CallbackQuery):
    """Обработка нажатий инлайн-кнопок форматов."""
    parts = query.data.split(":")
    if len(parts) < 3:
        await query.answer("Неверные данные.")
        return

    target_format = parts[1]
    file_uid = parts[2]

    # Достаем байты из кэша
    raw_bytes = image_cache.get(file_uid)
    if not raw_bytes:
        await query.answer(
            "⏳ Срок действия кэша истек. Пожалуйста, отправьте фото еще раз.",
            show_alert=True
        )
        return

    await query.answer(f"Генерирую {target_format.upper()}...")
    user_id = query.from_user.id
    mode = user_modes.get(user_id, config.DEFAULT_MODE)

    if query.message:
        await bot.send_chat_action(query.message.chat.id, ChatAction.UPLOAD_DOCUMENT)

    try:
        out_bytes, filename, mime_type = await asyncio.to_thread(
            image_processor.process_image,
            raw_bytes,
            target_format,
            mode
        )
        input_file = BufferedInputFile(out_bytes, filename=filename)
        keyboard = get_format_keyboard(file_uid)
        caption = f"✅ Формат: **{target_format.upper()}** (алгоритм: `{mode}`)"

        if target_format in ("png", "svg"):
            await query.message.answer_document(
                document=input_file,
                caption=caption,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        else:
            await query.message.answer_photo(
                photo=input_file,
                caption=caption,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.exception("Ошибка при конвертации из callback:")
        await query.message.answer(f"❌ Ошибка при формировании {target_format.upper()}: {e}")


async def main():
    """Запуск бота локально в режиме опроса (Long Polling)."""
    if not config.BOT_TOKEN or config.BOT_TOKEN == DUMMY_TOKEN:
        print("\n" + "=" * 60)
        print("ОШИБКА: Токен бота не установлен!")
        print("Создайте бота через @BotFather в Telegram, скопируйте токен")
        print("и укажите его в файле .env: BOT_TOKEN=ваш_токен")
        print("=" * 60 + "\n")
        return

    logger.info("Запуск Telegram-бота в режиме Long Polling...")
    # Удаляем вебхук при локальном запуске, чтобы не конфликтовать
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
