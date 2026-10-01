"""Pillow renderer (Phase 7) - draws the real chart and nothing else.

Rules enforced here, because they were explicit requirements:

* the image is generated from the scene, and the scene only contains values that
  came from candles or detections - there is no placeholder path in this file;
* overlays are drawn by priority (main event > confluence > sources > context),
  so if something must be dropped it is the least important thing;
* **labels never overlap and never sit on the candles**: they live in a dedicated
  right-hand gutter, each one connected to its price by a short leader. A label
  that cannot find a free slot is skipped (and counted), which is the only honest
  behaviour when the alternative is an unreadable pile.

Layout::

    [ header band : symbol, timeframe, state, score, timestamp, price ]
    [ plot : candles | gutter: labels | axis: prices ]
    [ footer : disclaimer + what was not drawn ]
"""

from __future__ import annotations

from datetime import datetime, timezone

from PIL import Image, ImageDraw, ImageFont

from app.capture.models import CaptureScene, Overlay, OverlayKind
from app.capture.params import CaptureParams, Resolution
from app.logging_conf import get_logger

logger = get_logger(__name__)

FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

THEMES = {
    "dark": {
        "background": "#0d1117",
        "panel": "#131a24",
        "gutter": "#0f1620",
        "grid": "#1e2733",
        "text": "#e6edf3",
        "muted": "#8b949e",
        "bull": "#26c281",
        "bear": "#ef5350",
    },
    "light": {
        "background": "#ffffff",
        "panel": "#f3f5f9",
        "gutter": "#f7f9fc",
        "grid": "#e2e7ee",
        "text": "#12181f",
        "muted": "#5c6873",
        "bull": "#0f9d58",
        "bear": "#d93025",
    },
}

#: short, readable names for the engines (the capture must be understandable)
SOURCE_SHORT = {
    "CHART_PATTERN_ENGINE": "Chartiste",
    "CHARTISTE": "Chartiste",
    "CHARTISTE_ENGINE": "Chartiste",
    "PRICE_ACTION_ENGINE": "PA",
    "PRICE_ACTION": "PA",
    "SMC_ICT_ENGINE": "SMC/ICT",
    "SMC_ICT": "SMC/ICT",
    "CONFLUENCE": "Confluence",
    "OPPORTUNITY": "Opportunite",
}


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except Exception:  # pragma: no cover - the font is always present in the image
        return ImageFont.load_default(size=size)


class _SlotAllocator:
    """Vertical slot allocator for the gutter: no two labels ever overlap."""

    def __init__(self, top: int, bottom: int, height: int, gap: int, max_labels: int) -> None:
        self.top = top
        self.bottom = bottom
        self.height = height
        self.gap = gap
        self.max_labels = max_labels
        self.taken: list[tuple[int, int]] = []
        self.skipped = 0

    def place(self, wanted_center: int) -> int | None:
        if len(self.taken) >= self.max_labels:
            self.skipped += 1
            return None
        step = self.height + self.gap
        for offset in (0, -1, 1, -2, 2, -3, 3, -4, 4, -5, 5, -6, 6, -7, 7, -8, 8):
            center = int(wanted_center + offset * step)
            top, bottom = center - self.height // 2, center + self.height // 2
            if top < self.top or bottom > self.bottom:
                continue
            if any(not (bottom < taken_top or top > taken_bottom) for taken_top, taken_bottom in self.taken):
                continue
            self.taken.append((top, bottom))
            return center
        self.skipped += 1
        return None


def render_scene(scene: CaptureScene, params: CaptureParams, resolution: Resolution | None = None) -> Image.Image:
    res = resolution or params.resolution()
    theme = THEMES.get(params.theme, THEMES["dark"])
    layout = params.layout

    image = Image.new("RGB", (res.width, res.height), theme["background"])
    draw = ImageDraw.Draw(image, "RGBA")
    title_font = _font(FONT_BOLD, layout.title_font_size)
    label_font = _font(FONT_REGULAR, max(13, layout.label_font_size - 1))
    small_font = _font(FONT_REGULAR, max(11, int(layout.label_font_size * 0.8)))

    gutter_width = max(230, int(res.width * 0.27))
    axis_width = max(64, int(layout.margin_right * 0.62))
    plot = {
        "left": layout.margin_left,
        "right": res.width - gutter_width - axis_width,
        "top": layout.margin_top,
        "bottom": res.height - layout.margin_bottom,
    }
    gutter = {"left": plot["right"] + 8, "right": plot["right"] + gutter_width - 6}
    axis = {"left": gutter["right"] + 6, "right": res.width - 8}

    _draw_header(draw, scene, res, plot, theme, title_font, small_font)
    draw.rectangle([gutter["left"] - 4, plot["top"], gutter["right"] + 2, plot["bottom"]], fill=theme["gutter"])

    if not scene.candles:
        _draw_center_text(draw, res, theme, label_font, "AUCUNE DONNEE DE MARCHE - capture non produite")
        return image

    low, high = scene.price_window()
    candles = scene.candles
    step = (plot["right"] - plot["left"]) / max(1, len(candles))
    width = max(2, int(step * layout.candle_width_ratio))
    gutter_width_px = gutter["right"] - gutter["left"]

    def x_of(index: int) -> float:
        return plot["left"] + (index + 0.5) * step

    def y_of(price: float) -> float:
        if high - low < 1e-12:
            return (plot["top"] + plot["bottom"]) / 2
        ratio = (price - low) / (high - low)
        return plot["bottom"] - ratio * (plot["bottom"] - plot["top"])

    _draw_grid(draw, plot, axis, theme, high, low, y_of, small_font)
    _draw_zones(draw, scene, plot, y_of, theme)

    label_height = max(13, layout.label_font_size - 1) + 8
    allocator = _SlotAllocator(
        plot["top"] + 4,
        plot["bottom"] - 4,
        label_height,
        params.overlays.label_min_gap,
        params.overlays.max_labels,
    )
    _draw_candles(draw, candles, x_of, y_of, width, theme)
    _draw_overlay_tags(draw, scene, plot, gutter, y_of, theme, label_font, allocator, gutter_width_px)
    _draw_time_axis(draw, candles, plot, theme, small_font, x_of)
    _draw_footer(draw, scene, res, theme, small_font)
    if allocator.skipped:
        scene.notes.append(f"{allocator.skipped} etiquette(s) non dessinee(s) : gouttiere pleine")
    return image


