"""
Модуль обработки изображений без использования нейросетей и внешних API.
Использует классические алгоритмы компьютерного зрения (OpenCV / NumPy / Pillow)
и библиотеку vtracer для быстрой векторизации в SVG.
"""

import io
import logging
from typing import Tuple, Optional
import numpy as np
from PIL import Image, ImageFilter

logger = logging.getLogger(__name__)

# Проверяем доступность OpenCV
try:
    import cv2
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False
    logger.warning("OpenCV не обнаружен, используется встроенный алгоритм на NumPy/Pillow")

# Проверяем доступность vtracer для SVG
try:
    import vtracer
    HAS_VTRACER = True
except ImportError:
    HAS_VTRACER = False
    logger.warning("vtracer не обнаружен, векторизация в SVG будет недоступна")


def is_uniform_border(img_rgb: np.ndarray, std_threshold: float = 24.0) -> bool:
    """
    Определяет, является ли фон по краям однородным (студийный фон, белый лист, хромакей).
    """
    h, w = img_rgb.shape[:2]
    top = img_rgb[0, :]
    bottom = img_rgb[-1, :]
    left = img_rgb[:, 0]
    right = img_rgb[:, -1]
    perimeter = np.concatenate([top, bottom, left, right], axis=0)
    std = float(np.mean(np.std(perimeter, axis=0)))
    return std < std_threshold


def remove_bg_floodfill_cv2(img_rgb: np.ndarray, tolerance: int = 25) -> np.ndarray:
    """
    Удаляет фон методом FloodFill по периметру с помощью OpenCV.
    Не затрагивает внутренние области объекта схожего цвета!
    """
    h, w = img_rgb.shape[:2]
    img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
    mask = np.zeros((h + 2, w + 2), np.uint8)

    # Точки заливки вдоль всех 4-х границ
    step = max(5, min(w, h) // 40)
    border_pts = []
    for x in range(0, w, step):
        border_pts.append((x, 0))
        border_pts.append((x, h - 1))
    for y in range(0, h, step):
        border_pts.append((0, y))
        border_pts.append((w - 1, y))

    copy_img = img_bgr.copy()
    diff = (tolerance, tolerance, tolerance)

    for pt in border_pts:
        if mask[pt[1] + 1, pt[0] + 1] == 0:
            cv2.floodFill(
                copy_img,
                mask,
                pt,
                0,
                diff,
                diff,
                cv2.FLOODFILL_MASK_ONLY | (255 << 8)
            )

    # 0 = объект, 255 = фон
    bg_mask = mask[1:-1, 1:-1]
    alpha = 255 - bg_mask
    return alpha


def remove_bg_grabcut_cv2(img_rgb: np.ndarray, margin_percent: float = 0.05, iterations: int = 4) -> np.ndarray:
    """
    Классическая сегментация GrabCut (OpenCV) для фото со сложным фоном.
    Не использует нейросети, основана на гауссовых моделях цветов и минимальных разрезах графов.
    """
    h, w = img_rgb.shape[:2]
    img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)

    mask = np.zeros((h, w), np.uint8)
    bgd_model = np.zeros((1, 65), np.float64)
    fgd_model = np.zeros((1, 65), np.float64)

    # Прямоугольник предполагаемого объекта с небольшим отступом от краев
    mx = max(2, int(w * margin_percent))
    my = max(2, int(h * margin_percent))
    rect = (mx, my, max(1, w - 2 * mx), max(1, h - 2 * my))

    cv2.grabCut(img_bgr, mask, rect, bgd_model, fgd_model, iterations, cv2.GC_INIT_WITH_RECT)

    # Выделяем пиксели переднего плана
    fg_mask = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    return fg_mask


def remove_bg_numpy(img_rgb: np.ndarray, tolerance: int = 30) -> np.ndarray:
    """
    Резервный алгоритм на чистом NumPy (если OpenCV отсутствует).
    Находит цвет фона по периметру и удаляет его по дистанции в цветовом пространстве.
    """
    h, w = img_rgb.shape[:2]
    top = img_rgb[0, :]
    bottom = img_rgb[-1, :]
    left = img_rgb[:, 0]
    right = img_rgb[:, -1]
    perimeter = np.concatenate([top, bottom, left, right], axis=0)
    bg_color = np.median(perimeter, axis=0)

    diff = np.linalg.norm(img_rgb.astype(np.float32) - bg_color.astype(np.float32), axis=-1)
    alpha = np.where(diff > tolerance, 255, 0).astype(np.uint8)
    return alpha


