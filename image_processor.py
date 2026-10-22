"""
Модуль надежного и быстрого удаления фона и конвертации в PNG, SVG, JPEG.
Работает на чистом Pillow/NumPy без перегруженных библиотек и тяжелых моделей.
"""

import os
import io
import time
import logging
from typing import Tuple, Optional
import requests
import numpy as np
from PIL import Image, ImageFilter

import config

logger = logging.getLogger(__name__)

# Проверяем доступность vtracer для векторизации в SVG
try:
    import vtracer
    HAS_VTRACER = True
except ImportError:
    HAS_VTRACER = False
    logger.warning("vtracer не обнаружен, векторизация SVG будет недоступна")


def remove_background_hf(image_bytes: bytes, token: str) -> Optional[Image.Image]:
    """
    Отправляет изображение в официальный бесплатный Serverless-эндпоинт модели briaai/RMBG-1.4 на Hugging Face.
    Возвращает изображение высочайшего студийного качества с прозрачным альфа-каналом.
    """
    urls = [
        "https://router.huggingface.co/hf-inference/models/briaai/RMBG-1.4",
        "https://api-inference.huggingface.co/models/briaai/RMBG-1.4",
    ]
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/octet-stream",
    }

    for url in urls:
        try:
            r = requests.post(url, headers=headers, data=image_bytes, timeout=30)
            if r.status_code == 200:
                return Image.open(io.BytesIO(r.content)).convert("RGBA")
            elif r.status_code == 503:
                # Если модель на сервере Hugging Face прогревается (cold start)
                time.sleep(2)
                r = requests.post(url, headers=headers, data=image_bytes, timeout=30)
                if r.status_code == 200:
                    return Image.open(io.BytesIO(r.content)).convert("RGBA")
            else:
                logger.warning(f"Hugging Face ({url}) статус {r.status_code}: {r.text[:200]}")
        except Exception as e:
            logger.warning(f"Ошибка запроса к {url}: {e}")

    return None


