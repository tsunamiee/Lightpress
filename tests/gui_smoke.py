"""Exercise the interface with generated media and capture both themes."""

from __future__ import annotations
import hashlib
import json
from pathlib import Path
import subprocess
import tkinter as tk
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageGrab
from compressor import core
from compressor.ui import App


def verify(folder: str):
    destination = Path(folder).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    report = {"checks": {}, "errors": []}
    root = None
    try:
        source = destination / "示例素材"
        source.mkdir(exist_ok=True)
        output = destination / "验证输出"
        for name, color in [
            ("旅行照片.jpg", "#6CA4C8"),
            ("透明素材.png", "#B2C8B8"),
            ("细节照片.jpg", "#D3AC89"),
        ]:
            image = Image.new("RGB", (480, 320), color)
            draw = ImageDraw.Draw(image)
            draw.ellipse((70, 30, 370, 330), fill="#E7E5DB")
            draw.rectangle((0, 200, 480, 320), fill="#557C79")
            image.save(source / name)
        original = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}
        ffmpeg, ffprobe = core.video.binary_path("ffmpeg"), core.video.binary_path("ffprobe")
        report["binaries"] = [ffmpeg, ffprobe]
        subprocess.run(
            [
                ffmpeg,
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=320x240:rate=12",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440",
                "-t",
                "1",
                "-c:v",
                "mpeg4",
                "-q:v",
                "2",
                "-c:a",
                "aac",
                "-y",
                str(source / "生活片段.mp4"),
            ],
            check=True,
            capture_output=True,
            creationflags=core.video.CREATE_NO_WINDOW,
            timeout=30,
        )
        tasks = core.scan(source, output)
        events = []
        options = core.Options(skip_larger=False)
        with patch(
            "compressor.history.history_path",
            return_value=destination / "appdata" / "history.sqlite3",
        ):
            core.run(
                tasks, output, options, core.Cancellation(), lambda k, v: events.append((k, v))
            )
        results = [v for k, v in events if k == "result"]
        report["results"] = results
        report["checks"]["image_and_video_encoding"] = len(results) == 4 and all(
            v["status"] == "success" for v in results
        )
        report["checks"]["originals_unchanged"] = all(
            hashlib.sha256((source / name).read_bytes()).hexdigest() == value
            for name, value in original.items()
        )
        report["capabilities"] = core.capabilities()
        root = tk.Tk()
        app = App(root, settings={"source": str(source), "output": str(output)}, persist=False)
        root.geometry("1160x780+80+80")
        root.update()
        app._on_scanned(dict(tasks=tasks, run_after=False))
        for kind, value in events:
            if kind in ("result", "finished"):
                app.events.put((kind, value))
        root.update()
        app.poll()
        root.update()
        report["checks"]["tkinter_window"] = (
            root.winfo_width() == 1160 and app.tree.winfo_height() > 70
        )
        report["checks"]["actions_visible"] = (
            app.start_btn.winfo_rooty() + app.start_btn.winfo_height()
            <= root.winfo_rooty() + root.winfo_height()
        )
        report["checks"]["task_count"] = len(app.tree.get_children()) == 4
        report["checks"]["settings_scrollable"] = app.notebook.winfo_reqheight() > 0

        def capture(theme, filename=None):
            app.source.set(r"C:\Media\相册")
            app.output.set(r"C:\Media\相册\压缩输出")
            app.theme = theme
            app.apply_theme()
            root.update()
            try:
                ImageGrab.grab(window=root.winfo_id()).save(
                    destination / ((filename or theme) + ".png")
                )
            except OSError as exc:
                report.setdefault("capture_warnings", []).append(str(exc))

        capture("light")
        report["checks"]["light_theme"] = root.cget("background") == "#F5F6F7"
        capture("dark")
        report["checks"]["dark_theme"] = root.cget("background") == "#191C21"
        app.notebook.select(1)
        root.update()
        report["checks"]["video_tab"] = app.notebook.index("current") == 1
        viewport = app.notebook.master.master
        report["checks"]["video_quality_visible"] = (
            app.quality_entry.winfo_rooty() + app.quality_entry.winfo_height()
            <= viewport.winfo_rooty() + viewport.winfo_height()
        )
        capture("dark", "dark-video")
        app.rate_label.set("指定码率")
        app.update_rate()
        root.update()
        report["checks"]["bitrate_options"] = bool(app.bitrate_frame.winfo_ismapped())
        original_quality = app.option_vars["image_quality"].get()
        app.show_options()
        root.update()
        report["checks"]["separate_options_page"] = (
            app.settings_page.winfo_ismapped() and not app.main_page.winfo_ismapped()
        )
        report["checks"]["primary_only_default_off"] = not app.option_vars[
            "image_primary_only"
        ].get()
        app.option_vars["image_primary_only"].set(True)
        capture("light", "options-light")
        capture("dark", "options-dark")
        app.scan()
        report["checks"]["no_scan_from_options"] = not app.busy
        app.cancel_options()
        root.update()
        report["checks"]["options_cancel_restores_value"] = (
            not app.option_vars["image_primary_only"].get() and app.main_page.winfo_ismapped()
        )
        app.show_options()
        app.option_vars["image_primary_only"].set(True)
        with patch("compressor.core.save_settings") as save_settings:
            app.persist = True
            app.save_options()
            app.persist = False
            report["checks"]["options_saved"] = (
                save_settings.call_count == 1
                and save_settings.call_args.args[0]["options"]["image_primary_only"]
                and not app.options_open
                and app.options().image_primary_only
                and app.option_vars["image_quality"].get() == original_quality
            )
        root.update()
        app.toggle_filters()
        root.geometry("980x640")
        root.update()
        report["checks"]["small_window_actions_visible"] = (
            app.start_btn.winfo_rooty() + app.start_btn.winfo_height()
            <= root.winfo_rooty() + root.winfo_height()
        )
        app.show_options()
        root.update()
        report["checks"]["small_window_options_visible"] = (
            app.save_options_btn.winfo_rooty() + app.save_options_btn.winfo_height()
            <= root.winfo_rooty() + root.winfo_height()
            and app.primary_only_check.winfo_ismapped()
        )
        app.option_vars["image_primary_only"].set(False)
        with patch.object(app, "persist_settings") as persist_settings:
            app.close()
            report["checks"]["close_discards_unsaved_options"] = (
                app.option_vars["image_primary_only"].get() and persist_settings.call_count == 1
            )
        root = None
        report["success"] = all(report["checks"].values())
    except Exception:
        import traceback

        report["errors"].append(traceback.format_exc())
        report["success"] = False
    finally:
        if root:
            root.destroy()
        (destination / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return report["success"]


if __name__ == "__main__":
    import sys

    raise SystemExit(0 if verify(sys.argv[1] if len(sys.argv) > 1 else "artifacts/ui") else 1)
