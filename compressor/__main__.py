"""Application entry point."""

import argparse
import io
import json
from pathlib import Path

from . import __version__


def main():
    parser = argparse.ArgumentParser(description="轻压：图片与视频批量压缩")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--check", type=Path, metavar="REPORT", help="将运行环境检查结果写入 JSON 文件"
    )
    parser.add_argument("--classic", action="store_true", help="打开完整参数界面")
    args = parser.parse_args()
    if args.check:
        from PIL import Image
        from . import core

        report = core.capabilities()
        report["version"] = __version__
        from .formats import FORMATS
        from .storage import settings_path, system_language

        report["formats"] = [format.key for format in FORMATS]
        report["settings_path"] = str(settings_path())
        report["system_language"] = system_language()
        from .about import component_licenses
        from .storage import application_dir

        report["open_source_components"] = [
            name for name, _ in component_licenses(application_dir())
        ]
        report["image_round_trips"] = {}
        from .graphics import render_icon

        try:
            with Image.open(io.BytesIO(render_icon("settings", "#3869EC"))) as icon:
                icon.load()
                report["svg_rendering"] = icon.size == (24, 24) and icon.mode == "RGBA"
        except Exception as exc:
            report["svg_rendering"] = False
            report["svg_error"] = str(exc)
        try:
            for format in ("AVIF", "JPEG", "PNG", "WEBP"):
                buffer = io.BytesIO()
                Image.new("RGB", (32, 32), "gray").save(buffer, format=format)
                buffer.seek(0)
                with Image.open(buffer) as image:
                    image.load()
                    report["image_round_trips"][format] = (
                        image.size == (32, 32) and image.format == format
                    )
            report["avif_round_trip"] = report["image_round_trips"]["AVIF"]
        except Exception as exc:
            report["avif_round_trip"] = False
            report["image_error"] = str(exc)
        report["ffmpeg"] = core.video.binary_path("ffmpeg") if report["video"] else None
        args.check.parent.mkdir(parents=True, exist_ok=True)
        args.check.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return (
            0
            if report["svg_rendering"]
            and all(report["image_round_trips"].values())
            and len(report["image_round_trips"]) == 4
            else 1
        )

    if args.classic:
        from .ui import main as run_ui
    else:
        from .compact import main as run_ui

    run_ui()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
