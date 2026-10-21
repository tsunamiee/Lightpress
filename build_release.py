"""Build the Windows portable application."""

import argparse
import hashlib
import importlib.metadata
import json
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from compressor import __version__
from tools.ffmpeg.bundle import verify_bundle

ROOT = Path(__file__).resolve().parent
NAME = "Lightpress"


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def copy_ffmpeg(directory: Path, app: Path, source_bundle: Path) -> dict:
    source_info = verify_bundle(source_bundle, directory)
    binaries = [directory / f"{name}.exe" for name in ("ffmpeg", "ffprobe")]
    for binary in binaries:
        if not binary.is_file():
            raise FileNotFoundError(binary)
    target = app / "bin"
    target.mkdir()
    for binary in binaries:
        shutil.copy2(binary, target / binary.name)
    with zipfile.ZipFile(source_bundle) as archive:
        for filename, output in (
            ("COPYING.GPLv3", "FFmpeg.txt"),
            ("THIRD_PARTY_NOTICES.txt", "FFmpeg-dependencies.txt"),
            ("build-information.json", "FFmpeg-build-information.json"),
        ):
            name = next(name for name in archive.namelist() if name.split("/", 1)[1] == filename)
            (app / "licenses" / output).write_bytes(archive.read(name))
    reference = dict(
        filename=source_bundle.name,
        sha256=sha256(source_bundle),
        version=source_info["ffmpeg_version"],
    )
    (app / "FFmpeg-SOURCE.txt").write_text(
        "FFmpeg corresponding source\n\n"
        f"Release asset: {reference['filename']}\nSHA-256: {reference['sha256']}\n\n"
        "Download this asset from the same release page as Lightpress.\n"
        "It contains the exact upstream source archives, build scripts, configuration and license notices.\n"
        "The source asset is not required to run Lightpress.\n",
        encoding="utf-8",
    )
    process = subprocess.run(
        [str(binaries[0]), "-version"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return {
        "build": process.stdout,
        "files": {path.name: sha256(path) for path in binaries},
        "corresponding_source": reference,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg-dir", type=Path, help="FFmpeg bin 目录；不指定则不捆绑视频工具")
    parser.add_argument(
        "--ffmpeg-source-bundle", type=Path, help="与 FFmpeg 二进制匹配的配套源码 ZIP"
    )
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Windows 发行版需要在 Windows 上构建")
    if args.ffmpeg_dir:
        if not args.ffmpeg_source_bundle:
            parser.error("捆绑 FFmpeg 时需要 --ffmpeg-source-bundle")
        args.ffmpeg_dir = args.ffmpeg_dir.resolve(strict=True)
        for name in ("ffmpeg.exe", "ffprobe.exe"):
            if not (args.ffmpeg_dir / name).is_file():
                parser.error(f"{args.ffmpeg_dir} 缺少 {name}")
        args.ffmpeg_source_bundle = args.ffmpeg_source_bundle.resolve(strict=True)
        verify_bundle(args.ffmpeg_source_bundle, args.ffmpeg_dir)
    elif args.ffmpeg_source_bundle:
        parser.error("--ffmpeg-source-bundle 需要同时指定 --ffmpeg-dir")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--windowed",
            "--name",
            NAME,
            "--distpath",
            str(ROOT / "release" / __version__),
            "--workpath",
            str(ROOT / "build"),
            "--specpath",
            str(ROOT / "build"),
            "--icon",
            str(ROOT / "assets" / "app.ico"),
            "--add-data",
            f'{ROOT / "assets"};assets',
            "--exclude-module",
            "numpy",
            "--exclude-module",
            "matplotlib",
            "--exclude-module",
            "pandas",
            "--exclude-module",
            "scipy",
            "--exclude-module",
            "IPython",
            "--exclude-module",
            "PyQt5",
            "--exclude-module",
            "PyQt6",
            "--exclude-module",
            "PySide6",
            "--exclude-module",
            "pillow_heif",
            "--exclude-module",
            "tests",
            str(ROOT / "main.py"),
        ],
        check=True,
        cwd=ROOT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    app = ROOT / "release" / __version__ / NAME
    licenses = app / "licenses"
    licenses.mkdir()
    for source in (ROOT / "licenses").iterdir():
        if source.name.startswith("FFmpeg-") and args.ffmpeg_dir:
            continue
        if source.is_file():
            shutil.copy2(source, licenses / source.name)
    distribution = importlib.metadata.distribution("Pillow")
    for file in distribution.files or []:
        if str(file).replace("\\", "/").endswith("/licenses/LICENSE"):
            shutil.copy2(distribution.locate_file(file), licenses / "Pillow.txt")
    info = {
        "application": __version__,
        "python": platform.python_version(),
        "pillow": distribution.version,
        "resvg-py": importlib.metadata.version("resvg-py"),
        "target": "Windows-x64",
        "pyinstaller": importlib.metadata.version("PyInstaller"),
        "ffmpeg": (
            copy_ffmpeg(args.ffmpeg_dir, app, args.ffmpeg_source_bundle)
            if args.ffmpeg_dir
            else None
        ),
    }
    (app / "bundle.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    shutil.copytree(ROOT / "docs", app / "docs", dirs_exist_ok=True)
    for filename in (
        "README.md",
        "README.zh-CN.md",
        "THIRD_PARTY_NOTICES.md",
        "THIRD_PARTY_NOTICES.zh-CN.md",
        "LICENSE",
    ):
        shutil.copy2(ROOT / filename, app / filename)
    manifest = {
        path.relative_to(app).as_posix(): sha256(path)
        for path in sorted(app.rglob("*"))
        if path.is_file() and "data" not in path.relative_to(app).parts
    }
    (app / "SHA256SUMS.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    archive = ROOT / "release" / f"Lightpress-{__version__}-Windows-x64.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in sorted(app.rglob("*")):
            if path.is_file() and "data" not in path.relative_to(app).parts:
                bundle.write(path, path.relative_to(app.parent))
    archive.with_suffix(".zip.sha256").write_text(
        f"{sha256(archive)}  {archive.name}\n", encoding="utf-8"
    )
    print(app / f"{NAME}.exe")
    print(archive)


if __name__ == "__main__":
    main()
