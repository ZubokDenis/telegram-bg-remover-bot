"""
Модуль высококачественного удаления фона и конвертации изображений.
Использует нейросеть BRIA RMBG-2.0 / 1.4 через Hugging Face с бесшовным локальным фоллбэком.
"""

import os
import io
import time
import logging
import tempfile
from typing import Tuple, Optional
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

# Глобальные клиенты для повторного использования (ускоряет инференс)
_client_rmbg2 = None
_client_rmbg1 = None


def get_rmbg2_client(token: str):
    global _client_rmbg2
    if _client_rmbg2 is None:
        from gradio_client import Client
        _client_rmbg2 = Client("briaai/BRIA-RMBG-2.0", token=token)
    return _client_rmbg2


def get_rmbg1_client(token: str):
    global _client_rmbg1
    if _client_rmbg1 is None:
        from gradio_client import Client
        _client_rmbg1 = Client("briaai/BRIA-RMBG-1.4", token=token)
    return _client_rmbg1


def remove_background_neural(pil_image: Image.Image, token: str) -> Optional[Image.Image]:
    """
    Отправляет изображение в нейросеть RMBG-2.0 / RMBG-1.4 на Hugging Face.
    Возвращает изображение студийного качества с прозрачным фоном.
    """
    from gradio_client import handle_file

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        pil_image.save(tmp.name, format="PNG")
        tmp_path = tmp.name

    try:
        # 1. Сначала пробуем лучшую современную модель RMBG-2.0
        try:
            client2 = get_rmbg2_client(token)
            res = client2.predict(image=handle_file(tmp_path), api_name="/image")
            # res: (slider_tuple, filepath)
            out_file = res[1]
            if out_file and os.path.exists(out_file):
                return Image.open(out_file).convert("RGBA")
        except Exception as e:
            logger.warning(f"RMBG-2.0 ошибка: {e}. Пробуем RMBG-1.4...")

        # 2. Если RMBG-2.0 недоступен, пробуем стабильный RMBG-1.4
        try:
            client1 = get_rmbg1_client(token)
            res = client1.predict(image=handle_file(tmp_path), api_name="/run")
            out_file = res[1]
            if out_file and os.path.exists(out_file):
                return Image.open(out_file).convert("RGBA")
        except Exception as e:
            logger.warning(f"RMBG-1.4 ошибка: {e}")

    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass

    return None


def remove_background_local(
    pil_image: Image.Image,
    threshold: float = 38.0
) -> Image.Image:
    """
    Резервный локальный алгоритм удаления фона (на случай оффлайна или проблем с сетью):
    1. Находит фоновые цвета по 4 углам и строит билинейную плоскость фона.
    2. Вычисляет цветовое расстояние с учетом человеческого восприятия.
    3. Применяет Matte Choke (MinFilter) для срезки краевого ореола.
    """
    rgb = pil_image.convert("RGB")
    arr = np.array(rgb, dtype=np.float32)
    h, w, _ = arr.shape

    c_size = max(5, min(w, h) // 30)

    tl = np.median(arr[:c_size, :c_size].reshape(-1, 3), axis=0)
    tr = np.median(arr[:c_size, -c_size:].reshape(-1, 3), axis=0)
    bl = np.median(arr[-c_size:, :c_size].reshape(-1, 3), axis=0)
    br = np.median(arr[-c_size:, -c_size:].reshape(-1, 3), axis=0)

    u = np.linspace(0.0, 1.0, w, endpoint=True, dtype=np.float32).reshape(1, w, 1)
    v = np.linspace(0.0, 1.0, h, endpoint=True, dtype=np.float32).reshape(h, 1, 1)
    top_line = (1.0 - u) * tl + u * tr
    bot_line = (1.0 - u) * bl + u * br
    bg_plane = (1.0 - v) * top_line + v * bot_line

    diff = arr - bg_plane
    dist = np.sqrt(2.0 * diff[:, :, 0]**2 + 4.0 * diff[:, :, 1]**2 + 3.0 * diff[:, :, 2]**2)

    t_low = max(5.0, threshold - 6.0)
    t_high = threshold + 6.0
    alpha = np.clip((dist - t_low) / (t_high - t_low) * 255.0, 0, 255).astype(np.uint8)

    alpha_pil = Image.fromarray(alpha, mode="L")
    alpha_eroded = alpha_pil.filter(ImageFilter.MinFilter(3))
    alpha_final = alpha_eroded.filter(ImageFilter.GaussianBlur(0.6))

    result = rgb.copy()
    result.putalpha(alpha_final)
    return result


def remove_background(pil_image: Image.Image) -> Image.Image:
    """
    Главная функция вырезания фона:
    При наличии HF_TOKEN запускает нейросеть студийного качества,
    при сбое мягко переключается на локальный алгоритм.
    """
    if config.HF_TOKEN:
        try:
            res = remove_background_neural(pil_image, config.HF_TOKEN)
            if res is not None:
                return res
        except Exception as e:
            logger.warning(f"Ошибка нейросетевой обработки: {e}")

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
