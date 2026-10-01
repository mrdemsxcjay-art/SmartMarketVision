"""Centralised Chart Capture parameters (Phase 7).

The capture is produced from the **real** candle series and the **real**
detections/confluences of the engines. Nothing is drawn that did not come from the
data: no placeholder image, no synthetic candle, no invented level.

Resolution presets
------------------
``phone``    : portrait, meant to be read on a phone without zooming;
``telegram`` : landscape, sized so Telegram shows it well in a chat preview.
Both are rendered from the same scene, so they always tell the same story.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Resolution(BaseModel):
    name: str
    width: int = Field(ge=320, le=4096)
    height: int = Field(ge=320, le=4096)
    description: str = ""


#: resolution presets. A preset is a real pixel size, never a "close enough" one.
RESOLUTIONS: dict[str, Resolution] = {
    "phone": Resolution(
        name="phone", width=1080, height=1350, description="portrait, lisible sans zoom sur telephone"
    ),
    "telegram": Resolution(
        name="telegram", width=1200, height=675, description="paysage, bon apercu dans un chat Telegram"
    ),
}


class CaptureLayout(BaseModel):
    """Geometry of the scene, in pixels (derived from the resolution)."""

    margin_left: int = Field(default=24, ge=0)
    margin_right: int = Field(default=112, ge=40, description="room for the price axis")
    margin_top: int = Field(default=132, ge=40, description="room for the header band")
    margin_bottom: int = Field(default=108, ge=20, description="room for the time axis and the footer")
    candle_count: int = Field(default=120, ge=20, le=600, description="candles shown")
    candle_width_ratio: float = Field(default=0.62, gt=0.1, lt=1.0)
    label_font_size: int = Field(default=19, ge=10, le=48)
    title_font_size: int = Field(default=27, ge=12, le=72)


class CaptureOverlays(BaseModel):
    """Overlay budget per priority level (7.2).

    Priority order: the main event first, then the confluence, then the sources,
    then the context. When the budget is exhausted the lower levels are simply not
    drawn - an unreadable pile of shapes is worse than a readable chart.
    """

    max_context: int = Field(default=6, ge=0, le=40, description="trend / structure context lines")
    max_sources: int = Field(default=8, ge=0, le=40, description="the detections behind the reading")
    max_zones: int = Field(default=6, ge=0, le=30, description="FVG / order block / dealing range")
    max_levels: int = Field(default=8, ge=0, le=40, description="horizontal levels")
    max_labels: int = Field(default=14, ge=1, le=60, description="hard cap of visible labels")
    label_min_gap: int = Field(default=7, ge=1, description="minimum vertical gap between two labels")


class CaptureParams(BaseSettings):
    """Runtime parameters of the capture engine (``CAPTURE_`` prefix)."""

    model_config = SettingsConfigDict(env_prefix="CAPTURE_", env_file=".env", extra="ignore")

    enabled: bool = Field(default=True)
    default_resolution: str = Field(default="phone")
    output_dir: str | None = Field(default=None, description="defaults to data/captures")
    keep_days: int = Field(default=7, ge=0, description="retention of the generated files")
    dedup: bool = Field(default=True, description="the same reading never produces two identical files")
    theme: str = Field(default="dark", description="dark | light")

    layout: CaptureLayout = Field(default_factory=CaptureLayout)
    overlays: CaptureOverlays = Field(default_factory=CaptureOverlays)

    GROUPS: tuple[str, ...] = ("layout", "overlays")

    def resolution(self, name: str | None = None) -> Resolution:
        key = (name or self.default_resolution).lower()
        return RESOLUTIONS.get(key, RESOLUTIONS[self.default_resolution])

    def snapshot(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name in self.GROUPS:
            value = getattr(self, name, None)
            if isinstance(value, BaseModel):
                out[name] = value.model_dump()
        out["derived"] = {
            "default_resolution": self.default_resolution,
            "resolutions": {
                key: {"width": value.width, "height": value.height, "description": value.description}
                for key, value in RESOLUTIONS.items()
            },
            "theme": self.theme,
            "dedup": self.dedup,
            "keep_days": self.keep_days,
        }
        return out

    def apply_overrides(self, overrides: dict[str, dict[str, Any]]) -> list[str]:
        applied: list[str] = []
        for group, values in (overrides or {}).items():
            target = getattr(self, group, None)
            if group == "derived":
                continue
            if not isinstance(target, BaseModel):
                applied.append(f"ignored:{group}")
                continue
            for key, value in (values or {}).items():
                if key not in type(target).model_fields:
                    applied.append(f"ignored:{group}.{key}")
                    continue
                setattr(target, key, value)
                applied.append(f"{group}.{key}={value}")
        return applied


params = CaptureParams()
