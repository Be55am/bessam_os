from PIL import ImageFont
from typing import Optional

_DEFAULT_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
]

_DEFAULT_BOLD_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]


def get_font(size: int = 11, bold: bool = False) -> ImageFont.ImageFont:
    paths = _DEFAULT_BOLD_PATHS if bold else _DEFAULT_FONT_PATHS
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()
