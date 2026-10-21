"""Processing records stored outside media directories."""

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Callable

from .storage import data_dir


def history_path() -> Path:
    return data_dir() / "history.sqlite3"


def legacy_record(target: Path, directory: Path) -> tuple[Path, dict]:
    path = directory / (hashlib.sha256(str(target).encode()).hexdigest() + ".json")
    try:
        if directory.is_symlink() or path.is_symlink():
            return path, {}
        record = json.loads(path.read_text(encoding="utf-8"))
        if (
            isinstance(record, dict)
            and isinstance(record.get("source"), dict)
            and isinstance(record.get("output_size"), int)
            and isinstance(record.get("output_mtime_ns"), int)
        ):
            return path, record
    except (OSError, ValueError):
        pass
    return path, {}


class History:
    def __init__(self, warn: Callable[[str], None]):
        self.connection = None
        self.warn = warn
        self.warned = False
        try:
            path = history_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(path, timeout=5)
            self.connection.execute(
                "CREATE TABLE IF NOT EXISTS outputs (path TEXT PRIMARY KEY, record TEXT NOT NULL)"
            )
            self.connection.commit()
        except (OSError, sqlite3.Error) as exc:
            self._disable(exc)

    def _disable(self, error):
        self.close()
        if not self.warned:
            self.warn(f"无法保存处理记录，压缩仍可继续：{error}")
            self.warned = True

    @staticmethod
    def _key(target: Path) -> str:
        return os.path.normcase(str(target.resolve()))

    def get(self, target: Path, legacy_directory: Path) -> dict:
        old_path, old = legacy_record(target, legacy_directory)
        current = {}
        if self.connection:
            try:
                row = self.connection.execute(
                    "SELECT record FROM outputs WHERE path = ?", (self._key(target),)
                ).fetchone()
                if row:
                    decoded = json.loads(row[0])
                    if isinstance(decoded, dict):
                        current = decoded
            except (sqlite3.Error, ValueError) as exc:
                self._disable(exc)
        result = current or old
        # Remove a legacy record only after its replacement has been committed.
        if old and self.put(target, result):
            try:
                old_path.unlink()
                if not any(legacy_directory.iterdir()):
                    legacy_directory.rmdir()
            except OSError:
                pass
        return result

    def put(self, target: Path, record: dict) -> bool:
        if not self.connection:
            return False
        try:
            self.connection.execute(
                "INSERT OR REPLACE INTO outputs (path, record) VALUES (?, ?)",
                (self._key(target), json.dumps(record, ensure_ascii=False)),
            )
            self.connection.commit()
            return True
        except sqlite3.Error as exc:
            self._disable(exc)
            return False

    def close(self):
        if self.connection:
            try:
                self.connection.close()
            except sqlite3.Error:
                pass
            self.connection = None
