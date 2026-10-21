"""Build a source archive from the public file list."""

import hashlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from compressor import __version__

DIRECTORIES = (".github", "assets", "compressor", "docs", "licenses", "tests", "tools")
FILES = (
    ".gitattributes",
    ".gitignore",
    "README.md",
    "README.zh-CN.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "THIRD_PARTY_NOTICES.zh-CN.md",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "main.py",
    "build_release.py",
    "start.bat",
)
EXCLUDED_NAMES = {
    "changelog.md",
    "contributing.md",
    "agent.md",
    "agents.md",
    "claude.md",
    "gemini.md",
    "copilot-instructions.md",
    ".cursorrules",
    ".windsurfrules",
    ".mcp.json",
    "settings.json",
    "last-run.json",
}
EXCLUDED_PARTS = {
    ".agents",
    ".agent",
    ".codex",
    ".claude",
    ".cursor",
    ".git",
    ".local",
    ".venv",
    "__pycache__",
    "artifacts",
    "build",
    "data",
    "dist",
    "release",
    "venv",
}
SOURCE_SUFFIXES = {
    ".py",
    ".md",
    ".txt",
    ".terms",
    ".toml",
    ".json",
    ".yml",
    ".yaml",
    ".svg",
    ".png",
    ".ico",
    ".bat",
}


def source_files(root=ROOT):
    paths = [root / name for name in FILES if (root / name).is_file()]
    for directory in DIRECTORIES:
        for path in (root / directory).rglob("*"):
            relative = path.relative_to(root)
            if (
                path.is_file()
                and not path.is_symlink()
                and path.suffix.lower() in SOURCE_SUFFIXES
                and path.name.lower() not in EXCLUDED_NAMES
                and not path.name.lower().startswith(".env")
                and not EXCLUDED_PARTS.intersection(part.lower() for part in relative.parts[:-1])
            ):
                paths.append(path)
    return sorted(path for path in set(paths) if not path.is_symlink())


def main():
    target = ROOT / "release" / f"Lightpress-{__version__}-source.zip"
    target.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in source_files():
            archive.write(path, Path(f"Lightpress-{__version__}") / path.relative_to(ROOT))
    with target.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    target.with_suffix(".zip.sha256").write_text(f"{digest}  {target.name}\n", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
