"""Check compact UI behavior with generated media."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import tkinter as tk
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageGrab

from compressor import core, storage
from compressor.compact import CompactApp


def verify(destination):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    source, output = destination / "示例素材", destination / "压缩输出"
    source.mkdir(exist_ok=True)
    checks, errors = {}, []
    root = None
    patcher = patch("compressor.storage.application_dir", return_value=destination / "app")
    patcher.start()

    def exists():
        try:
            return bool(root and root.winfo_exists())
        except tk.TclError:
            return False

    try:
        for name, mode in (("旅行.jpg", "RGB"), ("透明素材.png", "RGBA")):
            image = Image.new(
                mode, (320, 240), (70, 125, 175, 95) if mode == "RGBA" else (70, 125, 175)
            )
            ImageDraw.Draw(image).rectangle((100, 30, 230, 190), fill="coral")
            image.save(source / name)
        video = source / "片段.mov"
        subprocess.run(
            [
                core.video.binary_path("ffmpeg"),
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=320x240:rate=12",
                "-t",
                "1",
                "-c:v",
                "mpeg4",
                "-y",
                str(video),
            ],
            check=True,
            capture_output=True,
            creationflags=core.video.CREATE_NO_WINDOW,
        )
        originals = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in source.iterdir()
        }
        stored = dict(
            source=str(source),
            output=str(output),
            format="auto",
            quality=3,
            compact={"language": "zh_CN"},
        )
        root = tk.Tk()
        root.report_callback_exception = lambda *value: errors.append(str(value))
        app = CompactApp(root, settings=stored)
        root.geometry("453x520+100+100")
        root.update()

        def pump(until, timeout=25):
            end = time.monotonic() + timeout
            while not until() and time.monotonic() < end:
                root.update()
                time.sleep(0.01)
            root.update()
            if not until():
                raise TimeoutError("UI work did not finish")

        def capture(name):
            saved = app.source.get(), app.output.get()
            app.source.set(r"D:\Media\相册")
            app.output.set(r"D:\Media\压缩输出")
            app.draw()
            root.update()
            ImageGrab.grab(window=root.winfo_id()).save(destination / f"{name}.png")
            app.source.set(saved[0])
            app.output.set(saved[1])
            app.draw()

        checks["portable_first_launch_configuration"] = storage.settings_path().is_file()
        checks["default_subfolders_off"] = not app.settings["recursive"]
        checks["default_smaller_only_off"] = not app.settings["skip_larger"]
        checks["fixed_compact_window"] = root.resizable() == (0, 0) and (
            root.winfo_width(),
            root.winfo_height(),
        ) == (453, 520)
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            from compressor.window_theme import window_handle

            get_style = ctypes.windll.user32.GetWindowLongW
            get_style.argtypes = (wintypes.HWND, ctypes.c_int)
            get_style.restype = wintypes.LONG
            checks["native_maximize_disabled"] = not (get_style(window_handle(root), -16) & 0x10000)
        app.convert()
        checks["real_background_job_started"] = app.running
        pump(lambda: not app.running)
        checks["mixed_image_video_job"] = len(app.results) == 3 and all(
            r["status"] == "success" for r in app.results
        )
        checks["real_files_created"] = len({item["output"] for item in app.results}) == 3 and all(
            Path(item["output"]).is_file() for item in app.results
        )
        checks["real_progress_completed"] = app.progress == 100 and app.status_key == "finished"
        checks["history_in_app_directory"] = (
            storage.data_dir() / "history.sqlite3"
        ).is_file() and not (output / ".compressor").exists()
        checks["last_report_in_app_directory"] = (storage.data_dir() / "last-run.json").is_file()
        capture("light")
        app.about()
        root.update()
        ImageGrab.grab(window=app.popup.winfo_id()).save(destination / "about-zh.png")
        app.popup.destroy()
        app.toggle_theme()
        capture("dark")
        app.show_details()
        root.update()
        checks["details_window"] = bool(app.details_window.winfo_exists())
        ImageGrab.grab(window=app.details_window.winfo_id()).save(destination / "details.png")
        app.details_window.destroy()
        app.convert()
        pump(lambda: not app.running)
        checks["resume_skips_valid_outputs"] = all(r["status"] == "skip" for r in app.results)
        app.open_settings()
        app.toggle_setting("primary_only")
        app.set_language("en")
        app.cancel_settings()
        checks["cancel_restores_language_and_options"] = (
            app.language == "zh_CN" and not app.settings["primary_only"]
        )
        app.open_settings()
        capture("settings-zh")
        app.set_language("en")
        capture("settings-en")
        app.advanced_settings()
        root.update()
        dialog = next(
            child
            for child in root.winfo_children()
            if isinstance(child, tk.Toplevel) and child.title() == app.tr("advanced")
        )
        ImageGrab.grab(window=dialog.winfo_id()).save(destination / "advanced.png")
        checks["advanced_dialog"] = dialog.winfo_exists()
        dialog.destroy()
        app.save_settings()
        checks["language_saved"] = storage.read_settings()["compact"]["language"] == "en"
        capture("english")
        app.about()
        root.update()
        checks["copyright_window"] = bool(app.popup.winfo_exists())
        ImageGrab.grab(window=app.popup.winfo_id()).save(destination / "about-en.png")

        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)

        labels = "\n".join(
            str(widget.cget("text"))
            for widget in descendants(app.popup)
            if isinstance(widget, tk.Label)
        )
        checks["about_contains_copyright_and_mit"] = (
            "Lightpress contributors" in labels and "MIT License" in labels
        )
        checks["component_list_removed_from_about"] = (
            "Pillow" not in labels and "Lucide" not in labels
        )
        checks["about_has_no_conversion_instructions"] = "Live Photo" not in labels
        with patch("compressor.storage.application_dir", return_value=Path(__file__).parents[1]):
            next(
                widget
                for widget in descendants(app.popup)
                if isinstance(widget, tk.Button) and widget.cget("text") == "Open-source components"
            ).invoke()
        root.update()
        license_window = next(
            child for child in app.popup.winfo_children() if isinstance(child, tk.Toplevel)
        )
        choices = next(
            child for child in descendants(license_window) if isinstance(child, tk.Listbox)
        )
        license_text = next(
            child for child in descendants(license_window) if isinstance(child, tk.Text)
        )
        checks["components_viewer_opens_pillow_license"] = (
            "Pillow" in license_text.get("1.0", "end") and license_text.cget("state") == "disabled"
        )
        names = choices.get(0, "end")
        checks["third_party_licenses_present"] = len(names) == 8
        checks["unique_components_without_application_license"] = len(names) == len(
            set(names)
        ) and not any("Lightpress" in name for name in names)
        ImageGrab.grab(window=license_window.winfo_id()).save(destination / "licenses-en.png")
        for index in range(choices.size()):
            choices.selection_clear(0, "end")
            choices.selection_set(index)
            choices.event_generate("<<ListboxSelect>>")
            root.update()
            if not license_text.get("1.0", "end").strip():
                raise AssertionError("Empty license text")
        license_window.destroy()
        app.popup.destroy()
        app.source.set(str(source / "旅行.jpg"))
        app.format_index = 0
        app.output.set(str(destination / "jpeg"))
        app.convert()
        pump(lambda: not app.running)
        checks["jpeg_real_conversion"] = (
            app.results[0]["status"] == "success"
            and Path(app.results[0]["output"]).suffix == ".jpg"
        )
        app.source.set(str(source / "旅行.jpg"))
        app.output.set(str(destination / "cancelled"))
        app.convert()
        app.close()
        pump(lambda: not app.running)
        checks["close_waits_for_worker"] = app.closing and not exists()
        root = None
        checks["originals_unchanged"] = all(
            hashlib.sha256((source / name).read_bytes()).hexdigest() == digest
            for name, digest in originals.items()
        )
        with patch(
            "compressor.storage.system_language",
            side_effect=AssertionError("saved language should win"),
        ):
            root = tk.Tk()
            app = CompactApp(root)
            root.update()
            checks["saved_language_overrides_system_on_restart"] = app.language == "en"
            checks["theme_and_quality_restored"] = app.theme == "dark" and app.quality == 3
            app.close()
            root = None
        checks["no_ui_callback_errors"] = not errors
    except Exception:
        import traceback

        errors.append(traceback.format_exc())
    finally:
        if exists():
            root.destroy()
        patcher.stop()
    report = dict(success=not errors and all(checks.values()), checks=checks, errors=errors)
    (destination / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report["success"]


if __name__ == "__main__":
    raise SystemExit(0 if verify(sys.argv[1] if len(sys.argv) > 1 else "artifacts/compact") else 1)
