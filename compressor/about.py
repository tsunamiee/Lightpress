"""Application information and local license texts."""

import tkinter as tk
from tkinter import ttk

from . import __version__, storage
from .strings import translate
from .window_theme import apply_titlebar

FONT = "Microsoft YaHei UI"
COMPONENT_FILES = (
    ("Pillow", ("Pillow.txt",)),
    ("FFmpeg", ("FFmpeg.txt", "FFmpeg-GPL-v3.txt")),
    ("Python", ("Python.txt",)),
    ("Tcl/Tk", ("Tk-license.terms",)),
    ("Lucide", ("Lucide.txt",)),
    ("resvg-py", ("resvg-py.txt",)),
    ("resvg", ("resvg-MIT.txt", "resvg-Apache-2.0.txt")),
    ("PyInstaller", ("PyInstaller.txt",)),
)


def component_licenses(directory):
    folder = directory / "licenses"
    entries = []
    for name, filenames in COMPONENT_FILES:
        paths = tuple(folder / filename for filename in filenames if (folder / filename).is_file())
        if name == "FFmpeg":
            paths = paths[:1]
            dependencies = folder / "FFmpeg-dependencies.txt"
            if paths and dependencies.is_file():
                paths += (dependencies,)
        if paths:
            entries.append((name, paths))
    return entries


def license_text(paths):
    documents = dict.fromkeys(path.read_text(encoding="utf-8", errors="replace") for path in paths)
    return ("\n\n" + "─" * 48 + "\n\n").join(documents)


def _button(parent, text, command, palette):
    return tk.Button(
        parent,
        text=text,
        command=command,
        font=(FONT, -13),
        relief="flat",
        bd=0,
        padx=16,
        pady=8,
        bg=palette["tint"],
        fg=palette["accent"],
        activebackground=palette["border"],
        activeforeground=palette["text"],
        cursor="hand2",
    )


def show_components(parent, palette, language, dark):
    tr = lambda key: translate(language, key)
    window = tk.Toplevel(parent)
    window.title(tr("open_source_components"))
    window.transient(parent)
    window.configure(bg=palette["card"])
    window.geometry("700x460")
    window.minsize(580, 360)
    window.bind("<Escape>", lambda _: window.destroy())
    body = tk.Frame(window, bg=palette["card"])
    body.pack(fill="both", expand=True, padx=20, pady=20)
    choices = tk.Listbox(
        body,
        width=24,
        font=(FONT, -12),
        bg=palette["card"],
        fg=palette["text"],
        selectbackground=palette["tint"],
        selectforeground=palette["accent"],
        selectborderwidth=0,
        exportselection=False,
        relief="flat",
        bd=0,
        highlightthickness=0,
        activestyle="none",
    )
    choices.pack(side="left", fill="y", padx=(0, 16))
    content = tk.Frame(body, bg=palette["card"])
    content.pack(side="left", fill="both", expand=True)
    scrollbar = ttk.Scrollbar(content, orient="vertical")
    scrollbar.pack(side="right", fill="y")
    text = tk.Text(
        content,
        font=(FONT, -12),
        wrap="word",
        bg=palette["card"],
        fg=palette["text"],
        selectbackground=palette["tint"],
        selectforeground=palette["text"],
        relief="flat",
        bd=0,
        highlightthickness=0,
        padx=4,
        yscrollcommand=scrollbar.set,
    )
    text.pack(fill="both", expand=True)
    scrollbar.configure(command=text.yview)
    entries = component_licenses(storage.application_dir())
    for name, _ in entries:
        choices.insert("end", name)

    def select(_=None):
        selected = choices.curselection()
        if not selected:
            return
        try:
            value = license_text(entries[selected[0]][1])
        except OSError:
            value = tr("license_unavailable")
        text.configure(state="normal")
        text.delete("1.0", "end")
        text.insert("1.0", value)
        text.configure(state="disabled")
        text.yview_moveto(0)

    choices.bind("<<ListboxSelect>>", select)
    if entries:
        choices.selection_set(0)
        select()
    else:
        text.insert("1.0", tr("license_unavailable"))
        text.configure(state="disabled")
    _button(window, tr("close"), window.destroy, palette).pack(anchor="e", padx=20, pady=(0, 18))
    window.after_idle(lambda: apply_titlebar(window, dark, palette["card"], palette["text"]))
    return window


def show_about(parent, palette, language, dark):
    tr = lambda key: translate(language, key)
    window = tk.Toplevel(parent)
    window.title(tr("about_title"))
    window.transient(parent)
    window.resizable(False, False)
    window.configure(bg=palette["card"])
    window.bind("<Escape>", lambda _: window.destroy())
    body = tk.Frame(window, bg=palette["card"])
    body.pack(fill="both", expand=True, padx=26, pady=24)

    def label(value, size=13, color="text", bold=False, **packing):
        widget = tk.Label(
            body,
            text=value,
            font=(FONT, -size, "bold" if bold else "normal"),
            bg=palette["card"],
            fg=palette[color],
            justify="left",
            anchor="w",
        )
        widget.pack(anchor="w", **packing)

    label(tr("app_name"), size=23, bold=True)
    label(__version__, color="muted", pady=(4, 16))
    label("© 2026 Lightpress contributors")
    label("MIT License", color="muted", pady=(6, 18))
    footer = tk.Frame(body, bg=palette["card"])
    footer.pack(fill="x")
    _button(
        footer,
        tr("open_source_components"),
        lambda: show_components(window, palette, language, dark),
        palette,
    ).pack(side="left", padx=(0, 12))
    _button(footer, tr("close"), window.destroy, palette).pack(side="right")
    window.update_idletasks()
    x = parent.winfo_rootx() + (parent.winfo_width() - window.winfo_reqwidth()) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - window.winfo_reqheight()) // 2
    window.geometry(f"+{max(0, x)}+{max(0, y)}")
    window.after_idle(lambda: apply_titlebar(window, dark, palette["card"], palette["text"]))
    return window
