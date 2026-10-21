"""Desktop interface."""

from __future__ import annotations

import ctypes
import dataclasses
import os
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageOps, ImageTk

from . import __version__, core
from .theme import THEMES

CODECS = {"AV1 (CPU)": "av1_cpu", "AV1 (NVIDIA)": "av1_gpu", "H.265 (NVIDIA)": "h265_gpu"}
STATUS = {
    "success": "已完成",
    "skip": "已跳过",
    "larger": "未变小",
    "error": "失败",
    "cancel": "已停止",
}
FONT = "Microsoft YaHei UI"


def size_text(size):
    if size >= 1024**3:
        return f"{size / 1024**3:.2f} GiB"
    if size >= 1024**2:
        return f"{size / 1024**2:.1f} MiB"
    return f"{size / 1024:.1f} KiB"


class App:
    def __init__(self, root: tk.Tk, *, settings=None, persist=True):
        self.root = root
        self.persist = persist
        stored = core.read_settings() if settings is None else settings
        self.theme = stored.get("theme", "light")
        if self.theme not in THEMES:
            self.theme = "light"
        self.tasks = []
        self.results = {}
        self.events = queue.Queue()
        self.cancel = core.Cancellation()
        self.busy = False
        self.options_open = False
        self.options_snapshot = None
        self.closing = False
        self.mode = stored.get("mode", "all")
        if self.mode not in ("all", "image", "video"):
            self.mode = "all"
        self.logs = []
        self.log_window = None
        self.log_text = None
        self.caps = {}
        self.colors = []
        self.buttons = []
        self.mode_buttons = {}
        self.inputs = []
        self.option_vars = {}
        self.current_index = 0
        self.preview_image = None
        self.worker = None
        self.root.title(f"轻压 {__version__}")
        screen_width, screen_height = root.winfo_screenwidth(), root.winfo_screenheight()
        width = min(1160, max(980, screen_width - 80))
        height = min(780, max(640, screen_height - 100))
        left, top = (screen_width - width) // 2, max(0, (screen_height - height) // 2 - 20)
        self.root.geometry(f"{width}x{height}+{left}+{top}")
        self.root.minsize(980, 640)
        self.root.option_add("*Font", (FONT, 10))
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        try:
            base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
            self.root.iconbitmap(str(base / "assets" / "app.ico"))
        except tk.TclError:
            pass
        self.source = tk.StringVar(value=stored.get("source", ""))
        self.output = tk.StringVar(value=stored.get("output", ""))
        self.include = tk.StringVar(value=stored.get("include", "*"))
        self.exclude = tk.StringVar(value=stored.get("exclude", ""))
        self.recursive = tk.BooleanVar(value=stored.get("recursive", True))
        self.filters_open = False
        values = stored.get("options", {})
        if not isinstance(values, dict):
            values = {}
        defaults = core.Options()
        for field in dataclasses.fields(defaults):
            default = getattr(defaults, field.name)
            kind = tk.BooleanVar if isinstance(default, bool) else tk.StringVar
            self.option_vars[field.name] = kind(value=values.get(field.name, default))
        self.codec_label = tk.StringVar(
            value=next(
                (k for k, v in CODECS.items() if v == self.option_vars["codec"].get()),
                next(iter(CODECS)),
            )
        )
        self.rate_label = tk.StringVar(
            value="恒定质量" if self.option_vars["rate_mode"].get() == "quality" else "指定码率"
        )
        self.bytes_var = tk.StringVar(value="—")
        self.summary_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="就绪")
        self.progress_var = tk.DoubleVar(value=0)
        self.detail_var = tk.StringVar(value="")
        self.cap_var = tk.StringVar(value="检查运行环境…")
        self._build()
        self.apply_theme()
        self.root.after(80, self.poll)
        threading.Thread(target=self._check_capabilities, daemon=True).start()

    def paint(self, widget, **tokens):
        self.colors.append((widget, tokens))
        return widget

    def frame(self, parent, *, surface="card", **kw):
        widget = tk.Frame(parent, **kw)
        self.paint(widget, bg=surface)
        return widget

    def label(
        self, parent, text=None, *, variable=None, muted=False, font=None, surface="card", **kw
    ):
        widget = tk.Label(parent, text=text, textvariable=variable, font=font or (FONT, 10), **kw)
        self.paint(widget, bg=surface, fg="muted" if muted else "text")
        return widget

    def button(self, parent, text, command, *, primary=False, compact=False):
        widget = tk.Button(
            parent,
            text=text,
            command=command,
            relief="flat",
            bd=0,
            cursor="hand2",
            padx=14 if compact else 20,
            pady=5 if compact else 10,
            font=(FONT, 10),
            takefocus=True,
            highlightthickness=1,
        )
        self.buttons.append((widget, primary))
        return widget

    def card(self, parent, **kw):
        widget = self.frame(parent, highlightthickness=1, bd=0, **kw)
        self.paint(widget, bg="card", highlightbackground="border", highlightcolor="border")
        return widget

    def entry(self, parent, var, width=None):
        widget = ttk.Entry(parent, textvariable=var, width=width, style="Studio.TEntry")
        self.inputs.append((widget, "normal"))
        return widget

    def combo(self, parent, var, values, width=None):
        widget = ttk.Combobox(
            parent,
            textvariable=var,
            values=values,
            state="readonly",
            width=width,
            style="Studio.TCombobox",
        )
        self.inputs.append((widget, "readonly"))
        return widget

    def check(self, parent, text, var):
        widget = ttk.Checkbutton(parent, text=text, variable=var, style="Studio.TCheckbutton")
        self.inputs.append((widget, "normal"))
        return widget

    def _build(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        content = self.frame(self.root, surface="bg")
        self.main_page = content
        content.grid(row=0, column=0, sticky="nsew", padx=16, pady=12)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(2, weight=1)

        toolbar = self.frame(content, surface="bg")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self.label(toolbar, "批量压缩", font=(FONT, 13, "bold"), surface="bg").pack(side="left")
        self.button(toolbar, "帮助", self.about, compact=True).pack(side="right")
        self.button(toolbar, "日志", self.show_logs, compact=True).pack(side="right", padx=6)
        self.options_btn = self.button(toolbar, "选项", self.show_options, compact=True)
        self.options_btn.pack(side="right", padx=(6, 0))
        self.theme_btn = self.button(toolbar, "", self.toggle_theme, compact=True)
        self.theme_btn.pack(side="right")

        source_card = self.card(content)
        source_card.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        source_card.columnconfigure(1, weight=1)
        self.label(source_card, "来源").grid(
            row=0, column=0, padx=(12, 10), pady=(12, 6), sticky="w"
        )
        self.entry(source_card, self.source).grid(row=0, column=1, sticky="ew", pady=(12, 6))
        self.source_btn = self.button(source_card, "浏览…", self.browse_source, compact=True)
        self.source_btn.grid(row=0, column=2, padx=(8, 12), pady=(12, 6))
        self.label(source_card, "输出").grid(
            row=1, column=0, padx=(12, 10), pady=(0, 6), sticky="w"
        )
        self.entry(source_card, self.output).grid(row=1, column=1, sticky="ew", pady=(0, 6))
        self.output_btn = self.button(source_card, "浏览…", self.browse_output, compact=True)
        self.output_btn.grid(row=1, column=2, padx=(8, 12), pady=(0, 6))
        source_actions = self.frame(source_card)
        source_actions.grid(row=2, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 8))
        self.check(source_actions, "包含子文件夹", self.recursive).pack(side="left")
        self.filters_btn = self.button(
            source_actions, "文件筛选", self.toggle_filters, compact=True
        )
        self.filters_btn.pack(side="left", padx=12)
        self.scan_btn = self.button(source_actions, "扫描", self.scan, compact=True)
        self.scan_btn.pack(side="right")
        self.filter_frame = self.frame(source_card)
        for column in (1, 3):
            self.filter_frame.columnconfigure(column, weight=1)
        self.label(self.filter_frame, "包含").grid(row=0, column=0, padx=(0, 8))
        self.entry(self.filter_frame, self.include, width=16).grid(row=0, column=1, sticky="ew")
        self.label(self.filter_frame, "排除").grid(row=0, column=2, padx=(15, 8))
        self.entry(self.filter_frame, self.exclude, width=16).grid(row=0, column=3, sticky="ew")
        self.label(
            self.filter_frame,
            "例：*.jpg;*.mov  或  re:^IMG_。排除条件优先。",
            font=(FONT, 9),
            muted=True,
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))

        middle = self.frame(content, surface="bg")
        middle.grid(row=2, column=0, sticky="nsew")
        middle.columnconfigure(0, weight=1)
        middle.rowconfigure(0, weight=1)
        task_card = self.card(middle)
        task_card.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        task_card.columnconfigure(0, weight=1)
        task_card.rowconfigure(1, weight=1)
        queue_bar = self.frame(task_card)
        queue_bar.grid(row=0, column=0, sticky="ew", padx=10, pady=8)
        for key, title in [("all", "全部"), ("image", "图片"), ("video", "视频")]:
            button = self.button(
                queue_bar, title, lambda mode=key: self.select_mode(mode), compact=True
            )
            button.pack(side="left", padx=(0, 4))
            self.mode_buttons[key] = button
        self.queue_summary = tk.StringVar(value="0 个文件")
        self.label(queue_bar, variable=self.queue_summary, font=(FONT, 9), muted=True).pack(
            side="right", padx=4
        )

        table = self.frame(task_card)
        table.grid(row=1, column=0, sticky="nsew", padx=10)
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            table,
            columns=("name", "kind", "size", "result", "status"),
            show="headings",
            selectmode="browse",
            style="Studio.Treeview",
        )
        columns = [
            ("name", "文件", 230, "w"),
            ("kind", "类型", 50, "center"),
            ("size", "原始大小", 80, "e"),
            ("result", "输出大小", 80, "e"),
            ("status", "状态", 78, "center"),
        ]
        for key, title, width, anchor in columns:
            self.tree.heading(key, text=title, anchor=anchor)
            self.tree.column(
                key,
                width=width,
                minwidth=width if key != "name" else 150,
                anchor=anchor,
                stretch=key == "name",
            )
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(
            table, orient="vertical", command=self.tree.yview, style="Studio.Vertical.TScrollbar"
        )
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", self.selected)
        self.empty = self.frame(table)
        self.empty.place(relx=0.5, rely=0.5, anchor="center")
        self.empty_title = self.label(self.empty, "未添加文件", font=(FONT, 12, "bold"))
        self.empty_title.pack(pady=(0, 8))
        self.label(self.empty, "选择包含图片或视频的文件夹。", muted=True).pack()
        self.empty_btn = self.button(self.empty, "选择文件夹…", self.browse_source)
        self.empty_btn.pack(pady=(14, 0))

        detail = self.frame(task_card)
        detail.grid(row=2, column=0, sticky="ew", padx=12, pady=8)
        detail.columnconfigure(1, weight=1)
        self.thumb = self.label(detail, "", width=4)
        self.thumb.grid(row=0, column=0, padx=(0, 8))
        self.detail = self.label(
            detail,
            variable=self.detail_var,
            font=(FONT, 9),
            muted=True,
            justify="left",
            anchor="w",
            wraplength=430,
        )
        self.detail.grid(row=0, column=1, sticky="ew")

        params = self.card(middle, width=300)
        params.grid(row=0, column=1, sticky="ns")
        params.grid_propagate(False)
        params.columnconfigure(0, weight=1)
        params.rowconfigure(1, weight=1)
        self.label(params, "输出设置", font=(FONT, 10, "bold")).grid(
            row=0, column=0, padx=12, pady=(12, 8), sticky="w"
        )
        self.options_canvas = tk.Canvas(params, width=270, highlightthickness=0, bd=0)
        self.paint(self.options_canvas, bg="card")
        self.options_canvas.grid(row=1, column=0, sticky="nsew", padx=(10, 0), pady=(0, 8))
        options_scroll = ttk.Scrollbar(
            params,
            orient="vertical",
            command=self.options_canvas.yview,
            style="Studio.Vertical.TScrollbar",
        )
        options_scroll.grid(row=1, column=1, sticky="ns", padx=(0, 3), pady=(0, 8))
        self.options_canvas.configure(yscrollcommand=options_scroll.set)
        options_content = self.frame(self.options_canvas)
        options_content.columnconfigure(0, weight=1)
        canvas_item = self.options_canvas.create_window(0, 0, window=options_content, anchor="nw")
        options_content.bind(
            "<Configure>",
            lambda _: self.options_canvas.configure(scrollregion=self.options_canvas.bbox("all")),
        )
        self.options_canvas.bind(
            "<Configure>",
            lambda event: self.options_canvas.itemconfigure(canvas_item, width=event.width),
        )

        def scroll_options(event):
            widget = event.widget
            while widget:
                if widget == params:
                    self.options_canvas.yview_scroll(int(-event.delta / 120), "units")
                    return "break"
                widget = getattr(widget, "master", None)

        self.root.bind_all("<MouseWheel>", scroll_options, add="+")
        self.notebook = ttk.Notebook(options_content, style="Studio.TNotebook")
        self.notebook.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        image_page = self.frame(self.notebook)
        video_page = self.frame(self.notebook)
        self.notebook.add(image_page, text="图片")
        self.notebook.add(video_page, text="视频")
        self._image_options(image_page)
        self._video_options(video_page)
        if self.mode != "all":
            self.notebook.select(0 if self.mode == "image" else 1)
        bottom = self.frame(params)
        bottom.grid(row=2, column=0, columnspan=2, sticky="ew", padx=12, pady=(4, 12))
        self.check(bottom, "仅保存更小的文件", self.option_vars["skip_larger"]).pack(anchor="w")

        footer = self.frame(content, surface="bg")
        footer.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        footer.columnconfigure(0, weight=1)
        progress_area = self.frame(footer, surface="bg")
        progress_area.grid(row=0, column=0, sticky="ew", padx=(0, 20))
        progress_area.columnconfigure(0, weight=1)
        self.label(
            progress_area, variable=self.status_var, font=(FONT, 10), surface="bg", anchor="w"
        ).grid(row=0, column=0, sticky="ew")
        self.label(
            progress_area,
            variable=self.summary_var,
            font=(FONT, 9),
            muted=True,
            surface="bg",
            anchor="w",
            width=1,
        ).grid(row=1, column=0, sticky="ew", pady=(3, 8))
        self.progress = ttk.Progressbar(
            progress_area,
            variable=self.progress_var,
            maximum=100,
            style="Studio.Horizontal.TProgressbar",
        )
        self.progress.grid(row=2, column=0, sticky="ew")
        actions = self.frame(footer, surface="bg")
        actions.grid(row=0, column=1, sticky="e")
        self.stop_btn = self.button(actions, "停止", self.stop)
        self.stop_btn.pack(side="left", padx=(0, 8))
        self.start_btn = self.button(actions, "开始压缩", self.start, primary=True)
        self.start_btn.pack(side="left")
        status_bar = self.frame(content, surface="bg")
        status_bar.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        status_bar.columnconfigure(0, weight=1)
        self.label(
            status_bar, variable=self.cap_var, font=(FONT, 9), muted=True, surface="bg"
        ).grid(row=0, column=0, sticky="w")
        self.button(status_bar, "打开输出文件夹", self.open_output, compact=True).grid(
            row=0, column=1
        )
        self.source.trace_add("write", self._source_changed)
        self._build_options_page()
        self.root.bind("<Control-o>", lambda _: self.browse_source())
        self.root.bind(
            "<Control-Return>",
            lambda _: self.save_options() if self.options_open else self.start(),
        )
        self.root.bind("<F5>", lambda _: self.scan())
        self.root.bind(
            "<Escape>", lambda _: self.cancel_options() if self.options_open else self.stop()
        )
        self.set_busy(False)

    def _build_options_page(self):
        page = self.frame(self.root, surface="bg")
        self.settings_page = page
        page.grid(row=0, column=0, sticky="nsew", padx=16, pady=12)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)
        self.label(page, "选项", font=(FONT, 13, "bold"), surface="bg").grid(
            row=0, column=0, sticky="w", pady=(0, 12)
        )
        card = self.card(page)
        card.grid(row=1, column=0, sticky="ew")
        card.columnconfigure(0, weight=1)
        self.label(card, "特殊图片处理", font=(FONT, 10, "bold")).grid(
            row=0, column=0, sticky="w", padx=20, pady=(20, 14)
        )
        self.primary_only_check = self.check(
            card, "多图 JPG 仅保留主图", self.option_vars["image_primary_only"]
        )
        self.primary_only_check.grid(row=1, column=0, sticky="w", padx=20)
        note = self.label(
            card,
            "部分 JPG 内含多幅图像。开启后只转换主图，附加图及其 HDR、深度等信息和 XMP 不会保留。",
            muted=True,
            justify="left",
            anchor="w",
        )
        note.grid(row=2, column=0, sticky="ew", padx=20, pady=(8, 12))
        pair_note = self.label(
            card,
            "实况照片的 JPG 和 MOV 分别转码，输出不保留实况照片的配对效果。",
            muted=True,
            justify="left",
            anchor="w",
        )
        pair_note.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 20))
        card.bind(
            "<Configure>",
            lambda event: [
                widget.configure(wraplength=max(200, event.width - 40))
                for widget in (note, pair_note)
            ],
        )
        actions = self.frame(page, surface="bg")
        actions.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        self.save_options_btn = self.button(actions, "保存并返回", self.save_options, primary=True)
        self.save_options_btn.pack(side="right")
        self.button(actions, "取消", self.cancel_options).pack(side="right", padx=(0, 8))
        page.grid_remove()

    def show_options(self):
        if self.busy or self.options_open:
            return
        self.options_snapshot = self.option_vars["image_primary_only"].get()
        self.options_open = True
        self.main_page.grid_remove()
        self.settings_page.grid()
        self.primary_only_check.focus_set()

    def save_options(self):
        if not self.options_open:
            return
        self._leave_options()
        self.persist_settings()

    def cancel_options(self):
        if not self.options_open:
            return
        self.option_vars["image_primary_only"].set(self.options_snapshot)
        self._leave_options()

    def _leave_options(self):
        self.options_open = False
        self.options_snapshot = None
        self.settings_page.grid_remove()
        self.main_page.grid()
        self.options_btn.focus_set()

    def _source_changed(self, *_):
        if not self.busy:
            self.start_btn.configure(state="normal" if self.source.get().strip() else "disabled")

    def _field(self, parent, label, var, values=None, row=0):
        self.label(parent, label, font=(FONT, 9), muted=True).grid(
            row=row, column=0, sticky="w", pady=(8, 5)
        )
        widget = self.combo(parent, var, values) if values else self.entry(parent, var)
        widget.grid(row=row + 1, column=0, sticky="ew")
        return widget

    def _image_options(self, parent):
        parent.columnconfigure(0, weight=1)
        inner = self.frame(parent)
        inner.grid(row=0, column=0, sticky="ew", padx=5, pady=2)
        inner.columnconfigure(0, weight=1)
        presets = {
            "均衡": (55, 6, "4:2:0"),
            "较高画质": (72, 4, "4:4:4"),
            "较小文件": (43, 7, "4:2:0"),
        }
        preset = tk.StringVar(value="自定义")
        self.image_preset = self.combo(inner, preset, [*presets, "自定义"])
        self.image_preset.grid(row=0, column=0, sticky="ew", pady=(12, 1))

        def choose(_=None):
            if preset.get() not in presets:
                return
            q, speed, sampling = presets[preset.get()]
            for key, value in [
                ("image_quality", q),
                ("image_speed", speed),
                ("sampling", sampling),
            ]:
                self.option_vars[key].set(value)

        self.image_preset.bind("<<ComboboxSelected>>", choose)

        def reflect_preset(*_):
            current = tuple(
                str(self.option_vars[key].get())
                for key in ("image_quality", "image_speed", "sampling")
            )
            preset.set(
                next(
                    (
                        name
                        for name, values in presets.items()
                        if tuple(map(str, values)) == current
                    ),
                    "自定义",
                )
            )

        for key in ("image_quality", "image_speed", "sampling"):
            self.option_vars[key].trace_add("write", reflect_preset)
        reflect_preset()
        pair = self.frame(inner)
        pair.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        pair.columnconfigure(0, weight=1)
        pair.columnconfigure(1, weight=1)
        self.label(pair, "画质 0–100", font=(FONT, 9), muted=True).grid(
            row=0, column=0, sticky="w", pady=(0, 5)
        )
        self.label(pair, "速度 0–10", font=(FONT, 9), muted=True).grid(
            row=0, column=1, sticky="w", padx=(8, 0), pady=(0, 5)
        )
        self.entry(pair, self.option_vars["image_quality"], width=8).grid(
            row=1, column=0, sticky="ew"
        )
        self.entry(pair, self.option_vars["image_speed"], width=8).grid(
            row=1, column=1, sticky="ew", padx=(8, 0)
        )
        self._field(inner, "色度采样", self.option_vars["sampling"], ["4:2:0", "4:4:4"], row=2)
        self.check(inner, "保留拍摄信息（含定位）", self.option_vars["keep_exif"]).grid(
            row=4, column=0, sticky="w", pady=(14, 6)
        )
        self.check(inner, "保留色彩配置（ICC）", self.option_vars["keep_icc"]).grid(
            row=5, column=0, sticky="w"
        )

    def _video_options(self, parent):
        parent.columnconfigure(0, weight=1)
        inner = self.frame(parent)
        inner.grid(row=0, column=0, sticky="ew", padx=5, pady=2)
        inner.columnconfigure(0, weight=1)
        self.codec_combo = self._field(inner, "编码器", self.codec_label, list(CODECS), row=0)
        row = self.frame(inner)
        row.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        row.columnconfigure(0, weight=1)
        row.columnconfigure(1, weight=1)
        self.label(row, "输出格式", font=(FONT, 9), muted=True).grid(
            row=0, column=0, sticky="w", pady=(0, 5)
        )
        self.label(row, "目标帧率", font=(FONT, 9), muted=True).grid(
            row=0, column=1, sticky="w", padx=(8, 0), pady=(0, 5)
        )
        self.combo(row, self.option_vars["container"], ["mp4", "webm"], width=8).grid(
            row=1, column=0, sticky="ew"
        )
        fps = self.combo(
            row,
            self.option_vars["fps"],
            ["原始帧率", "24", "25", "30", "50", "60", "60000/1001"],
            width=12,
        )
        fps.grid(row=1, column=1, sticky="ew", padx=(8, 0))
        control_row = self.frame(inner)
        control_row.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        control_row.columnconfigure(0, weight=1)
        control_row.columnconfigure(1, weight=1)
        self.label(control_row, "码率控制", font=(FONT, 9), muted=True).grid(
            row=0, column=0, sticky="w", pady=(0, 5)
        )
        self.label(control_row, "质量 1–51", font=(FONT, 9), muted=True).grid(
            row=0, column=1, sticky="w", padx=(8, 0), pady=(0, 5)
        )
        control = self.combo(control_row, self.rate_label, ["恒定质量", "指定码率"], width=11)
        control.grid(row=1, column=0, sticky="ew")
        self.quality_entry = self.entry(control_row, self.option_vars["video_quality"], width=8)
        self.quality_entry.grid(row=1, column=1, sticky="ew", padx=(8, 0))
        self.rate_stack = self.frame(inner)
        self.rate_stack.grid(row=4, column=0, sticky="ew")
        self.rate_stack.columnconfigure(0, weight=1)
        self.quality_frame = self.frame(self.rate_stack)
        self.quality_frame.grid(row=0, column=0, sticky="ew")
        self.quality_frame.columnconfigure(0, weight=1)
        self.label(
            self.quality_frame, "CQ / CRF 数值越低，画质越高。", font=(FONT, 8), muted=True
        ).pack(anchor="w", pady=(6, 0))
        self.bitrate_frame = self.frame(self.rate_stack)
        self.bitrate_frame.columnconfigure(0, weight=1)
        self.bitrate_frame.columnconfigure(1, weight=1)
        self.label(self.bitrate_frame, "目标 Mbps", font=(FONT, 9), muted=True).grid(
            row=0, column=0, sticky="w", pady=(10, 5)
        )
        self.label(self.bitrate_frame, "最大 Mbps", font=(FONT, 9), muted=True).grid(
            row=0, column=1, sticky="w", padx=(8, 0), pady=(10, 5)
        )
        self.entry(self.bitrate_frame, self.option_vars["bitrate"], width=8).grid(
            row=1, column=0, sticky="ew"
        )
        self.entry(self.bitrate_frame, self.option_vars["maxrate"], width=8).grid(
            row=1, column=1, sticky="ew", padx=(8, 0)
        )
        control.bind("<<ComboboxSelected>>", lambda _: self.update_rate())
        self.update_rate()
        self.label(
            inner,
            "MP4 使用 AAC，WebM 使用 Opus。\nNVIDIA 编码需要兼容的显卡和驱动。",
            font=(FONT, 8),
            muted=True,
            justify="left",
            wraplength=245,
        ).grid(row=5, column=0, sticky="w", pady=(12, 4))

    def update_rate(self):
        self.quality_entry.configure(
            state="disabled" if self.busy or self.rate_label.get() != "恒定质量" else "normal"
        )
        if self.rate_label.get() == "恒定质量":
            self.bitrate_frame.grid_remove()
            self.quality_frame.grid(row=0, column=0, sticky="ew")
        else:
            self.quality_frame.grid_remove()
            self.bitrate_frame.grid(row=0, column=0, sticky="ew")

    def apply_theme(self):
        c = THEMES[self.theme]
        self.root.configure(bg=c["bg"])
        for widget, mapping in self.colors:
            if widget.winfo_exists():
                widget.configure(**{key: c[value] for key, value in mapping.items()})
        for widget, primary in self.buttons:
            if not widget.winfo_exists():
                continue
            widget.configure(
                bg=c["accent"] if primary else c["field"],
                fg=(
                    "#FFFFFF"
                    if primary and self.theme == "light"
                    else "#101C37" if primary else c["text"]
                ),
                activebackground=c["hover"] if primary else c["select"],
                activeforeground="#FFFFFF" if primary and self.theme == "light" else c["text"],
                disabledforeground=c["disabled"],
                highlightbackground=c["border"],
                highlightcolor=c["accent"],
            )
        self.theme_btn.configure(text="深色外观" if self.theme == "light" else "浅色外观")
        for key, widget in self.mode_buttons.items():
            widget.configure(
                bg=c["tint"] if key == self.mode else c["card"],
                fg=c["accent"] if key == self.mode else c["muted"],
            )
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", font=(FONT, 10), background=c["card"], foreground=c["text"])
        style.configure(
            "Studio.TEntry",
            fieldbackground=c["field"],
            foreground=c["text"],
            insertcolor=c["text"],
            padding=(9, 5),
            bordercolor=c["border"],
            lightcolor=c["border"],
            darkcolor=c["border"],
        )
        style.map(
            "Studio.TEntry",
            fieldbackground=[("disabled", c["card"])],
            foreground=[("disabled", c["muted"])],
            bordercolor=[("focus", c["accent"])],
        )
        style.configure(
            "Studio.TCombobox",
            fieldbackground=c["field"],
            background=c["field"],
            foreground=c["text"],
            arrowcolor=c["muted"],
            padding=(8, 5),
            bordercolor=c["border"],
            lightcolor=c["border"],
            darkcolor=c["border"],
        )
        style.map(
            "Studio.TCombobox",
            fieldbackground=[("readonly", c["field"]), ("disabled", c["card"])],
            foreground=[("disabled", c["muted"]), ("readonly", c["text"])],
            selectbackground=[("readonly", c["field"])],
            selectforeground=[("readonly", c["text"])],
        )
        self.root.option_add("*TCombobox*Listbox.background", c["field"])
        self.root.option_add("*TCombobox*Listbox.foreground", c["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", c["select"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", c["text"])
        style.configure(
            "Studio.TCheckbutton",
            background=c["card"],
            foreground=c["text"],
            indicatorbackground=c["field"],
            indicatorforeground=c["accent"],
            padding=0,
        )
        style.map(
            "Studio.TCheckbutton",
            background=[("active", c["card"])],
            foreground=[("disabled", c["muted"])],
        )
        style.configure(
            "Studio.TNotebook",
            background=c["card"],
            borderwidth=0,
            bordercolor=c["card"],
            lightcolor=c["card"],
            darkcolor=c["card"],
            tabmargins=(0, 0, 0, 8),
        )
        style.configure(
            "Studio.TNotebook.Tab",
            background=c["field"],
            foreground=c["muted"],
            padding=(16, 6),
            borderwidth=0,
            bordercolor=c["card"],
            lightcolor=c["card"],
            darkcolor=c["card"],
        )
        style.map(
            "Studio.TNotebook.Tab",
            background=[("selected", c["tint"])],
            foreground=[("selected", c["accent"])],
        )
        style.configure(
            "Studio.Treeview",
            background=c["card"],
            fieldbackground=c["card"],
            foreground=c["text"],
            borderwidth=0,
            rowheight=32,
            font=(FONT, 9),
        )
        style.layout("Studio.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        style.configure(
            "Studio.Treeview.Heading",
            background=c["card"],
            foreground=c["muted"],
            relief="flat",
            padding=(8, 10),
            font=(FONT, 9),
        )
        style.map(
            "Studio.Treeview",
            background=[("selected", c["select"])],
            foreground=[("selected", c["text"])],
        )
        style.map("Studio.Treeview.Heading", background=[("active", c["field"])])
        self.tree.tag_configure("odd", background=c["stripe"])
        for tag, token in [
            ("success", "text"),
            ("skip", "muted"),
            ("larger", "muted"),
            ("error", "red"),
            ("cancel", "muted"),
        ]:
            self.tree.tag_configure(tag, foreground=c[token])
        style.configure(
            "Studio.Vertical.TScrollbar",
            background=c["border"],
            troughcolor=c["card"],
            borderwidth=0,
            arrowsize=10,
            arrowcolor=c["muted"],
            bordercolor=c["card"],
            lightcolor=c["border"],
            darkcolor=c["border"],
        )
        style.configure(
            "Studio.Horizontal.TProgressbar",
            background=c["accent"],
            troughcolor=c["field"],
            bordercolor=c["field"],
            lightcolor=c["field"],
            darkcolor=c["field"],
            borderwidth=0,
            thickness=5,
        )
        if self.log_text and self.log_text.winfo_exists():
            self.log_text.configure(bg=c["field"], fg=c["text"], insertbackground=c["text"])

    def toggle_theme(self):
        self.theme = "dark" if self.theme == "light" else "light"
        self.apply_theme()
        self.persist_settings()

    def persist_settings(self):
        if not self.persist:
            return
        values = {key: var.get() for key, var in self.option_vars.items()}
        values["codec"] = CODECS.get(self.codec_label.get(), "av1_cpu")
        values["rate_mode"] = "quality" if self.rate_label.get() == "恒定质量" else "bitrate"
        try:
            core.save_settings(
                dict(
                    theme=self.theme,
                    source=self.source.get(),
                    output=self.output.get(),
                    mode=self.mode,
                    include=self.include.get(),
                    exclude=self.exclude.get(),
                    recursive=self.recursive.get(),
                    options=values,
                )
            )
        except OSError as exc:
            self.log(f"设置未保存：{exc}")

    def select_mode(self, key):
        if self.busy or self.options_open:
            return
        self.mode = key
        if key != "all":
            self.notebook.select(0 if key == "image" else 1)
        self.apply_theme()
        if self.source.get():
            self.scan()

    def toggle_filters(self):
        self.filters_open = not self.filters_open
        if self.filters_open:
            self.filter_frame.grid(
                row=3, column=0, columnspan=3, sticky="ew", padx=18, pady=(0, 12)
            )
        else:
            self.filter_frame.grid_remove()
        self.filters_btn.configure(text="收起筛选" if self.filters_open else "文件筛选")

    def browse_source(self):
        if self.busy or self.options_open:
            return
        path = filedialog.askdirectory(
            title="选择照片和视频所在的文件夹", initialdir=self.source.get() or None
        )
        if path:
            previous_default = (
                str(Path(self.source.get()) / "压缩输出") if self.source.get() else ""
            )
            if not self.output.get() or self.output.get() == previous_default:
                self.output.set(str(Path(path) / "压缩输出"))
            self.source.set(path)
            self.scan()

    def browse_output(self):
        if self.busy or self.options_open:
            return
        path = filedialog.askdirectory(
            title="选择输出文件夹", initialdir=self.output.get() or self.source.get() or None
        )
        if path:
            self.output.set(path)

    def options(self):
        values = {key: var.get() for key, var in self.option_vars.items()}
        values["png_colors"] = int(values["png_colors"]) if values["png_colors"] else None
        for key in ("image_quality", "image_speed", "video_quality", "bitrate", "maxrate"):
            try:
                values[key] = int(values[key])
            except (ValueError, TypeError):
                raise ValueError("质量、速度与码率参数必须填写整数") from None
        values["codec"] = CODECS[self.codec_label.get()]
        values["rate_mode"] = "quality" if self.rate_label.get() == "恒定质量" else "bitrate"
        options = core.Options(**values)
        options.validate()
        return options

    def scan(self, run_after=False):
        if self.busy or self.options_open:
            return
        try:
            if self.source.get() and not self.output.get():
                self.output.set(str(Path(self.source.get()) / "压缩输出"))
            source, output = core.validate_paths(self.source.get(), self.output.get())
            core.patterns(self.include.get())
            core.patterns(self.exclude.get())
            options = self.options() if run_after else None
        except Exception as exc:
            messagebox.showerror("请检查设置", str(exc), parent=self.root)
            return
        self.cancel = core.Cancellation()
        self.set_busy(True)
        self.status_var.set("正在扫描…")
        self.summary_var.set("")
        self.progress_var.set(0)
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self.persist_settings()
        include, exclude, recursive, mode = (
            self.include.get(),
            self.exclude.get(),
            self.recursive.get(),
            self.mode,
        )

        def work():
            try:
                tasks = core.scan(source, output, include, exclude, recursive, mode, self.cancel)
                self.events.put(
                    (
                        "scanned",
                        dict(tasks=tasks, output=output, options=options, run_after=run_after),
                    )
                )
            except Exception as exc:
                self.events.put(("fatal", {"message": str(exc)}))

        self.worker = threading.Thread(target=work, daemon=False)
        self.worker.start()

    def start(self):
        self.scan(run_after=True)

    def set_busy(self, value):
        self.busy = value
        for widget in (
            self.scan_btn,
            self.start_btn,
            self.source_btn,
            self.output_btn,
            self.filters_btn,
            self.options_btn,
            self.empty_btn,
            *self.mode_buttons.values(),
        ):
            widget.configure(state="disabled" if value else "normal")
        for widget, state in self.inputs:
            widget.configure(state="disabled" if value else state)
        self.stop_btn.configure(state="normal" if value else "disabled")
        self.update_rate()
        self._source_changed()

    def stop(self):
        if not self.busy:
            return
        self.cancel.cancel()
        self.stop_btn.configure(state="disabled")
        self.status_var.set("正在停止…")
        self.summary_var.set("视频将终止当前编码；图片会在当前文件完成后停止。")

    def _on_scanned(self, data):
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.tasks = data["tasks"]
        self.results.clear()
        self.tree.delete(*self.tree.get_children())
        self.preview_image = None
        self.thumb.configure(image="", text="")
        self.detail_var.set("")
        for index, task in enumerate(self.tasks):
            self.tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    task.relative.as_posix(),
                    "图片" if task.kind == "image" else "视频",
                    size_text(task.size),
                    "—",
                    "等待中",
                ),
                tags=("odd",) if index % 2 else (),
            )
        self.bytes_var.set(size_text(sum(t.size for t in self.tasks)) if self.tasks else "—")
        self.queue_summary.set(f"{len(self.tasks)} 个文件 · {self.bytes_var.get()}")
        self.empty_title.configure(
            text="没有匹配的文件" if self.source.get() and not self.tasks else "未添加文件"
        )
        if self.tasks:
            self.empty.place_forget()
        else:
            self.empty.place(relx=0.5, rely=0.52, anchor="center")
        count_images = sum(t.kind == "image" for t in self.tasks)
        self.summary_var.set(f"{count_images} 张图片，{len(self.tasks) - count_images} 个视频")
        self.log(
            f"扫描完成：{len(self.tasks)} 个文件，{size_text(sum(t.size for t in self.tasks))}"
        )
        if self.cancel.event.is_set() or not data["run_after"] or not self.tasks:
            self.status_var.set(
                "已停止"
                if self.cancel.event.is_set()
                else "扫描完成" if self.tasks else "没有匹配的文件"
            )
            self.set_busy(False)
            return
        self.status_var.set("正在准备压缩…")
        self.current_index = 0

        def emit(kind, value):
            self.events.put((kind, value))

        self.worker = threading.Thread(
            target=core.run,
            args=(self.tasks, data["output"], data["options"], self.cancel, emit),
            daemon=False,
        )
        self.worker.start()

    def _check_capabilities(self):
        self.events.put(("capabilities", core.capabilities()))

    def poll(self):
        try:
            for _ in range(150):
                try:
                    kind, data = self.events.get_nowait()
                except queue.Empty:
                    break
                if kind == "scanned":
                    self._on_scanned(data)
                elif kind == "current":
                    self.current_index = data["index"]
                    self.status_var.set(f"正在压缩 {self.current_index + 1} / {len(self.tasks)}")
                    self.summary_var.set(data["name"])
                    self.tree.set(str(self.current_index), "status", "准备中")
                    self.tree.see(str(self.current_index))
                elif kind == "stage":
                    self.tree.set(str(self.current_index), "status", data["status"])
                elif kind == "fraction":
                    self.progress_var.set(
                        100 * (self.current_index + data["fraction"]) / max(1, len(self.tasks))
                    )
                elif kind == "result":
                    index = data["index"]
                    self.results[index] = data
                    self.tree.set(str(index), "status", STATUS[data["status"]])
                    self.tree.set(
                        str(index),
                        "result",
                        (
                            size_text(data["size"])
                            if data["size"] and data["status"] in ("success", "skip")
                            else "—"
                        ),
                    )
                    self.tree.item(
                        str(index), tags=(("odd",) if index % 2 else ()) + (data["status"],)
                    )
                    self.progress_var.set(100 * (index + 1) / max(1, len(self.tasks)))
                    self.log(
                        f'[{STATUS[data["status"]]}] {self.tasks[index].relative} · {data["reason"]}'
                    )
                elif kind == "finished":
                    self.set_busy(False)
                    counts = data["counts"]
                    self.queue_summary.set(
                        f'{len(self.tasks)} 个文件 · 输出减小 {size_text(data["saved"])}'
                    )
                    self.status_var.set("任务已停止" if data["cancelled"] else "压缩完成")
                    self.summary_var.set(
                        f'完成 {counts["success"]} · 跳过 {counts["skip"]} · 未变小 {counts["larger"]} · 失败 {counts["error"]} · {data["elapsed"]:.1f} 秒'
                    )
                    if not data["cancelled"]:
                        self.progress_var.set(100)
                    self.log(self.summary_var.get())
                elif kind == "fatal":
                    self.progress.stop()
                    self.progress.configure(mode="determinate")
                    self.set_busy(False)
                    self.status_var.set("处理失败")
                    self.summary_var.set("点击运行日志查看具体原因")
                    self.log("错误：" + data["message"])
                    if not self.closing:
                        messagebox.showerror("处理失败", data["message"], parent=self.root)
                elif kind == "log":
                    self.log(data["message"])
                elif kind == "thumbnail":
                    selection = self.tree.selection()
                    if selection and int(selection[0]) == data["index"]:
                        self.preview_image = ImageTk.PhotoImage(data["image"])
                        self.thumb.configure(image=self.preview_image, text="")
                elif kind == "capabilities":
                    self.caps = data
                    self.cap_var.set(
                        ("图片压缩可用" if data["avif"] else "图片压缩不可用")
                        + "  /  "
                        + ("视频压缩可用" if data["video"] else "未找到 FFmpeg")
                    )
                    if data["message"]:
                        self.log(data["message"])
        except tk.TclError:
            return
        if self.closing and not self.busy and (not self.worker or not self.worker.is_alive()):
            self.persist_settings()
            self.root.destroy()
            return
        self.root.after(80, self.poll)

    def selected(self, _=None):
        selection = self.tree.selection()
        if not selection:
            return
        index = int(selection[0])
        task = self.tasks[index]
        result = self.results.get(index)
        self.detail_var.set(
            task.relative.as_posix()
            + "\n"
            + (
                result["reason"]
                if result
                else f'{"AVIF 图片" if task.kind == "image" else "视频转码"} · {size_text(task.size)}'
            )
        )
        self.thumb.configure(image="", text="")
        if task.kind == "image":

            def thumbnail():
                try:
                    with Image.open(task.source) as raw:
                        raw.thumbnail((140, 100))
                        thumb = ImageOps.exif_transpose(raw).convert("RGBA")
                        thumb.thumbnail((52, 40))
                        self.events.put(("thumbnail", {"index": index, "image": thumb.copy()}))
                except Exception:
                    pass

            threading.Thread(target=thumbnail, daemon=True).start()

    def log(self, message):
        line = time.strftime("%H:%M:%S") + "  " + message
        self.logs.append(line)
        self.logs = self.logs[-2000:]
        if self.log_text and self.log_text.winfo_exists():
            self.log_text.configure(state="normal")
            self.log_text.insert("end", line + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")

    def show_logs(self):
        if self.log_window and self.log_window.winfo_exists():
            self.log_window.lift()
            return
        window = tk.Toplevel(self.root)
        self.log_window = window
        window.title("运行日志 · 轻压")
        window.geometry("850x480")
        self.log_text = tk.Text(
            window, wrap="word", font=(FONT, 10), relief="flat", padx=18, pady=16
        )
        self.log_text.pack(fill="both", expand=True)
        self.log_text.insert("end", "\n".join(self.logs) + "\n")
        self.log_text.configure(state="disabled")
        self.apply_theme()

    def open_output(self):
        if not self.output.get():
            messagebox.showinfo(
                "输出文件夹", "选择来源后，默认输出到其中的“压缩输出”文件夹。", parent=self.root
            )
            return
        try:
            path = Path(self.output.get()).resolve()
            if not path.is_dir():
                messagebox.showinfo(
                    "输出文件夹", "输出文件夹尚未创建，开始压缩时会自动创建。", parent=self.root
                )
                return
            os.startfile(path)
        except OSError as exc:
            messagebox.showerror("无法打开文件夹", str(exc), parent=self.root)

    def about(self):
        window = tk.Toplevel(self.root)
        window.title("帮助 — 轻压")
        window.geometry("620x470")
        colors = THEMES[self.theme]
        text = tk.Text(
            window,
            wrap="word",
            padx=20,
            pady=18,
            relief="flat",
            font=(FONT, 10),
            bg=colors["card"],
            fg=colors["text"],
        )
        self.paint(text, bg="card", fg="text")
        text.pack(fill="both", expand=True)
        text.insert(
            "end",
            f"轻压 {__version__}\n\n"
            "选择来源文件夹，检查文件列表和输出设置，然后点击“开始压缩”。特殊图片处理可在“选项”页配置。输出保留子文件夹结构，原文件不会修改。\n\n"
            "图片\n"
            "输出 AVIF。画质越高，文件通常越大；编码速度越高，处理越快。保留拍摄信息会同时保留 EXIF 中的位置数据。图片输出为 8-bit，多图 JPG 可选择仅保留主图；多页 TIFF 或动画仍不支持。\n\n"
            "视频\n"
            "默认使用 AV1 CPU 编码并保持源帧率。MP4 使用 AAC 音频，WebM 使用 Opus；H.265 只能保存为 MP4。CQ/CRF 越低画质越高，不同编码器的数值不能直接比较。\n\n"
            "视频保留首个视频轨及所有音轨，不转存字幕或附件。不进行 Log、HDR 与 SDR 之间的色彩转换，HDR 动态元数据不在校验范围内。\n\n"
            "实况照片的 JPG 和 MOV 分别转码，不保留实况配对效果。仅保留 JPG 主图时，附加图及其 HDR、深度信息和 XMP 不会复制。\n\n"
            "停止后，已完成的输出会保留。再次运行时会跳过来源和参数未变、且校验通过的结果。失败原因可在日志中查看。处理记录保存在用户数据目录，不会在输出文件夹生成记录目录。\n\n"
            "快捷键：Ctrl+O 选择来源，F5 扫描，Ctrl+Enter 开始，Esc 停止。在选项页，Ctrl+Enter 保存并返回，Esc 取消。\n\n"
            "源码使用 MIT 许可证。Pillow、FFmpeg 等组件的许可证见发行目录中的 THIRD_PARTY_NOTICES.md。",
        )
        text.configure(state="disabled")

    def close(self):
        if self.busy:
            self.closing = True
            self.stop()
            self.status_var.set("正在停止任务并退出…")
        else:
            self.cancel_options()
            self.persist_settings()
            self.root.destroy()


def main():
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    App(root)
    root.mainloop()
