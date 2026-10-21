"""Compact desktop interface for image and video compression."""

from __future__ import annotations

import ctypes
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog
from tkinter import font as tkfont

from PIL import Image, ImageDraw, ImageTk

from . import __version__, core, jobs, storage
from .graphics import IconCache
from .strings import LANGUAGES, QUALITY_LABELS, translate
from .formats import FORMATS
from .window_theme import apply_titlebar

FONT = "Microsoft YaHei UI"
QUALITY = QUALITY_LABELS["zh_CN"]
WINDOW_WIDTH = 453
MIN_WIDTH = WINDOW_WIDTH

PALETTES = {
    "light": {
        "bg": "#F4F6FA",
        "card": "#FFFFFF",
        "text": "#202A3C",
        "muted": "#64718A",
        "border": "#DCE2EB",
        "accent": "#3869EC",
        "hover": "#2858D8",
        "tint": "#E9EFFE",
        "track": "#DEE5F0",
        "error": "#C53F4A",
        "success": "#24816C",
        "white": "#FFFFFF",
    },
    "dark": {
        "bg": "#181D27",
        "card": "#222A38",
        "text": "#E8EDF7",
        "muted": "#98A5BD",
        "border": "#354157",
        "accent": "#91AEFF",
        "hover": "#A8BFFF",
        "tint": "#2C3B5E",
        "track": "#37445C",
        "error": "#FF9CA5",
        "success": "#7FD9BC",
        "white": "#18223A",
    },
}


class Tooltip:
    def __init__(self, root):
        self.root = root
        self.timer = None
        self.window = None
        self.text = None

    def show_later(self, text, x, y, palette):
        if text == self.text:
            return
        self.hide()
        self.text = text
        if text:
            self.timer = self.root.after(550, lambda: self._show(text, x, y, palette))

    def _show(self, text, x, y, palette):
        self.timer = None
        self.window = tk.Toplevel(self.root)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        label = tk.Label(
            self.window,
            text=text,
            font=(FONT, -12),
            bg=palette["text"],
            fg=palette["bg"],
            padx=10,
            pady=7,
            wraplength=420,
            justify="left",
        )
        label.pack()
        self.window.update_idletasks()
        left = min(x + 12, self.root.winfo_screenwidth() - self.window.winfo_width() - 12)
        top = min(y + 20, self.root.winfo_screenheight() - self.window.winfo_height() - 12)
        self.window.geometry(f"+{max(0, left)}+{max(0, top)}")

    def hide(self):
        if self.timer:
            self.root.after_cancel(self.timer)
            self.timer = None
        if self.window:
            self.window.destroy()
            self.window = None
        self.text = None


