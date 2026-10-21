"""Output formats and the five quality levels shown in the compact window."""

from dataclasses import dataclass

from .strings import translate


@dataclass(frozen=True)
class Format:
    key: str
    name: str
    suffix: str
    kind: str
    parameter: str
    levels: tuple
    description: str

    def quality_text(self, index, language="zh_CN"):
        value = self.levels[index]
        if self.key == "auto":
            return f"AVIF {FORMATS[2].levels[index]} / H.264 CRF {FORMATS[4].levels[index]}"
        if self.parameter == "colors":
            return (
                translate(language, "png_original")
                if value is None
                else translate(language, "png_colors", value=value)
            )
        if self.parameter == "quality":
            return translate(language, "quality_value", name=self.name, value=value)
        return f"{self.name} · {self.parameter} {value}"


FORMATS = (
    Format("jpeg", "JPEG", ".jpg", "images", "quality", (35, 50, 68, 82, 93), "jpeg_description"),
    Format("webp", "WebP", ".webp", "images", "quality", (25, 45, 65, 82, 94), "webp_description"),
    Format("avif", "AVIF", ".avif", "images", "quality", (20, 35, 50, 65, 80), "avif_description"),
    Format("png", "PNG", ".png", "images", "colors", (32, 64, 128, 256, None), "png_description"),
    Format("h264", "H.264", ".mp4", "videos", "CRF", (36, 31, 26, 21, 17), "h264_description"),
    Format("h265", "H.265", ".mp4", "videos", "CRF", (39, 34, 29, 24, 19), "h265_description"),
    Format("av1", "AV1", ".mp4", "videos", "CRF", (48, 42, 35, 28, 22), "av1_description"),
    Format("av1_webm", "AV1", ".webm", "videos", "CRF", (48, 42, 35, 28, 22), "webm_description"),
    Format("auto", "AUTO", "", "all", "auto", (0, 1, 2, 3, 4), "auto_description"),
)


def get_format(key):
    return next(format for format in FORMATS if format.key == key)
