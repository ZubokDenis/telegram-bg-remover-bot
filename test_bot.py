"""
Тест проверки работы модулей бота и алгоритмов вырезания фона.
"""

import io
import unittest
from PIL import Image, ImageDraw
import image_processor


class TestImageProcessor(unittest.TestCase):
    def setUp(self):
        # Создаем тестовое изображение: белый фон с цветным кругом
        self.img = Image.new("RGB", (200, 200), (255, 255, 255))
        d = ImageDraw.Draw(self.img)
        d.ellipse([40, 40, 160, 160], fill=(220, 50, 50))
        d.rectangle([80, 80, 120, 120], fill=(255, 255, 255))  # белая область внутри

        buf = io.BytesIO()
        self.img.save(buf, format="PNG")
        self.raw_bytes = buf.getvalue()

    def test_png_conversion(self):
        out_bytes, filename, mime = image_processor.process_image(self.raw_bytes, "png")
        self.assertEqual(filename, "no_bg.png")
        self.assertEqual(mime, "image/png")
        self.assertGreater(len(out_bytes), 0)

        # Проверяем, что результат открывается и имеет альфа-канал
        result_img = Image.open(io.BytesIO(out_bytes))
        self.assertEqual(result_img.mode, "RGBA")

    def test_jpeg_conversion(self):
        out_bytes, filename, mime = image_processor.process_image(self.raw_bytes, "jpeg")
        self.assertEqual(filename, "no_bg.jpg")
        self.assertEqual(mime, "image/jpeg")
        self.assertGreater(len(out_bytes), 0)

        result_img = Image.open(io.BytesIO(out_bytes))
        self.assertEqual(result_img.mode, "RGB")

    def test_svg_conversion(self):
        out_bytes, filename, mime = image_processor.process_image(self.raw_bytes, "svg")
        self.assertEqual(filename, "no_bg.svg")
        self.assertEqual(mime, "image/svg+xml")
        self.assertGreater(len(out_bytes), 0)

        svg_text = out_bytes.decode("utf-8")
        self.assertIn("<svg", svg_text)


if __name__ == "__main__":
    unittest.main()