class CompactApp:
    def __init__(self, root, *, settings=None, persist=True):
        self.root = root
        self.persist = persist
        stored = storage.read_settings() if settings is None else settings
        self.theme = stored.get("theme", "light")
        if not isinstance(self.theme, str) or self.theme not in PALETTES:
            self.theme = "light"
        self.page = "main"
        self.format_index = next(
            (i for i, fmt in enumerate(FORMATS) if fmt.key == stored.get("format")), 0
        )
        quality = stored.get("quality", 3)
        self.quality = quality if isinstance(quality, int) and 0 <= quality <= 4 else 3
        self.sources = (
            [value for value in stored.get("sources", []) if isinstance(value, str)]
            if isinstance(stored.get("sources"), list)
            else []
        )
        self.source = tk.StringVar(value=stored.get("source", ""))
        self.output = tk.StringVar(value=stored.get("output", ""))
        self.status_key = "ready"
        self.status_values = {}
        self.status_kind = "accent"
        self.progress = 0
        self.running = False
        self.closing = False
        self.events = queue.Queue()
        self.cancel = core.Cancellation()
        self.worker = None
        self.tasks = []
        self.results = []
        self.logs = []
        self.current_index = 0
        self.ignored = 0
        self.details_window = None
        self.hover = None
        self.dragging = False
        self.regions = []
        self.popup = None
        self.snapshot = None
        self.rounded_cache = {}
        self.icons = IconCache(root)
        preferences = stored.get("compact", {})
        language = preferences.get("language") if isinstance(preferences, dict) else None
        self.settings = {
            "language": (
                language
                if isinstance(language, str) and language in LANGUAGES
                else storage.system_language()
            ),
            "recursive": False,
            "skip_larger": False,
            "conflict": "number",
            "keep_exif": True,
            "keep_icc": True,
            "primary_only": False,
            "include": "*",
            "exclude": "",
            "encoder": "cpu",
            "fps": "原始帧率",
        }
        if isinstance(preferences, dict):
            for key, default in self.settings.items():
                if isinstance(preferences.get(key), type(default)):
                    self.settings[key] = preferences[key]
        if self.settings["language"] not in LANGUAGES:
            self.settings["language"] = storage.system_language()
        if self.settings["conflict"] not in ("number", "skip"):
            self.settings["conflict"] = "number"
        if self.settings["encoder"] not in ("cpu", "nvidia"):
            self.settings["encoder"] = "cpu"
        self.titlebar_result = {}
        root.title(self.tr("window_title"))
        root.geometry(f"{WINDOW_WIDTH}x520")
        root.minsize(MIN_WIDTH, 520)
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.close)
        try:
            base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
            root.iconbitmap(str(base / "assets" / "app.ico"))
        except tk.TclError:
            pass
        self.canvas = tk.Canvas(root, bd=0, highlightthickness=0, takefocus=True)
        self.canvas.pack(fill="both", expand=True)
        self.entries = []
        for variable, placeholder in (
            (self.source, "input_placeholder"),
            (self.output, "output_placeholder"),
        ):
            entry = tk.Entry(
                self.canvas,
                textvariable=variable,
                font=(FONT, -14),
                bd=0,
                relief="flat",
                highlightthickness=0,
                insertwidth=1,
            )
            entry.bind("<Enter>", lambda event, v=variable: self._path_tip(event, v.get()))
            entry.bind("<Leave>", lambda _: self.tooltip.hide())
            self.entries.append((entry, placeholder))
        self.tooltip = Tooltip(root)
        self.canvas.bind("<Configure>", lambda _: self.draw())
        self.canvas.bind("<Motion>", self.motion)
        self.canvas.bind("<Leave>", self.leave)
        self.canvas.bind("<Button-1>", self.click)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind("<ButtonRelease-1>", self.release)
        self.canvas.bind("<Left>", lambda _: self.change_quality(-1))
        self.canvas.bind("<Right>", lambda _: self.change_quality(1))
        root.bind("<Control-o>", lambda _: self.choose_files())
        root.bind("<Control-Shift-O>", lambda _: self.choose_folder())
        root.bind(
            "<Control-Return>",
            lambda _: self.save_settings() if self.page == "settings" else self.convert(),
        )
        root.bind("<Escape>", self.escape)
        root.bind("<Map>", lambda event: self.update_titlebar() if event.widget == root else None)
        self.draw()
        root.after_idle(self.update_titlebar)
        self.poll_timer = root.after(70, self.poll)
        self.persist_settings()

    @property
    def palette(self):
        return PALETTES[self.theme]

    @property
    def selected_format(self):
        return FORMATS[self.format_index]

    @property
    def format_name(self):
        return (
            self.tr("automatic")
            if self.selected_format.key == "auto"
            else self.selected_format.name
        )

    @property
    def language(self):
        return self.settings["language"]

    @property
    def quality_labels(self):
        return QUALITY_LABELS[self.language]

    @property
    def status(self):
        return self.tr(self.status_key, **self.status_values)

    def tr(self, key, **values):
        return translate(self.language, key, **values)

    def update_titlebar(self):
        self.titlebar_result = apply_titlebar(
            self.root, self.theme == "dark", self.palette["bg"], self.palette["text"]
        )
        if self.popup and self.popup.winfo_exists():
            apply_titlebar(
                self.popup, self.theme == "dark", self.palette["card"], self.palette["text"]
            )

    def text(self, x, y, value, size=14, color="text", bold=False, anchor="w", **kwargs):
        return self.canvas.create_text(
            x,
            y,
            text=value,
            font=(FONT, -size, "bold" if bold else "normal"),
            fill=self.palette.get(color, color),
            anchor=anchor,
            **kwargs,
        )

    def rounded(self, x1, y1, x2, y2, radius=12, fill="card", outline=None):
        width, height = round(x2 - x1), round(y2 - y1)
        color = self.palette[fill]
        stroke = self.palette[outline] if outline else None
        key = (width, height, radius, color, stroke)
        if key not in self.rounded_cache:
            image = Image.new("RGBA", (width * 3, height * 3))
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle(
                (1, 1, width * 3 - 2, height * 3 - 2),
                radius=radius * 3,
                fill=color,
                outline=stroke,
                width=3 if stroke else 1,
            )
            image = image.resize((width, height), Image.Resampling.LANCZOS)
            self.rounded_cache[key] = ImageTk.PhotoImage(image, master=self.root)
        return self.canvas.create_image(x1, y1, anchor="nw", image=self.rounded_cache[key])

    def hit(self, name, bounds, callback, tip=None):
        self.regions.append((name, bounds, callback, tip))

    def icon(self, x, y, name, color="muted"):
        asset = {
            "file": "file-text",
            "gear": "settings",
            "i": "info",
            "arrow": "chevron-right",
            "chevron": "chevron-down",
        }.get(name, name)
        size = 18 if name in ("arrow", "chevron") else 24
        self.canvas.create_image(
            round(x), round(y), image=self.icons.get(asset, self.palette[color], size)
        )

    def icon_button(self, x, y, name, role, callback, tip):
        self.rounded(
            x - 18,
            y - 18,
            x + 18,
            y + 18,
            18,
            fill="tint" if self.hover == role else "card",
            outline="border",
        )
        self.icon(
            x,
            y,
            name,
            "accent" if self.hover == role else "muted",
        )
        self.hit(role, (x - 18, y - 18, x + 18, y + 18), callback, tip)

    def draw(self):
        self.canvas.delete("all")
        if len(self.rounded_cache) > 128:
            self.rounded_cache.clear()
        self.canvas.configure(bg=self.palette["bg"])
        self.root.title(self.tr("window_title"))
        self.regions = []
        self.width = max(MIN_WIDTH, self.canvas.winfo_width())
        self.height = max(520, self.canvas.winfo_height())
        if self.page == "settings":
            self.draw_settings()
        else:
            self.draw_main()

    def draw_main(self):
        w, h = self.width, self.height
        left, right = 30, w - 30
        self.rounded(left, 26, left + 32, 58, 10, "accent")
        self.canvas.create_line(
            left + 10,
            34,
            left + 10,
            39,
            left + 15,
            39,
            fill=self.palette["white"],
            width=2.4,
            joinstyle="miter",
        )
        self.canvas.create_line(
            left + 17,
            45,
            left + 22,
            45,
            left + 22,
            50,
            fill=self.palette["white"],
            width=2.4,
            joinstyle="miter",
        )
        self.text(left + 44, 41, self.tr("app_name"), size=21, bold=True)
        self.text(
            left + (100 if self.language == "zh_CN" else 164),
            43,
            __version__,
            size=12,
            color="muted",
        )
        self.icon_button(
            right - 116,
            42,
            "moon" if self.theme == "light" else "sun",
            "theme",
            self.toggle_theme,
            self.tr("dark_theme" if self.theme == "light" else "light_theme"),
        )
        self.icon_button(right - 67, 42, "i", "about", self.about, self.tr("about_tip"))
        self.icon_button(
            right - 18, 42, "gear", "settings", self.open_settings, self.tr("settings")
        )

        for index, (title, role, command, tip) in enumerate(
            (
                ("input_path", "source_folder", self.choose_folder, "choose_folder"),
                ("output_path", "output", self.choose_output, "choose_output"),
            )
        ):
            top = 108 + index * 94
            self.text(left, top - 16, self.tr(title), size=13, color="muted")
            self.rounded(left, top, right, top + 49, 12, outline="border")
            entry, placeholder = self.entries[index]
            entry.configure(
                bg=self.palette["card"],
                fg=self.palette["text"],
                insertbackground=self.palette["accent"],
                disabledforeground=self.palette["muted"],
                state="disabled" if self.running else "normal",
            )
            self.canvas.create_window(
                left + 16,
                top + 24,
                window=entry,
                anchor="w",
                width=right - left - (126 if index == 0 else 84),
                height=26,
            )
            if not entry.get() and self.root.focus_get() != entry:
                placeholder_widget = getattr(entry, "placeholder", None)
                if placeholder_widget is None:
                    placeholder_widget = tk.Label(entry, bd=0, font=(FONT, -14), anchor="w")
                    placeholder_widget.bind("<Button-1>", lambda _, e=entry: e.focus_set())
                    entry.placeholder = placeholder_widget
                    entry.bind(
                        "<FocusIn>",
                        lambda _, e=entry: (e.placeholder.place_forget(), self.tooltip.hide()),
                    )
                    entry.bind("<FocusOut>", lambda _: self.draw())
                placeholder_widget.configure(
                    text=self.tr(placeholder), bg=self.palette["card"], fg=self.palette["muted"]
                )
                placeholder_widget.place(x=0, y=0, relwidth=1, relheight=1)
            elif hasattr(entry, "placeholder"):
                entry.placeholder.place_forget()
            bx = right - 27
            self.rounded(
                bx - 18, top + 7, bx + 18, top + 42, 9, "tint" if self.hover == role else "bg"
            )
            self.icon(bx, top + 23, "folder", "accent")
            self.hit(role, (right - 48, top, right, top + 49), command, self.tr(tip))
            if index == 0:
                file_x = right - 69
                self.rounded(
                    file_x - 18,
                    top + 7,
                    file_x + 18,
                    top + 42,
                    9,
                    "tint" if self.hover == "source_files" else "bg",
                )
                self.icon(file_x, top + 24, "file", "accent")
                self.hit(
                    "source_files",
                    (right - 90, top, right - 48, top + 49),
                    self.choose_files,
                    self.tr("choose_files"),
                )

        quality_top = 282
        self.text(left, quality_top, self.tr("output_quality"), size=13, color="muted")
        self.text(
            right,
            quality_top,
            self.quality_labels[self.quality],
            size=13,
            color="accent",
            bold=True,
            anchor="e",
        )
        self.slider_left, self.slider_right = left + 14, right - 14
        sy = quality_top + 31
        selected_x = round(
            self.slider_left + (self.slider_right - self.slider_left) * self.quality / 4
        )
        self.canvas.create_line(
            self.slider_left,
            sy,
            self.slider_right,
            sy,
            fill=self.palette["track"],
            width=4,
            capstyle="round",
        )
        if self.quality:
            self.canvas.create_line(
                self.slider_left,
                sy,
                selected_x,
                sy,
                fill=self.palette["accent"],
                width=4,
                capstyle="round",
            )
        for index, name in enumerate(self.quality_labels):
            x = round(self.slider_left + (self.slider_right - self.slider_left) * index / 4)
            self.canvas.create_image(
                x,
                sy,
                image=self.icons.get(
                    "quality-tick", self.palette["accent" if index <= self.quality else "track"], 6
                ),
            )
            self.text(
                x,
                sy + 28,
                name,
                size=15 if index == self.quality else 12,
                color="accent" if index == self.quality else "muted",
                bold=index == self.quality,
                anchor="center",
            )
        self.canvas.create_image(
            selected_x,
            sy,
            image=self.icons.get("quality-thumb", self.palette["accent"], 24, self.palette["card"]),
        )
        self.hit(
            "quality",
            (left, sy - 16, right, sy + 42),
            self.set_quality_at,
            self.tr("quality_tip")
            + "\n"
            + self.selected_format.quality_text(self.quality, self.language),
        )

        bottom = h - 125
        self.text(left, bottom - 16, self.tr("output_format"), size=13, color="muted")
        button_left = right - 160
        self.rounded(
            left,
            bottom,
            button_left - 14,
            bottom + 48,
            12,
            "tint" if self.hover == "format" else "card",
            "border",
        )
        fmt = self.selected_format
        self.text(left + 16, bottom + 24, self.format_name, size=15, bold=True)
        self.text(
            left + (92 if fmt.kind == "videos" else 82),
            bottom + 24,
            fmt.suffix.upper() if fmt.suffix else "AVIF / MP4",
            size=12,
            color="muted",
        )
        self.icon(button_left - 37, bottom + 24, "chevron")
        self.hit(
            "format",
            (left, bottom, button_left - 14, bottom + 48),
            self.format_menu,
            self.tr(
                "format_tip",
                name=self.format_name,
                suffix=fmt.suffix,
                description=self.tr(fmt.description),
            ),
        )
        self.rounded(
            button_left,
            bottom,
            right,
            bottom + 48,
            12,
            "hover" if self.hover == "convert" else "accent",
        )
        self.text(
            (button_left + right) / 2 - 6,
            bottom + 24,
            self.tr("cancel" if self.running else "convert"),
            size=15,
            color="white",
            bold=True,
            anchor="center",
        )
        if not self.running:
            self.icon(right - 26, bottom + 24, "arrow", "white")
        self.hit(
            "convert",
            (button_left, bottom, right, bottom + 48),
            self.convert,
            self.tr("cancel_tip" if self.running else "convert_tip"),
        )
        status_y = h - 33
        self.canvas.create_oval(
            left,
            status_y - 3,
            left + 6,
            status_y + 3,
            fill=self.palette[self.status_kind],
            outline="",
        )
        self.text(
            left + 16,
            status_y,
            self.ellipsize(self.status, right - left - 70),
            size=12,
            color=self.status_kind,
        )
        if self.running or self.progress:
            self.text(
                right, status_y, f"{self.progress}%", size=12, color=self.status_kind, anchor="e"
            )
        self.hit(
            "status",
            (left, status_y - 14, right, status_y + 14),
            self.show_details,
            self.status + "\n" + self.tr("details_tip"),
        )
        self.canvas.create_line(
            left, h - 10, right, h - 10, fill=self.palette["track"], width=3, capstyle="round"
        )
        if self.progress:
            self.canvas.create_line(
                left,
                h - 10,
                left + (right - left) * self.progress / 100,
                h - 10,
                fill=self.palette[self.status_kind],
                width=3,
                capstyle="round",
            )

    def draw_settings(self):
        w, h = self.width, self.height
        left, right = 30, w - 30
        self.text(left, 42, self.tr("settings"), size=21, bold=True)
        self.text(
            left + (62 if self.language == "zh_CN" else 100),
            44,
            self.tr("settings_scope"),
            size=12,
            color="muted",
        )
        self.text(left, 88, self.tr("general"), size=13, color="muted")
        self.rounded(left, 105, right, 281, outline="border")
        self.text(left, 303, self.tr("images"), size=13, color="muted")
        self.rounded(left, 320, right, 452, outline="border")
        rows = (
            ("language", 127),
            ("recursive", 171),
            ("skip_larger", 215),
            ("conflict", 259),
            ("keep_exif", 342),
            ("keep_icc", 386),
            ("primary_only", 430),
        )
        for key, y in rows:
            if key not in ("language", "keep_exif"):
                self.canvas.create_line(
                    left + 16, y - 22, right - 16, y - 22, fill=self.palette["border"], width=1
                )
            self.text(left + 18, y, self.tr(key), size=14)
            if key in ("conflict", "language"):
                value = (
                    LANGUAGES[self.language] if key == "language" else self.tr(self.settings[key])
                )
                self.text(right - 40, y, value, size=13, color="accent", anchor="e")
                self.icon(right - 22, y, "chevron", "accent")
            else:
                on = self.settings[key]
                self.rounded(
                    right - 58, y - 11, right - 18, y + 11, 11, "accent" if on else "track"
                )
                cx = right - 29 if on else right - 47
                self.canvas.create_oval(cx - 8, y - 8, cx + 8, y + 8, fill="#FFFFFF", outline="")
            self.hit(
                key,
                (left + 8, y - 21, right - 8, y + 21),
                self.language_menu if key == "language" else lambda k=key: self.toggle_setting(k),
                self.tr(key + "_tip"),
            )
        self.rounded(right - 206, h - 57, right - 118, h - 11, 12, "card", "border")
        self.text(left, h - 34, self.tr("advanced"), size=13, color="accent")
        self.hit(
            "advanced",
            (left, h - 57, right - 218, h - 11),
            self.advanced_settings,
            self.tr("advanced_tip"),
        )
        self.text(right - 162, h - 34, self.tr("cancel"), size=14, anchor="center")
        self.hit(
            "cancel-settings",
            (right - 206, h - 57, right - 118, h - 11),
            self.cancel_settings,
            self.tr("cancel_settings_tip"),
        )
        self.rounded(right - 106, h - 57, right, h - 11, 12, "accent")
        self.text(
            right - 53,
            h - 34,
            self.tr("save_return"),
            size=14,
            color="white",
            bold=True,
            anchor="center",
        )
        self.hit(
            "save-settings",
            (right - 106, h - 57, right, h - 11),
            self.save_settings,
            self.tr("save_settings_tip"),
        )

    def region_at(self, x, y):
        return next(
            (r for r in self.regions if r[1][0] <= x <= r[1][2] and r[1][1] <= y <= r[1][3]), None
        )

    def motion(self, event):
        region = self.region_at(event.x, event.y)
        role = region[0] if region else None
        if self.hover != role:
            self.hover = role
            self.draw()
        self.canvas.configure(cursor="hand2" if region else "")
        self.tooltip.show_later(
            region[3] if region else None, event.x_root, event.y_root, self.palette
        )

    def leave(self, _=None):
        self.tooltip.hide()
        if self.hover:
            self.hover = None
            self.draw()

    def click(self, event):
        self.tooltip.hide()
        self.canvas.focus_set()
        region = self.region_at(event.x, event.y)
        if not region:
            return
        if region[0] == "quality":
            self.dragging = not self.running
            self.set_quality_at(event.x)
        else:
            region[2]()

    def drag(self, event):
        if self.dragging:
            self.set_quality_at(event.x)

    def release(self, _):
        self.dragging = False

    def set_quality_at(self, x=None):
        if x is not None and not self.running:
            self.quality = max(
                0,
                min(
                    4,
                    int((x - self.slider_left) / (self.slider_right - self.slider_left) * 4 + 0.5),
                ),
            )
            self.quality_feedback()

    def change_quality(self, delta):
        if self.page == "main" and not self.running:
            self.quality = max(0, min(4, self.quality + delta))
            self.quality_feedback()

    def quality_feedback(self):
        fmt = self.selected_format
        self.feedback(
            "format_status",
            name=self.format_name,
            suffix=fmt.suffix,
            quality=self.quality_labels[self.quality],
        )

    def _path_tip(self, event, value):
        self.tooltip.show_later(value, event.x_root, event.y_root, self.palette)

    def toggle_theme(self):
        self.theme = "dark" if self.theme == "light" else "light"
        self.draw()
        self.update_titlebar()
        self.persist_settings()

    def menu(self):
        p = self.palette
        return tk.Menu(
            self.root,
            tearoff=False,
            bg=p["card"],
            fg=p["text"],
            activebackground=p["tint"],
            activeforeground=p["accent"],
            disabledforeground=p["muted"],
            font=(FONT, -14),
            bd=0,
            activeborderwidth=0,
        )

    def choose_files(self):
        if self.running or self.page != "main":
            return
        paths = filedialog.askopenfilenames(
            parent=self.root,
            title=self.tr("media_dialog"),
            filetypes=[
                (
                    self.tr("media_files"),
                    "*.jpg *.jpeg *.png *.webp *.avif *.heic *.mp4 *.mov *.mkv *.avi *.webm",
                ),
                (self.tr("all_files"), "*.*"),
            ],
        )
        if paths:
            self.set_sources(list(paths))

    def choose_folder(self):
        if self.running or self.page != "main":
            return
        path = filedialog.askdirectory(parent=self.root, title=self.tr("input_dialog"))
        if path:
            self.set_sources([path])

    def set_sources(self, paths):
        self.sources = paths
        self.source.set(self.source_display())
        self.entries[0][0].xview_moveto(0)
        first = Path(paths[0])
        if not self.output.get():
            self.output.set(
                str((first if first.is_dir() else first.parent) / self.tr("output_folder"))
            )
            self.entries[1][0].xview_moveto(0)
        if first.suffix.lower() in core.VIDEO_EXTS and self.selected_format.kind == "images":
            self.format_index = 4
        self.status_key = "selected_many" if len(paths) > 1 else "selected_source"
        self.status_values = {"count": len(paths)}
        self.status_kind = "accent"
        self.progress = 0
        self.draw()

    def source_display(self):
        if not self.sources:
            return ""
        return self.sources[0] + (
            self.tr("selection_count", count=len(self.sources)) if len(self.sources) > 1 else ""
        )

    def choose_output(self):
        if self.running:
            return
        path = filedialog.askdirectory(parent=self.root, title=self.tr("output_dialog"))
        if path:
            self.output.set(path)
            self.entries[1][0].xview_moveto(0)
            self.draw()

    def format_menu(self):
        if self.running:
            return
        menu = self.menu()
        for kind in ("images", "videos"):
            if kind == "videos":
                menu.add_separator()
            menu.add_command(label=f"  {self.tr(kind)}", state="disabled", font=(FONT, -12))
            for index, fmt in enumerate(FORMATS):
                if fmt.kind != kind:
                    continue
                menu.add_command(
                    label=f"{'✓' if index == self.format_index else '  '}   {fmt.name}   {fmt.suffix}",
                    command=lambda i=index: self.select_format(i),
                    font=(
                        FONT,
                        -15 if index == self.format_index else -14,
                        "bold" if index == self.format_index else "normal",
                    ),
                )
        menu.add_separator()
        menu.add_command(
            label=self.tr("automatic") + " · AVIF / H.264",
            command=lambda: self.select_format(len(FORMATS) - 1),
        )
        menu.tk_popup(self.root.winfo_rootx() + 30, self.root.winfo_rooty() + self.height - 77)

    def select_format(self, index):
        self.format_index = index
        self.quality_feedback()

    def open_settings(self):
        if self.running:
            return
        self.snapshot = self.settings.copy()
        self.page = "settings"
        self.hover = None
        self.tooltip.hide()
        self.draw()

    def toggle_setting(self, key):
        self.settings[key] = (
            ("skip" if self.settings[key] == "number" else "number")
            if key == "conflict"
            else not self.settings[key]
        )
        self.draw()

    def language_menu(self):
        menu = self.menu()
        for key, name in LANGUAGES.items():
            menu.add_command(
                label=("✓  " if key == self.language else "    ") + name,
                command=lambda value=key: self.set_language(value),
            )
        menu.tk_popup(self.root.winfo_rootx() + self.width - 200, self.root.winfo_rooty() + 149)

    def set_language(self, language):
        if language not in LANGUAGES:
            return
        display_selected = bool(self.sources and self.source.get() == self.source_display())
        self.settings["language"] = language
        if display_selected:
            self.source.set(self.source_display())
        if self.status_key in ("format_status", "converting"):
            self.status_values["quality"] = self.quality_labels[self.quality]
        self.tooltip.hide()
        self.hover = None
        self.draw()

    def save_settings(self):
        self.snapshot = None
        self.page = "main"
        self.hover = None
        self.draw()
        self.persist_settings()

    def cancel_settings(self):
        if self.snapshot is not None:
            display_selected = bool(self.sources and self.source.get() == self.source_display())
            self.settings = self.snapshot
            if display_selected:
                self.source.set(self.source_display())
            if self.status_key in ("format_status", "converting"):
                self.status_values["quality"] = self.quality_labels[self.quality]
        self.save_settings()

    def about(self):
        if self.popup and self.popup.winfo_exists():
            self.popup.lift()
            return
        from .about import show_about

        self.popup = show_about(self.root, self.palette, self.language, self.theme == "dark")

    def persist_settings(self):
        if not self.persist:
            return True
        try:
            stored = storage.read_settings()
            stored.update(
                theme=self.theme,
                format=self.selected_format.key,
                quality=self.quality,
                source=self.source.get(),
                output=self.output.get(),
                sources=self.sources,
                compact=self.settings.copy(),
                version=__version__,
            )
            storage.save_settings(stored)
            return True
        except OSError as error:
            self.logs.append(str(error))
            self.feedback("settings_write_failed", "error", path=str(storage.data_dir()))
            return False

    def ellipsize(self, value, width):
        font = tkfont.Font(self.root, family=FONT, size=-12)
        if font.measure(value) <= width:
            return value
        while value and font.measure(value + "…") > width:
            value = value[:-1]
        return value + "…"

    def show_details(self):
        from .dialogs import show_details

        show_details(self)

    def advanced_settings(self):
        from .dialogs import advanced_settings

        advanced_settings(self)

    def convert(self):
        if self.running:
            self.cancel_conversion()
            return
        if self.page != "main":
            return
        source = self.source.get().strip()
        paths = (
            self.sources.copy() if self.sources and source == self.source_display() else [source]
        )
        if not source:
            self.feedback("missing_source", "error")
            return
        if any(not Path(path).expanduser().exists() for path in paths):
            self.feedback("invalid_source", "error")
            return
        if not self.output.get().strip():
            self.feedback("missing_output", "error")
            return
        self.cancel = core.Cancellation()
        self.tasks, self.results, self.logs = [], [], []
        self.current_index, self.ignored = 0, 0
        self.progress = 0
        self.persist_settings()
        self.running = True
        self.status_kind, self.status_key, self.status_values = "accent", "scanning", {}
        self.draw()
        parameters = (
            paths,
            self.output.get().strip(),
            self.selected_format.key,
            self.quality,
            self.settings.copy(),
            self.cancel,
            lambda kind, value: self.events.put((kind, value)),
        )
        self.worker = threading.Thread(
            target=jobs.run, args=parameters, name="compression", daemon=False
        )
        self.worker.start()

    def poll(self):
        self.poll_timer = None
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "prepared":
                    self.tasks, self.ignored = value["tasks"], value["ignored"]
                    if self.ignored:
                        self.logs.append(self.tr("ignored_count", count=self.ignored))
                elif kind == "current":
                    self.current_index = value["index"]
                    if not self.cancel.event.is_set():
                        self.status_key = "processing"
                        self.status_values = dict(
                            index=self.current_index + 1, total=len(self.tasks), name=value["name"]
                        )
                elif kind == "fraction":
                    self.progress = min(
                        99,
                        int(
                            (self.current_index + value["fraction"]) / max(1, len(self.tasks)) * 100
                        ),
                    )
                elif kind == "result":
                    value = value.copy()
                    value["name"] = self.tasks[value["index"]].relative.as_posix()
                    self.results.append(value)
                    self.progress = int(len(self.results) / max(1, len(self.tasks)) * 100)
                elif kind == "log":
                    self.logs.append(value["message"])
                elif kind == "finished":
                    self.running = False
                    counts = value["counts"]
                    self.status_kind = (
                        "accent"
                        if value["cancelled"]
                        else "error" if counts.get("error", 0) else "success"
                    )
                    self.status_key = "stopped" if value["cancelled"] else "finished"
                    self.status_values = dict(
                        success=counts.get("success", 0),
                        skipped=counts.get("skip", 0) + counts.get("larger", 0),
                        errors=counts.get("error", 0),
                    )
                    if not value["cancelled"]:
                        self.progress = 100
                    self.save_report(value)
                    if self.closing:
                        self.close()
                        return
                elif kind == "fatal":
                    self.running = False
                    self.status_key = value.get("code", "job_failed")
                    self.status_values = {}
                    self.status_kind = "error"
                    self.logs.append(value.get("message", ""))
                    self.save_report(value)
                    if self.closing:
                        self.close()
                        return
                self.draw()
        except queue.Empty:
            pass
        self.poll_timer = self.root.after(70, self.poll)

    def save_report(self, summary):
        if not self.persist:
            return
        try:
            storage.write_json(
                storage.data_dir() / "last-run.json",
                dict(version=__version__, results=self.results, logs=self.logs, summary=summary),
            )
        except OSError as error:
            self.logs.append(str(error))

    def feedback(self, key, kind="accent", **values):
        self.status_key, self.status_values = key, values
        self.status_kind, self.progress = kind, 0
        self.draw()

    def cancel_conversion(self):
        if not self.running:
            return
        self.cancel.cancel()
        self.status_key, self.status_values = "stopping", {}
        self.status_kind = "accent"
        self.draw()

    def escape(self, _=None):
        if self.page == "settings":
            self.cancel_settings()
        elif self.running:
            self.cancel_conversion()

    def close(self):
        self.tooltip.hide()
        if self.running:
            self.closing = True
            self.cancel_conversion()
            return
        if self.page == "settings":
            self.cancel_settings()
        self.persist_settings()
        if self.poll_timer:
            self.root.after_cancel(self.poll_timer)
            self.poll_timer = None
        self.root.destroy()


def main():
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    CompactApp(root)
    root.mainloop()
