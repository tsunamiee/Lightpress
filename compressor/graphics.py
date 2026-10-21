"""Render SVG assets at their display size."""

from functools import lru_cache
from pathlib import Path
import sys
import tkinter as tk

import resvg_py


def asset_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return base / "assets"


@lru_cache(maxsize=32)
def _source(name: str) -> str:
    return (asset_dir() / "icons" / f"{name}.svg").read_text(encoding="utf-8")


def render_icon(name: str, color: str, size: int = 24, surface: str = "#FFFFFF") -> bytes:
    svg = _source(name).replace("currentColor", color).replace("__SURFACE__", surface)
    return resvg_py.svg_to_bytes(
        svg_string=svg,
        width=size,
        height=size,
        skip_system_fonts=True,
        shape_rendering="geometric_precision",
    )


class IconCache:
    def __init__(self, master):
        self.master = master
        self.images = {}

    def get(self, name, color, size=24, surface="#FFFFFF"):
        key = name, color, size, surface
        if key not in self.images:
            self.images[key] = tk.PhotoImage(
                master=self.master, data=render_icon(name, color, size, surface)
            )
        return self.images[key]
