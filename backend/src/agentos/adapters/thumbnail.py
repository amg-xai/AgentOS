"""Bounded local rendering and PNG validation, with a bundled licensed font."""

import hashlib
from io import BytesIO
from pathlib import Path

import PIL
from PIL import Image, ImageDraw, ImageFont

from agentos.domain.missions import StateConflict
from agentos.domain.thumbnail import (
    ThumbnailEvidence,
    ThumbnailLayout,
    ThumbnailReceipt,
    ThumbnailRenderingError,
)

FONT = Path(__file__).parent.parent / "assets" / "NotoSans.ttf"


def validate_png(content: bytes) -> None:
    if not content or len(content) > 2_000_000 or not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise StateConflict("PNG must be a valid bounded 1280x720 graphic")
    try:
        with Image.open(BytesIO(content)) as image:
            if (
                image.format != "PNG"
                or image.size != (1280, 720)
                or getattr(image, "is_animated", False)
            ):
                raise ValueError("Unsupported PNG")
            image.verify()
        with Image.open(BytesIO(content)) as image:
            image.load()
    except (OSError, ValueError, SyntaxError) as exc:
        raise StateConflict("PNG must be a valid bounded 1280x720 graphic") from exc


def _lines(text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines: list[str] = []
    for word in text.split():
        if font.getlength(word) > width:
            raise ThumbnailRenderingError(
                "Thumbnail word does not fit; shorten the headline/subtitle"
            )
        if lines and font.getlength(lines[-1] + " " + word) <= width:
            lines[-1] += " " + word
        else:
            lines.append(word)
    return lines


def render_thumbnail(layout: ThumbnailLayout) -> tuple[bytes, ThumbnailEvidence]:
    layout = ThumbnailLayout.model_validate(layout.model_dump())

    def luminance(color: str) -> float:
        values = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values]
        return sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722), strict=True))

    light, dark = sorted((luminance(layout.background), luminance(layout.foreground)), reverse=True)
    if (light + 0.05) / (dark + 0.05) < 4.5:
        raise ThumbnailRenderingError(
            "Thumbnail text needs contrasting foreground/background colors"
        )
    image = Image.new("RGB", (1280, 720), layout.background)
    draw = ImageDraw.Draw(image)
    if layout.decoration == "circle":
        draw.ellipse((1000, 50, 1190, 240), fill=layout.accent)
    elif layout.decoration == "bars":
        for bar_x in (1070, 1120, 1170):
            draw.rectangle((bar_x, 60, bar_x + 24, 230), fill=layout.accent)
    # Text occupies a separate, bounded region below decoration. Fit before drawing.
    headline_font = ImageFont.truetype(str(FONT), 72)
    subtitle_font = ImageFont.truetype(str(FONT), 34)
    headline = _lines(layout.headline, headline_font, 1100)
    subtitle = _lines(layout.subtitle, subtitle_font, 1100)
    if len(headline) > 3 or len(subtitle) > 3:
        raise ThumbnailRenderingError("Thumbnail text exceeds its layout; shorten it")
    y = 265
    for lines, font, step in ((headline, headline_font, 95), (subtitle, subtitle_font, 48)):
        for line in lines:
            x: float = 90 if layout.composition == "left" else (1280 - font.getlength(line)) / 2
            box = draw.textbbox((x, y), line, font=font, anchor="lt")
            if box[0] < 0 or box[2] > 1280 or box[3] > 675:
                raise ThumbnailRenderingError("Thumbnail text exceeds its canvas; shorten it")
            draw.text((x, y), line, font=font, fill=layout.foreground, anchor="lt")
            y += step
        y += 20
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=False, compress_level=9)
    content = buffer.getvalue()
    validate_png(content)
    return content, ThumbnailEvidence(
        layout=layout,
        receipt=ThumbnailReceipt(
            renderer="agentos-graphic-v1",
            pillow=PIL.__version__,
            font_sha256=hashlib.sha256(FONT.read_bytes()).hexdigest(),
            png_sha256=hashlib.sha256(content).hexdigest(),
            width=1280,
            height=720,
        ),
    )
