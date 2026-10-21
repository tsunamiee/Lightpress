"""Secondary windows for preferences and per-file results."""

import os
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from . import core, jobs
from .window_theme import apply_titlebar

FONT = "Microsoft YaHei UI"


def window(app, title, width=460, height=420):
    result = tk.Toplevel(app.root)
    result.title(app.tr(title))
    result.transient(app.root)
    result.geometry(f"{width}x{height}+{app.root.winfo_rootx() + 20}+{app.root.winfo_rooty() + 30}")
    result.configure(bg=app.palette["card"])
    result.after_idle(
        lambda: apply_titlebar(
            result, app.theme == "dark", app.palette["card"], app.palette["text"]
        )
    )
    style = ttk.Style(result)
    style.theme_use("clam")
    p = app.palette
    style.configure(
        "Compact.TEntry",
        fieldbackground=p["bg"],
        foreground=p["text"],
        padding=7,
        insertcolor=p["text"],
    )
    style.configure(
        "Compact.TCombobox",
        fieldbackground=p["bg"],
        foreground=p["text"],
        background=p["bg"],
        padding=7,
        arrowsize=12,
    )
    style.map(
        "Compact.TCombobox",
        fieldbackground=[("readonly", p["bg"])],
        foreground=[("readonly", p["text"])],
    )
    for name in ("Compact.TEntry", "Compact.TCombobox", "Compact.Treeview.Heading"):
        style.configure(
            name,
            bordercolor=p["border"],
            lightcolor=p["border"],
            darkcolor=p["border"],
            relief="flat",
            borderwidth=1,
        )
    style.configure("Compact.Treeview", borderwidth=0, relief="flat")
    style.configure(
        "Compact.Vertical.TScrollbar",
        background=p["border"],
        troughcolor=p["bg"],
        arrowcolor=p["muted"],
        borderwidth=0,
    )
    return result


def button(app, parent, key, command):
    return tk.Button(
        parent,
        text=app.tr(key),
        command=command,
        font=(FONT, -13),
        bg=app.palette["tint"],
        fg=app.palette["accent"],
        relief="flat",
        bd=0,
        padx=14,
        pady=9,
        cursor="hand2",
    )


def label(app, parent, key, **kwargs):
    return tk.Label(
        parent,
        text=app.tr(key),
        bg=app.palette["card"],
        fg=app.palette["text"],
        font=(FONT, -13),
        anchor="w",
        **kwargs,
    )


def advanced_settings(app):
    dialog = window(app, "advanced", 440, 400)
    dialog.resizable(False, False)
    dialog.columnconfigure(1, weight=1)
    fields = {key: tk.StringVar(value=app.settings[key]) for key in ("include", "exclude")}
    for row, key in enumerate(fields):
        label(app, dialog, key).grid(row=row, column=0, padx=(18, 12), pady=(16, 0))
        ttk.Entry(dialog, textvariable=fields[key], style="Compact.TEntry").grid(
            row=row, column=1, sticky="ew", padx=(0, 18), pady=(16, 0)
        )
    label(app, dialog, "filter_help", wraplength=390, justify="left").grid(
        row=2, column=0, columnspan=2, sticky="ew", padx=18, pady=14
    )
    encoder_names = {app.tr("cpu_encoder"): "cpu", app.tr("gpu_encoder"): "nvidia"}
    encoder = tk.StringVar(
        value=next(name for name, key in encoder_names.items() if key == app.settings["encoder"])
    )
    fps_names = {
        app.tr("source_fps"): "原始帧率",
        **{value: value for value in ("24", "25", "30", "50", "60", "60000/1001")},
    }
    fps = tk.StringVar(
        value=next(
            (name for name, value in fps_names.items() if value == app.settings["fps"]),
            app.tr("source_fps"),
        )
    )
    for row, key, variable, values in (
        (3, "video_encoder", encoder, list(encoder_names)),
        (4, "frame_rate", fps, list(fps_names)),
    ):
        label(app, dialog, key).grid(row=row, column=0, padx=(18, 12), pady=8)
        ttk.Combobox(
            dialog,
            textvariable=variable,
            values=values,
            state="readonly",
            style="Compact.TCombobox",
        ).grid(row=row, column=1, sticky="ew", padx=(0, 18), pady=8)
    message = label(app, dialog, "gpu_note", wraplength=390, justify="left")
    message.grid(row=5, column=0, columnspan=2, sticky="ew", padx=18, pady=10)

    def save():
        values = {key: value.get() for key, value in fields.items()}
        try:
            for text in values.values():
                core.patterns(text)
            values.update(encoder=encoder_names[encoder.get()], fps=fps_names[fps.get()])
            jobs.encoding_options(app.selected_format.key, app.quality, app.settings | values)
        except Exception as error:
            message.configure(
                text=app.tr("invalid_preferences", detail=str(error)), fg=app.palette["error"]
            )
            return
        app.settings.update(values)
        dialog.destroy()
        app.draw()

    controls = tk.Frame(dialog, bg=app.palette["card"])
    controls.grid(row=6, column=0, columnspan=2, sticky="e", padx=18, pady=12)
    button(app, controls, "cancel", dialog.destroy).pack(side="left", padx=(0, 8))
    button(app, controls, "save_return", save).pack(side="left")
    dialog.bind("<Escape>", lambda _: dialog.destroy())
    dialog.grab_set()


