"""
Модуль качественного удаления фона и конвертации форматов (PNG, SVG, JPEG).
Использует встроенную локальную модель u2netp (rembg) без необходимости скачивания из сети.
"""

import os
import io
import logging
from typing import Tuple, Optional
import numpy as np
from PIL import Image, ImageFilter

logger = logging.getLogger(__name__)

# Пути к локальным моделям внутри проекта
current_dir = os.path.dirname(os.path.abspath(__file__))
models_dir = os.path.join(current_dir, "models")

# Настраиваем пути поиска для rembg
os.environ["U2NET_HOME"] = models_dir
os.environ["REMBG_HOME"] = os.path.join(os.environ.get("TMPDIR", "/tmp"), "rembg")

# Глобальная переменная для сессии rembg
_REMBG_SESSION = None
_REMBG_INITIALIZED = False

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


def get_rembg_session():
    """Ленивая загрузка сессии rembg из локального файла u2netp.onnx."""
    global _REMBG_SESSION, _REMBG_INITIALIZED
    if _REMBG_INITIALIZED:
        return _REMBG_SESSION

    _REMBG_INITIALIZED = True
    try:
        import rembg
        # Убеждаемся, что U2NET_HOME указывает на локальную папку models
        os.environ["U2NET_HOME"] = models_dir
        _REMBG_SESSION = rembg.new_session("u2netp")
        logger.info("Локальная модель u2netp успешно загружена")
    except Exception as e:
        logger.exception(f"Не удалось загрузить модель rembg: {e}")
        _REMBG_SESSION = None

    return _REMBG_SESSION


def remove_bg_cielab(img_pil: Image.Image, threshold: float = 24.0, feather: float = 1.5) -> Image.Image:
    """
    Резервное удаление фона по цветовому расстоянию в пространстве CIELAB.
    """
    rgb = img_pil.convert("RGB")
    arr = np.array(rgb)
    h, w, _ = arr.shape

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
    Удаляет фон с изображения.
    Использует локальную модель u2netp (rembg) с откатом к CIELAB.
    """
    session = get_rembg_session()
    if session is not None:
        try:
            import rembg
            return rembg.remove(pil_image, session=session)
        except Exception as e:
            logger.exception(f"Ошибка при работе rembg: {e}")

    logger.warning("Используется резервный алгоритм CIELAB")
    return remove_bg_cielab(pil_image)


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
