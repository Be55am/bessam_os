import time
from typing import List, Tuple

import board
import busio
import adafruit_ssd1306
from PIL import Image, ImageDraw

from src.utils.fonts import get_font
from src.utils.text import wrap_text


class OledDisplay:
    def __init__(self) -> None:
        i2c = busio.I2C(board.SCL, board.SDA)
        display = None
        for addr in (0x3C, 0x3D):
            try:
                display = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c, addr=addr)
                break
            except Exception:
                continue
        if display is None:
            raise RuntimeError("OLED not found on I2C (0x3C/0x3D)")
        self._display = display
        self.width = display.width
        self.height = display.height

    def clear(self) -> None:
        self._display.fill(0)
        self._display.show()

    def new_image(self) -> Image.Image:
        return Image.new("1", (self.width, self.height))

    def show_image(self, image: Image.Image) -> None:
        self._display.image(image)
        self._display.show()

    def draw_text(self, text: str, bold: bool = False) -> None:
        image = self.new_image()
        draw = ImageDraw.Draw(image)
        font = get_font(11, bold=bold)
        lines = wrap_text(text, max_chars=20)
        y = 0
        for line in lines[:6]:
            draw.text((2, y), line, font=font, fill=255)
            y += 11
        self.show_image(image)

    def draw_menu(self, items: List[str], selected_index: int, title: str = "") -> None:
        image = self.new_image()
        draw = ImageDraw.Draw(image)
        font = get_font(11, bold=True)
        visible_items = 5
        start_index = max(0, selected_index - 2)
        end_index = min(len(items), start_index + visible_items)
        if end_index - start_index < visible_items and len(items) >= visible_items:
            start_index = max(0, end_index - visible_items)
        y = 0
        for i in range(start_index, end_index):
            if i == selected_index:
                draw.rectangle([(0, y), (128, y + 13)], fill=255)
                draw.text((4, y + 1), f"> {items[i]}", font=font, fill=0)
            else:
                draw.text((4, y + 1), f"  {items[i]}", font=font, fill=255)
            y += 13
        self.show_image(image)

    def draw_spinner(self, message: str, frame: int = 0) -> None:
        image = self.new_image()
        draw = ImageDraw.Draw(image)
        font = get_font(11, bold=False)
        # Draw message
        lines = wrap_text(message, max_chars=20)
        y = 0
        for line in lines[:5]:
            draw.text((2, y), line, font=font, fill=255)
            y += 11
        # Spinner bottom-right
        cx, cy, r = 112, 52, 8
        for i in range(12):
            angle = (i / 12.0) * 6.28318
            x = cx + int(r * 0.9 * __import__("math").cos(angle))
            y2 = cy + int(r * 0.9 * __import__("math").sin(angle))
            shade = 255 if (i == (frame % 12)) else 80
            draw.point((x, y2), fill=shade)
        self.show_image(image)