def remove_background(
    pil_image: Image.Image,
    mode: str = "auto",
    tolerance: int = 25,
    feather_radius: float = 1.5
) -> Image.Image:
    """
    Удаляет фон с изображения классическими методами.
    mode:
      - 'auto': автоопределение (floodfill для однородного, grabcut для сложного)
      - 'floodfill' / 'color': для студийных/однородных фонов, товаров, логотипов
      - 'grabcut': алгоритм GrabCut для обычных фотографий
    """
    img_rgb = pil_image.convert("RGB")
    arr = np.array(img_rgb)

    if HAS_OPENCV:
        if mode == "auto":
            if is_uniform_border(arr):
                alpha_mask = remove_bg_floodfill_cv2(arr, tolerance=tolerance)
            else:
                alpha_mask = remove_bg_grabcut_cv2(arr, iterations=4)
        elif mode in ("floodfill", "color"):
            alpha_mask = remove_bg_floodfill_cv2(arr, tolerance=tolerance)
        elif mode == "grabcut":
            alpha_mask = remove_bg_grabcut_cv2(arr, iterations=4)
        else:
            alpha_mask = remove_bg_floodfill_cv2(arr, tolerance=tolerance)
    else:
        alpha_mask = remove_bg_numpy(arr, tolerance=tolerance)

    # Сглаживание краев (feathering) для мягкого аккуратного контура
    mask_pil = Image.fromarray(alpha_mask, mode="L")
    if feather_radius > 0:
        mask_pil = mask_pil.filter(ImageFilter.GaussianBlur(feather_radius))

    result = img_rgb.copy()
    result.putalpha(mask_pil)
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
    """
    Сохраняет изображение в JPEG.
    Так как JPEG не поддерживает прозрачность, вырезанный объект
    накладывается на чистый фон (по умолчанию белый).
    """
    bg = Image.new("RGB", rgba_img.size, bg_color)
    bg.paste(rgba_img, (0, 0), rgba_img)
    buf = io.BytesIO()
    bg.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def to_svg_bytes(rgba_img: Image.Image) -> bytes:
    """
    Векторизует вырезанное растровое изображение в масштабируемый векторный SVG
    с помощью vtracer (без потери качества при масштабировании).
    """
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
    Главная функция обработки:
    1. Загружает изображение из байтов.
    2. Удаляет фон без ИИ.
    3. Конвертирует в запрошенный формат ('png', 'jpeg', 'svg').
    Возвращает: (output_bytes, filename, mime_type)
    """
    input_img = Image.open(io.BytesIO(image_bytes))

    # Ограничиваем максимальный размер для оптимизации скорости
    max_dim = 1600
    if max(input_img.size) > max_dim:
        input_img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

    # Удаляем фон
    rgba_result = remove_background(input_img, mode=mode)

    fmt = target_format.lower().strip().lstrip("/")
    if fmt in ("jpg", "jpeg"):
        out_bytes = to_jpeg_bytes(rgba_result)
        return out_bytes, "no_bg.jpg", "image/jpeg"
    elif fmt == "svg":
        out_bytes = to_svg_bytes(rgba_result)
        return out_bytes, "no_bg.svg", "image/svg+xml"
    else:  # по умолчанию PNG
        out_bytes = to_png_bytes(rgba_result)
        return out_bytes, "no_bg.png", "image/png"


def convert_format(
    image_bytes: bytes,
    target_format: str
) -> Tuple[bytes, str, str]:
    """
    Конвертирует исходное изображение в запрошенный формат (svg, png, jpeg) БЕЗ удаления фона.
    """
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
    else:  # png
        buf = io.BytesIO()
        input_img.save(buf, format="PNG")
        return buf.getvalue(), "image.png", "image/png"

