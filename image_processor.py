"""
Модуль надежного и быстрого удаления фона и конвертации в PNG, SVG, JPEG.
Работает на чистом Pillow/NumPy без перегруженных библиотек и тяжелых моделей.
"""

import os
import io
import logging
from typing import Tuple, Optional
import numpy as np
from PIL import Image, ImageFilter

logger = logging.getLogger(__name__)

# Проверяем доступность vtracer для векторизации в SVG
try:
    import vtracer
    HAS_VTRACER = True
except ImportError:
    HAS_VTRACER = False
    logger.warning("vtracer не обнаружен, векторизация SVG будет недоступна")


def remove_background(
    pil_image: Image.Image,
    threshold: float = 24.0,
    feather_radius: float = 1.0
) -> Image.Image:
    """
    Удаляет фон с изображения:
    1. Находит фоновый цвет по угловым областям.
    2. Вычисляет взвешенное цветовое расстояние (с учетом чувствительности человеческого глаза).
    3. Формирует плавный альфа-канал с мягким сглаживанием краев.
    Сохраняет 100% деталей объекта (ствол, ветки, листья) и полностью удаляет фон.
    """
    rgb = pil_image.convert("RGB")
    arr = np.array(rgb, dtype=np.float32)
    h, w, _ = arr.shape

    # Угловые области (размером примерно 3-5% от картинки)
    c_size = max(5, min(w, h) // 30)
    c1 = arr[:c_size, :c_size].reshape(-1, 3)
    c2 = arr[:c_size, -c_size:].reshape(-1, 3)
    c3 = arr[-c_size:, :c_size].reshape(-1, 3)
    c4 = arr[-c_size:, -c_size:].reshape(-1, 3)
    corners = np.concatenate([c1, c2, c3, c4], axis=0)

    # Определяем медианный цвет фона
    bg_color = np.median(corners, axis=0)

    # Взвешенное цветовое расстояние (человеческий глаз наиболее чувствителен к зеленому, затем к красному, затем к синему)
    dr = arr[:, :, 0] - bg_color[0]
    dg = arr[:, :, 1] - bg_color[1]
    db = arr[:, :, 2] - bg_color[2]
    dist = np.sqrt(2.0 * dr**2 + 4.0 * dg**2 + 3.0 * db**2)

    # Плавная граница перехода (soft alpha)
    t_low = max(4.0, threshold - 8.0)
    t_high = threshold + 8.0
    alpha = np.clip((dist - t_low) / (t_high - t_low) * 255.0, 0, 255).astype(np.uint8)

    # Сглаживание краев
    alpha_pil = Image.fromarray(alpha, mode="L")
    if feather_radius > 0:
        alpha_pil = alpha_pil.filter(ImageFilter.GaussianBlur(feather_radius))

    result = rgb.copy()
    result.putalpha(alpha_pil)
    return result


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
