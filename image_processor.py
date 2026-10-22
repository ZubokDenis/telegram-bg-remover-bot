"""
Модуль качественного удаления фона и конвертации форматов (PNG, SVG, JPEG).
Использует высокоточную легковесную модель u2netp (rembg) с плавным откатом
к колориметрическому алгоритму CIELAB при необходимости.
"""

import os
import io
import logging
from typing import Tuple, Optional
import numpy as np
from PIL import Image, ImageFilter

logger = logging.getLogger(__name__)

# Для Serverless-сред (Vercel) настраиваем сохранение моделей в доступную для записи папку /tmp
os.environ["U2NET_HOME"] = os.path.join(os.environ.get("TMPDIR", "/tmp"), ".u2net")

# Инициализируем rembg
HAS_REMBG = False
REMBG_SESSION = None

try:
    import rembg
    REMBG_SESSION = rembg.new_session("u2netp")
    HAS_REMBG = True
    logger.info("Модель u2netp (rembg) успешно инициализирована")
except Exception as e:
    logger.warning(f"rembg не загружен, будет использован колориметрический алгоритм: {e}")

# Проверяем доступность OpenCV
try:
    import cv2
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False

# Проверяем доступность vtracer для SVG
try:
    import vtracer
    HAS_VTRACER = True
except ImportError:
    HAS_VTRACER = False


def remove_bg_cielab(img_pil: Image.Image, threshold: float = 24.0, feather: float = 1.5) -> Image.Image:
    """
    Качественное удаление однородного/градиентного фона в цветовом пространстве CIELAB.
    Определяет фон по углам изображения и удаляет его со всех пустот между ветками и деталями.
    """
    rgb = img_pil.convert("RGB")
    arr = np.array(rgb)
    h, w, _ = arr.shape

    # 4 угловых патча для определения фонового цвета
    p_size = max(3, min(w, h) // 40)
    patches = [
        arr[:p_size, :p_size],
        arr[:p_size, -p_size:],
        arr[-p_size:, :p_size],
        arr[-p_size:, -p_size:]
    ]
    border_pixels = np.concatenate([p.reshape(-1, 3) for p in patches], axis=0)

    if HAS_OPENCV:
        lab = cv2.cvtColor(arr, cv2.COLOR_RGB2LAB).astype(np.float32)
        border_lab = cv2.cvtColor(border_pixels.reshape(1, -1, 3), cv2.COLOR_RGB2LAB).reshape(-1, 3).astype(np.float32)
        bg_lab = np.median(border_lab, axis=0)
        delta_e = np.linalg.norm(lab - bg_lab, axis=-1)
    else:
        bg_rgb = np.median(border_pixels, axis=0)
        delta_e = np.linalg.norm(arr.astype(np.float32) - bg_rgb.astype(np.float32), axis=-1)

    t_low = max(4.0, threshold - 5.0)
    t_high = threshold + 5.0
    alpha = np.clip((delta_e - t_low) / (t_high - t_low) * 255.0, 0, 255).astype(np.uint8)

    alpha_pil = Image.fromarray(alpha, mode="L")
    if feather > 0:
        alpha_pil = alpha_pil.filter(ImageFilter.GaussianBlur(feather))

    result = rgb.copy()
    result.putalpha(alpha_pil)
    return result


def remove_background(pil_image: Image.Image) -> Image.Image:
    """
    Главная функция вырезания фона.
    В первую очередь использует специализированную модель сегментации (rembg),
    которая безошибочно вырезает ветки, листья, корни, волосы и сложные контуры.
    """
    global HAS_REMBG, REMBG_SESSION

    if HAS_REMBG and REMBG_SESSION:
        try:
            return rembg.remove(pil_image, session=REMBG_SESSION)
        except Exception as e:
            logger.exception("Ошибка rembg, переключаюсь на CIELAB:")

    return remove_bg_cielab(pil_image)


def to_png_bytes(rgba_img: Image.Image) -> bytes:
    """Сохраняет RGBA изображение в формат PNG с прозрачностью."""
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
    """Векторизует вырезанное растровое изображение в масштабируемый SVG."""
    if not HAS_VTRACER:
        raise RuntimeError("vtracer не установлен для векторизации SVG.")

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
    - svg: векторный силуэт
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
