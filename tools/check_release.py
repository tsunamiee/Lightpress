"""Check public source files and release packages for accidental local data."""

import argparse
import json
import marshal
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from types import CodeType
from urllib.parse import unquote, urlsplit
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.source_archive import source_files

RULES = {
    "user_directory": re.compile(r"(?i)(?:[A-Z]:[\\/]+Users[\\/]+|/(?:home|Users)/)"),
    "private_network": re.compile(
        r"\b(?:192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+)\b"
    ),
    "credential": re.compile(
        r"(?:BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY|gh[pousr]_[A-Za-z0-9_]{20,}"
        r"|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{24,})"
    ),
    "assigned_secret": re.compile(
        r"""(?i)(?:api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*["'][^"'\s]{8,}["']"""
    ),
}
IMAGE_SUFFIXES = {".png", ".ico"}


def local_prefixes():
    return {
        str(path).replace("\\", "/").lower()
        for path in (ROOT, Path.home(), Path(sys.prefix))
        if len(str(path)) > 4
    }


def scan_text(name, text, *, vendor=False):
    findings = []
    prefixes = local_prefixes()
    for line_number, line in enumerate(text.splitlines(), 1):
        for rule, pattern in RULES.items():
            if pattern.search(line):
                findings.append(dict(file=name, line=line_number, rule=rule))
        normalized = line.replace("\\\\", "/").replace("\\", "/").lower()
        if any(prefix in normalized for prefix in prefixes):
            findings.append(dict(file=name, line=line_number, rule="workstation_path"))
        if not vendor and re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", line):
            findings.append(dict(file=name, line=line_number, rule="email_address"))
    return findings


def scan_file(path, name):
    if path.suffix.lower() in IMAGE_SUFFIXES:
        from PIL import Image

        with Image.open(path) as image:
            keys = {key.lower() for key in image.info}
            if keys.intersection(
                {"exif", "xmp", "comment", "author", "description", "xml:com.adobe.xmp"}
            ):
                return [dict(file=name, rule="image_metadata")]
        return []
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeError:
        return [dict(file=name, rule="unexpected_binary_file")]
    return scan_text(name, text, vendor="licenses" in PurePosixPath(name).parts[:-1])


def check_document_links(files, root=ROOT):
    public_paths = {path.resolve() for path in files}
    findings = []
    for path in files:
        if path.suffix.lower() != ".md":
            continue
        text = path.read_text(encoding="utf-8-sig")
        for match in re.finditer(r"!?\[[^\]]*\]\(([^)]+)\)", text):
            target = urlsplit(match[1].strip("<>"))
            if target.scheme or not target.path:
                continue
            resolved = (path.parent / unquote(target.path)).resolve()
            if resolved not in public_paths:
                findings.append(
                    dict(file=path.relative_to(root).as_posix(), rule="missing_document_link")
                )
    return findings


def check_source_archive(path, files, root=ROOT):
    expected = {file.relative_to(root).as_posix(): file for file in files}
    findings = []
    with zipfile.ZipFile(path) as archive:
        members = {}
        for member in archive.infolist():
            parts = PurePosixPath(member.filename).parts
            name = "/".join(parts[1:])
            if len(parts) < 2 or ".." in parts or member.is_dir() or name in members:
                findings.append(dict(file=member.filename, rule="unexpected_archive_entry"))
            else:
                members[name] = member
        for name in sorted(members.keys() - expected.keys()):
            findings.append(dict(file=name, rule="unexpected_archive_file"))
        for name in sorted(expected.keys() - members.keys()):
            findings.append(dict(file=name, rule="missing_archive_file"))
        for name in expected.keys() & members.keys():
            if archive.read(members[name]) != expected[name].read_bytes():
                findings.append(dict(file=name, rule="archive_content_mismatch"))
    return findings


def check_tracked_files(files, root=ROOT):
    if not (root / ".git").exists():
        return []
    process = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--cached", "-z"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    public_names = {path.relative_to(root).as_posix() for path in files}
    return [
        dict(file=name, rule="tracked_file_outside_public_list")
        for name in process.stdout.rstrip("\0").split("\0")
        if name and name not in public_names
    ]


def check_application(directory):
    from PyInstaller.archive.readers import CArchiveReader

    findings = []
    prefixes = local_prefixes()
    byte_patterns = {
        text.encode(encoding)
        for prefix in prefixes
        for text in (prefix, prefix.replace("/", "\\"))
        for encoding in ("utf-8", "utf-16le")
    }
    overlap = max(map(len, byte_patterns)) - 1
    file_count = 0
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        file_count += 1
        name = path.relative_to(directory).as_posix()
        if "data" in Path(name).parts:
            findings.append(dict(file=name, rule="runtime_data_in_application"))
        with path.open("rb") as stream:
            previous = b""
            while chunk := stream.read(1024 * 1024):
                block = (previous + chunk).lower()
                if any(pattern in block for pattern in byte_patterns):
                    findings.append(dict(file=name, rule="workstation_path_in_binary"))
                    break
                previous = block[-overlap:]
        if not name.startswith("_internal/") and path.suffix.lower() in {
            ".md",
            ".txt",
            ".json",
            ".toml",
            ".svg",
            ".png",
            ".ico",
        }:
            findings.extend(scan_file(path, name))
    executable = directory / "Lightpress.exe"
    if not executable.is_file():
        return findings + [dict(file="Lightpress.exe", rule="missing_executable")], file_count
    reader = CArchiveReader(str(executable))
    pyz = reader.open_embedded_archive(next(name for name in reader.toc if name.endswith(".pyz")))

    def code_findings(code, name):
        result = []
        if Path(code.co_filename).is_absolute() or re.match(r"^[A-Za-z]:", code.co_filename):
            result.append(dict(file=name, rule="absolute_compiled_source_path"))
        for value in code.co_consts:
            if isinstance(value, CodeType):
                result.extend(code_findings(value, name))
            elif isinstance(value, str):
                result.extend(scan_text(name, value))
        return result

    for name in pyz.toc:
        if name == "compressor" or name.startswith("compressor."):
            findings.extend(code_findings(pyz.extract(name), name))
    findings.extend(code_findings(marshal.loads(reader.extract("main")), "main"))
    return findings, file_count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-archive", type=Path)
    parser.add_argument("--application-dir", type=Path)
    parser.add_argument("--ffmpeg-source-bundle", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    files = source_files()
    findings = []
    for path in files:
        findings.extend(scan_file(path, path.relative_to(ROOT).as_posix()))
    findings.extend(check_document_links(files))
    findings.extend(check_tracked_files(files))
    report = dict(source_files=len(files), findings=findings)
    if args.source_archive:
        findings.extend(check_source_archive(args.source_archive, files))
        report["source_archive_checked"] = args.source_archive.name
    if args.application_dir:
        additional, count = check_application(args.application_dir)
        findings.extend(additional)
        report["application_files"] = count
    if args.ffmpeg_source_bundle:
        from tools.ffmpeg.bundle import verify_bundle

        binary_dir = args.application_dir / "bin" if args.application_dir else None
        source_info = verify_bundle(args.ffmpeg_source_bundle, binary_dir)
        report["ffmpeg_source_bundle_verified"] = source_info["ffmpeg_version"]
    report["success"] = not findings
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