def show_details(app):
    if app.details_window and app.details_window.winfo_exists():
        app.details_window.destroy()
    dialog = window(app, "details", 680, 460)
    app.details_window = dialog
    dialog.minsize(540, 380)
    p = app.palette
    dialog.rowconfigure(0, weight=1)
    dialog.columnconfigure(0, weight=1)
    style = ttk.Style(dialog)
    style.configure(
        "Compact.Treeview",
        background=p["card"],
        fieldbackground=p["card"],
        foreground=p["text"],
        rowheight=30,
        font=(FONT, -13),
    )
    style.configure(
        "Compact.Treeview.Heading", background=p["bg"], foreground=p["text"], font=(FONT, -13)
    )
    style.map(
        "Compact.Treeview",
        background=[("selected", p["tint"])],
        foreground=[("selected", p["accent"])],
    )
    tree = ttk.Treeview(
        dialog, columns=("name", "status", "size"), show="headings", style="Compact.Treeview"
    )
    for key, title, width in (
        ("name", "file", 320),
        ("status", "result", 95),
        ("size", "output_size", 115),
    ):
        tree.heading(key, text=app.tr(title))
        tree.column(key, width=width, stretch=key == "name")
    tree.grid(row=0, column=0, sticky="nsew", padx=(16, 0), pady=(16, 8))
    scrollbar = ttk.Scrollbar(dialog, command=tree.yview, style="Compact.Vertical.TScrollbar")
    scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 16), pady=(16, 8))
    tree.configure(yscrollcommand=scrollbar.set)
    for index, result in enumerate(app.results):
        tree.insert(
            "",
            "end",
            iid=str(index),
            values=(
                result["name"],
                app.tr("status_" + result["status"]),
                f'{result["size"] / 1024:.1f} KiB' if result["size"] else "—",
            ),
        )
    diagnostic = tk.Text(
        dialog,
        height=7,
        wrap="word",
        font=(FONT, -12),
        relief="flat",
        bg=p["bg"],
        fg=p["text"],
        padx=12,
        pady=10,
    )
    diagnostic.grid(row=1, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 8))

    def text_value(value):
        diagnostic.configure(state="normal")
        diagnostic.delete("1.0", "end")
        diagnostic.insert("1.0", value)
        diagnostic.configure(state="disabled")

    def selected(_=None):
        selection = tree.selection()
        if selection:
            item = app.results[int(selection[0])]
            code = item.get("code") or (
                "conversion_failed" if item["status"] == "error" else item["status"]
            )
            text_value(app.tr("reason_" + code) + "\n" + item["output"] + "\n" + item["reason"])

    tree.bind("<<TreeviewSelect>>", selected)
    text_value("\n".join(app.logs) or app.tr("details_help"))
    controls = tk.Frame(dialog, bg=p["card"])
    controls.grid(row=2, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 14))

    def open_output():
        path = Path(app.output.get()).expanduser()
        if path.is_dir():
            os.startfile(path)
        else:
            text_value(app.tr("output_not_created"))

    def copy_report():
        app.root.clipboard_clear()
        app.root.clipboard_append(
            "\n".join(
                [
                    f'{item["name"]}: {app.tr("status_" + item["status"])} — {item["reason"]}\n{item["output"]}'
                    for item in app.results
                ]
                + app.logs
            )
        )

    button(app, controls, "open_output", open_output).pack(side="left")
    button(app, controls, "copy_report", copy_report).pack(side="left", padx=8)
    button(app, controls, "close", dialog.destroy).pack(side="right")
    dialog.bind("<Escape>", lambda _: dialog.destroy())