def save_png(image: Image.Image, path, optimize: bool = True) -> int:
    """Save the image as a real PNG and return the byte size."""
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=optimize)
    return path.stat().st_size


# ------------------------------------------------------------------- drawing
def _draw_header(draw, scene: CaptureScene, res: Resolution, plot: dict, theme: dict, title_font, small_font) -> None:
    draw.rectangle([0, 0, res.width, plot["top"] - 10], fill=theme["panel"])
    draw.text((24, 16), scene.title, font=title_font, fill=theme["text"])
    stamp = scene.timestamp.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    price = f"{scene.price:.5f}" if scene.price is not None else "-"
    right = f"{stamp}   {price}"
    width = draw.textlength(right, font=small_font)
    draw.text((res.width - 24 - width, 24), right, font=small_font, fill=theme["muted"])

    y = 52
    for index, line in enumerate(scene.headline[:2]):
        color = theme["text"] if index == 0 else theme["muted"]
        draw.text((24, y), _truncate(draw, line, small_font, res.width - 48), font=small_font, fill=color)
        y += 21
    watermark = "SMART MARKET VISION"
    width = draw.textlength(watermark, font=small_font)
    draw.text((res.width - 24 - width, plot["top"] - 27), watermark, font=small_font, fill=theme["muted"])


def _draw_grid(draw, plot: dict, axis: dict, theme: dict, high: float, low: float, y_of, font) -> None:
    lines = 5
    for index in range(lines + 1):
        y = plot["top"] + (plot["bottom"] - plot["top"]) * index / lines
        draw.line([(plot["left"], y), (plot["right"], y)], fill=theme["grid"], width=1)
        value = high - (high - low) * index / lines
        draw.text((axis["left"], y - 8), f"{value:.5f}", font=font, fill=theme["muted"])
    draw.rectangle([plot["left"], plot["top"], plot["right"], plot["bottom"]], outline=theme["grid"])