def remove_background_local(
    pil_image: Image.Image,
    threshold: float = 38.0
) -> Image.Image:
    """
    Удаляет фон с изображения:
    1. Находит фоновые цвета по 4 углам и строит билинейную плоскость градиента фона.
    2. Вычисляет взвешенное цветовое расстояние (человеческое восприятие).
    3. Применяет алгоритм Matte Choke (MinFilter) для полного удаления краевого ореола.
    4. Делает микросглаживание контура.
    """
    rgb = pil_image.convert("RGB")
    arr = np.array(rgb, dtype=np.float32)
    h, w, _ = arr.shape

    # Угловые области (размером примерно 3-5% от картинки)
    c_size = max(5, min(w, h) // 30)

    tl = np.median(arr[:c_size, :c_size].reshape(-1, 3), axis=0)
    tr = np.median(arr[:c_size, -c_size:].reshape(-1, 3), axis=0)
    bl = np.median(arr[-c_size:, :c_size].reshape(-1, 3), axis=0)
    br = np.median(arr[-c_size:, -c_size:].reshape(-1, 3), axis=0)

    # Билинейная плоскость фона (компенсирует градиенты, тени и виньетирование)
    u = np.linspace(0.0, 1.0, w, endpoint=True, dtype=np.float32).reshape(1, w, 1)
    v = np.linspace(0.0, 1.0, h, endpoint=True, dtype=np.float32).reshape(h, 1, 1)
    top_line = (1.0 - u) * tl + u * tr
    bot_line = (1.0 - u) * bl + u * br
    bg_plane = (1.0 - v) * top_line + v * bot_line

    # Взвешенное цветовое расстояние
    diff = arr - bg_plane
    dist = np.sqrt(2.0 * diff[:, :, 0]**2 + 4.0 * diff[:, :, 1]**2 + 3.0 * diff[:, :, 2]**2)

    # Крутой и четкий порог
    t_low = max(5.0, threshold - 6.0)
    t_high = threshold + 6.0
    alpha = np.clip((dist - t_low) / (t_high - t_low) * 255.0, 0, 255).astype(np.uint8)

    # Убираем ореол и краевую кайму (Matte Choke)
    alpha_pil = Image.fromarray(alpha, mode="L")
    alpha_eroded = alpha_pil.filter(ImageFilter.MinFilter(3))

    # Микросглаживание контура (0.6px)
    alpha_final = alpha_eroded.filter(ImageFilter.GaussianBlur(0.6))

    result = rgb.copy()
    result.putalpha(alpha_final)
    return result


def remove_background(pil_image: Image.Image) -> Image.Image:
    """
    Главная функция вырезания фона:
    1. Если задан HF_TOKEN, использует передовую нейросеть briaai/RMBG-1.4 (студийное качество 10/10).
    2. В случае отсутствия токена или сетевой ошибки бесшовно переключается на локальный алгоритм.
    """
    if config.HF_TOKEN:
        try:
            buf = io.BytesIO()
            pil_image.save(buf, format="PNG")
            hf_res = remove_background_hf(buf.getvalue(), config.HF_TOKEN)
            if hf_res is not None:
                return hf_res
        except Exception as e:
            logger.warning(f"Ошибка при вызове нейросети RMBG: {e}")

    return remove_background_local(pil_image)



def to_png_bytes(rgba_img: Image.Image) -> bytes:
    """Сохраняет RGBA изображение в формат PNG с поддержкой прозрачности."""
    buf = io.BytesIO()
    rgba_img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def to_jpeg_bytes(
    rgba_img: Image.Image,
    bg_color: Tuple[int, int, int] = (255, 255, 255),
    quality: int = 95
) -> bytes:
    """Сохраняет изображение в JPEG на чистом белом фоне."""
    bg = Image.new("RGB", rgba_img.size, bg_color)
    bg.paste(rgba_img, (0, 0), rgba_img)
    buf = io.BytesIO()
    bg.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def to_svg_bytes(rgba_img: Image.Image) -> bytes:
    """Векторизует вырезанное растровое изображение в масштабируемый векторный SVG."""
    if not HAS_VTRACER:
        raise RuntimeError("Модуль vtracer не установлен, создание SVG невозможно.")

    png_data = to_png_bytes(rgba_img)
    svg_str = vtracer.convert_raw_image_to_svg(
        png_data,
        img_format="png",
        colormode="color",
        hierarchical="stacked",
        mode="spline",
        filter_speckle=4,
        color_precision=6,
        layer_difference=16,
    )
    return svg_str.encode("utf-8")


def process_image(
    image_bytes: bytes,
    target_format: str = "png",
    mode: str = "auto"
) -> Tuple[bytes, str, str]:
    """
    Вырезает фон и сохраняет в запрошенном формате:
    - png: прозрачный фон
    - svg: векторный SVG
    - jpeg: чистый белый фон
    """
    input_img = Image.open(io.BytesIO(image_bytes))

    max_dim = 1600
    if max(input_img.size) > max_dim:
        input_img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

    rgba_result = remove_background(input_img)

    fmt = target_format.lower().strip().lstrip("/")
    if fmt in ("jpg", "jpeg"):
        out_bytes = to_jpeg_bytes(rgba_result)
        return out_bytes, "no_bg.jpg", "image/jpeg"
    elif fmt == "svg":
        out_bytes = to_svg_bytes(rgba_result)
        return out_bytes, "no_bg.svg", "image/svg+xml"
    else:
        out_bytes = to_png_bytes(rgba_result)
        return out_bytes, "no_bg.png", "image/png"


def convert_format(
    image_bytes: bytes,
    target_format: str
) -> Tuple[bytes, str, str]:
    """Конвертирует исходное изображение без вырезания фона."""
    input_img = Image.open(io.BytesIO(image_bytes))
    fmt = target_format.lower().strip().lstrip("/")

    if fmt == "svg":
        if not HAS_VTRACER:
            raise RuntimeError("vtracer не установлен для векторизации SVG.")
        buf = io.BytesIO()
        input_img.save(buf, format="PNG")
        svg_str = vtracer.convert_raw_image_to_svg(
            buf.getvalue(),
            img_format="png",
            colormode="color",
            hierarchical="stacked",
            mode="spline",
            filter_speckle=4,
            color_precision=6,
            layer_difference=16,
        )
        return svg_str.encode("utf-8"), "image.svg", "image/svg+xml"
    elif fmt in ("jpg", "jpeg"):
        rgb = input_img.convert("RGB")
        buf = io.BytesIO()
        rgb.save(buf, format="JPEG", quality=95)
        return buf.getvalue(), "image.jpg", "image/jpeg"
    else:
        buf = io.BytesIO()
        input_img.save(buf, format="PNG")
        return buf.getvalue(), "image.png", "image/png"
