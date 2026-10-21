"""Portable application data and first-run language selection."""

import ctypes
import json
import locale
import os
from pathlib import Path
import sys
import uuid


def application_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def data_dir() -> Path:
    return application_dir() / "data"


def settings_path() -> Path:
    return data_dir() / "settings.json"


def read_settings() -> dict:
    try:
        value = json.loads(settings_path().read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def save_settings(value: dict):
    existing = read_settings()
    existing.update(value)
    write_json(settings_path(), existing)


def system_language() -> str:
    if sys.platform == "win32":
        try:
            language = ctypes.windll.kernel32.GetUserDefaultUILanguage
            language.restype = ctypes.c_ushort
            return "zh_CN" if language() & 0x3FF == 0x04 else "en"
        except (AttributeError, OSError):
            pass
    name = locale.getlocale()[0] or os.environ.get("LANG", "en")
    return "zh_CN" if name.lower().startswith("zh") else "en"