def _draw_candles(draw, candles, x_of, y_of, width, theme: dict) -> None:
    for index, candle in enumerate(candles):
        x = x_of(index)
        color = theme["bull"] if candle.close >= candle.open else theme["bear"]
        draw.line([(x, y_of(candle.high)), (x, y_of(candle.low))], fill=color, width=max(1, width // 3))
        top, bottom = y_of(max(candle.open, candle.close)), y_of(min(candle.open, candle.close))
        if bottom - top < 1:
            bottom = top + 1
        draw.rectangle([x - width / 2, top, x + width / 2, bottom], fill=color)


def _draw_zones(draw, scene: CaptureScene, plot: dict, y_of, theme: dict) -> None:
    for overlay in sorted(scene.overlays, key=lambda item: -item.priority):
        if overlay.kind is not OverlayKind.ZONE or overlay.top is None or overlay.bottom is None:
            continue
        top, bottom = sorted((y_of(overlay.top), y_of(overlay.bottom)))
        color = overlay.color or "#ff5fa2"
        draw.rectangle([plot["left"], top, plot["right"], max(bottom, top + 2)], fill=_rgba(color, 40))
        draw.line([(plot["left"], top), (plot["right"], top)], fill=_rgba(color, 140), width=1)
        draw.line([(plot["left"], bottom), (plot["right"], bottom)], fill=_rgba(color, 140), width=1)


def _draw_overlay_tags(draw, scene: CaptureScene, plot: dict, gutter: dict, y_of, theme: dict, font, allocator, gutter_width: int) -> None:
    """All labels go to the gutter; each one keeps a short leader to its price."""
    ordered = sorted(
        [item for item in scene.overlays if item.price is not None or item.kind is OverlayKind.ZONE],
        key=lambda item: (item.priority, item.label),
    )
    for overlay in ordered:
        anchor_price = overlay.price
        if overlay.kind is OverlayKind.ZONE and anchor_price is None and overlay.top is not None:
            anchor_price = (overlay.top + (overlay.bottom or overlay.top)) / 2
        if anchor_price is None:
            continue
        y = y_of(anchor_price)
        if not plot["top"] - 20 <= y <= plot["bottom"] + 20:
            continue
        color = overlay.color or "#9aa4b2"
        if overlay.kind is not OverlayKind.ZONE:
            if overlay.kind is OverlayKind.MARKER and overlay.time is not None:
                index = _index_of_time(scene, overlay.time)
                if index is not None:
                    x = plot["left"] + (index + 0.5) * ((plot["right"] - plot["left"]) / max(1, len(scene.candles)))
                    radius = 5
                    draw.ellipse([x - radius, y - radius, x + radius, y + radius], outline=_rgba(color, 255), width=2)
            dash = overlay.style != "solid"
            _dashed_line(draw, plot["left"], plot["right"], y, _rgba(color, 190), dash=dash)
        _gutter_tag(draw, gutter, y, overlay, font, theme, color, allocator, gutter_width)


def _gutter_tag(draw, gutter: dict, y: float, overlay: Overlay, font, theme: dict, color: str, allocator, gutter_width: int) -> None:
    height = allocator.height
    center = allocator.place(int(y))
    if center is None:
        return
    text = overlay.label
    if overlay.price is not None:
        text = f"{text}  {overlay.price:.5f}"
    text = _truncate(draw, text, font, gutter_width - 26)
    top = center - height // 2
    draw.rectangle([gutter["left"], top, gutter["right"], top + height], fill=_rgba(color, 34))
    draw.rectangle([gutter["left"], top, gutter["left"] + 3, top + height], fill=_rgba(color, 255))
    draw.text((gutter["left"] + 9, top + (height - allocator.height + 4) // 2 + 3), text, font=font, fill=theme["text"])
    # leader: from the price on the plot to the label, never over the candles
    draw.line([(gutter["left"] - 4, center), (gutter["left"], center)], fill=_rgba(color, 220), width=2)
    if abs(center - y) > height:
        draw.line([(gutter["left"] - 10, center), (gutter["left"] - 4, y)], fill=_rgba(color, 120), width=1)


def _draw_time_axis(draw, candles, plot: dict, theme: dict, font, x_of) -> None:
    labels = min(5, len(candles))
    if labels < 2:
        return
    for step in range(labels):
        index = int(step * (len(candles) - 1) / (labels - 1))
        stamp = datetime.fromtimestamp(candles[index].time, tz=timezone.utc).strftime("%d/%m %H:%M")
        width = draw.textlength(stamp, font=font)
        x = min(max(x_of(index) - width / 2, plot["left"]), plot["right"] - width)
        draw.text((x, plot["bottom"] + 10), stamp, font=font, fill=theme["muted"])


def _draw_footer(draw, scene: CaptureScene, res: Resolution, theme: dict, font) -> None:
    """Disclaimer + what was not drawn, under the time axis (never over it)."""
    lines = [scene.footer, *scene.notes[:2]]
    y = res.height - 20 - 17 * len(lines)
    for line in lines:
        draw.text((24, y), _truncate(draw, line, font, res.width - 48), font=font, fill=theme["muted"])
        y += 17


def _draw_center_text(draw, res: Resolution, theme: dict, font, text: str) -> None:
    width = draw.textlength(text, font=font)
    draw.text(((res.width - width) / 2, res.height / 2), text, font=font, fill=theme["text"])


def _dashed_line(draw, x0: float, x1: float, y: float, color, dash: bool = True, length: int = 9) -> None:
    if not dash:
        draw.line([(x0, y), (x1, y)], fill=color, width=1)
        return
    x = x0
    while x < x1:
        draw.line([(x, y), (min(x + length, x1), y)], fill=color, width=1)
        x += length * 2


def _truncate(draw, text: str, font, max_width: float) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    truncated = text
    while truncated and draw.textlength(truncated + "...", font=font) > max_width:
        truncated = truncated[:-1]
    return truncated + "..."


def _index_of_time(scene: CaptureScene, time_value: int) -> int | None:
    for index, candle in enumerate(scene.candles):
        if candle.time == time_value:
            return index
    return None


def _rgba(color: str, alpha: int) -> tuple[int, int, int, int]:
    text = color.lstrip("#")
    if len(text) == 3:
        text = "".join(char * 2 for char in text)
    try:
        red, green, blue = (int(text[index : index + 2], 16) for index in (0, 2, 4))
    except ValueError:  # pragma: no cover - a colour coming from the data
        red = green = blue = 128
    return (red, green, blue, alpha)
