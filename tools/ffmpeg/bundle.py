"""Create and verify the FFmpeg corresponding-source release asset."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import zipfile

from tools.ffmpeg.build import COMPONENTS, HERE, sha256

NOTICE_FILES = {
    "x264": ("COPYING",),
    "x265": ("COPYING",),
    "opus": ("COPYING",),
    "dav1d": ("COPYING", "doc/PATENTS"),
    "svt-av1": (
        "LICENSE.md",
        "LICENSE-BSD2.md",
        "PATENTS.md",
        "third_party/safestringlib/LICENSE",
        "third_party/cpuinfo/LICENSE",
        "third_party/cpuinfo/deps/clog/LICENSE",
    ),
    "zlib": ("LICENSE",),
}


def source_root(work, name):
    directory = work / "sources" / name
    children = list(directory.iterdir())
    return children[0] if len(children) == 1 and children[0].is_dir() else directory


def dependency_notices(work):
    sections = []
    for name, files in NOTICE_FILES.items():
        root = source_root(work, name)
        for filename in files:
            path = root / filename
            sections.append(
                f"{name} — {filename}\n{'=' * 60}\n\n" + path.read_text(encoding="utf-8")
            )
    headers = source_root(work, "nv-codec-headers") / "include/ffnvcodec"
    for path in sorted(headers.glob("*.h")):
        text = path.read_text(encoding="utf-8")
        license_header = re.search(r"/\*.*?\*/", text, re.DOTALL)
        if not license_header:
            raise ValueError(f"No license header found in {path.name}")
        sections.append(f"nv-codec-headers — {path.name}\n{'=' * 60}\n\n" + license_header[0])
    for path in sorted((HERE / "licenses").glob("*.txt")):
        sections.append(f"{path.name}\n{'=' * 60}\n\n" + path.read_text(encoding="utf-8"))
    return "\n\n".join(sections) + "\n"


def make_bundle(work, archives, target):
    lock = json.loads((HERE / "sources.json").read_text(encoding="utf-8"))
    for name in COMPONENTS:
        source = lock["sources"][name]
        if sha256(archives / source["filename"]) != source["sha256"]:
            raise ValueError(f"Source archive checksum mismatch: {name}")
        stamp = json.loads((work / "stamps" / f"{name}.json").read_text(encoding="utf-8"))
        if stamp["source"] != source["sha256"]:
            raise ValueError(f"Build used a different source archive: {name}")
    output = work / "output"
    ffmpeg_source = source_root(work, "ffmpeg")
    shutil.copy2(ffmpeg_source / "COPYING.GPLv3", output / "LICENSE")
    (output / "FFmpeg-dependencies.txt").write_text(dependency_notices(work), encoding="utf-8")
    binaries = {name: sha256(output / "bin" / name) for name in ("ffmpeg.exe", "ffprobe.exe")}
    configure = json.loads((output / "configure.json").read_text(encoding="utf-8"))
    if "--enable-indev=lavfi" not in configure:
        raise ValueError("The tested build recipe must include the lavfi fixture input")
    process = subprocess.run(
        [str(output / "bin/ffmpeg.exe"), "-version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    information = dict(
        format=1,
        ffmpeg_version=lock["sources"]["ffmpeg"]["version"],
        license="GPL-3.0-or-later",
        binaries=binaries,
        sources=lock["sources"],
        configure=configure,
        toolchain=json.loads((work / "toolchain.json").read_text(encoding="utf-8")),
        patches=[],
        build_output=process.stdout,
    )
    info_bytes = (json.dumps(information, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (output / "build-information.json").write_bytes(info_bytes)
    (output / "README.txt").write_text(
        "FFmpeg Windows build for Lightpress\n\n"
        f"FFmpeg: {information['ffmpeg_version']}\nLicense: GPL v3 or later\n"
        f"Corresponding source asset: {target.name}\n\n"
        "Download the corresponding-source asset from the same release page as Lightpress.\n"
        "It contains the exact source archives, build recipe, notices and source checksums.\n",
        encoding="utf-8",
    )
    payload = {"build-information.json": info_bytes}
    for filename in ("build.py", "sources.json", "README.md"):
        payload[filename] = (HERE / filename).read_bytes()
    payload["COPYING.GPLv3"] = (output / "LICENSE").read_bytes()
    payload["THIRD_PARTY_NOTICES.txt"] = (output / "FFmpeg-dependencies.txt").read_bytes()
    for record in lock["sources"].values():
        payload["archives/" + record["filename"]] = (archives / record["filename"]).read_bytes()
    for path in sorted((HERE / "licenses").glob("*.txt")):
        payload["licenses/" + path.name] = path.read_bytes()
    payload["licenses/Lightpress-build-scripts-MIT.txt"] = (
        HERE.parents[1] / "LICENSE"
    ).read_bytes()
    manifest = {name: hashlib.sha256(data).hexdigest() for name, data in payload.items()}
    payload["SHA256SUMS.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    target.parent.mkdir(parents=True, exist_ok=True)
    root_name = f"ffmpeg-{information['ffmpeg_version']}-lightpress-source"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, data in sorted(payload.items()):
            archive.writestr(f"{root_name}/{name}", data)
    target.with_suffix(".zip.sha256").write_text(
        f"{sha256(target)}  {target.name}\n", encoding="utf-8"
    )
    verify_bundle(target, output / "bin")
    return information


def verify_bundle(path, binary_dir=None):
    with zipfile.ZipFile(path) as archive:
        members = {}
        for member in archive.infolist():
            parts = PurePosixPath(member.filename).parts
            name = "/".join(parts[1:])
            if (
                len(parts) < 2
                or ".." in parts
                or PurePosixPath(member.filename).is_absolute()
                or name in members
            ):
                raise ValueError("Invalid corresponding-source archive layout")
            members[name] = member
        manifest = json.loads(archive.read(members["SHA256SUMS.json"]))
        required = {
            "build.py",
            "sources.json",
            "README.md",
            "COPYING.GPLv3",
            "THIRD_PARTY_NOTICES.txt",
            "build-information.json",
        }
        if not required.issubset(manifest):
            raise ValueError("Corresponding-source archive is missing build or license files")
        if set(members) != set(manifest) | {"SHA256SUMS.json"}:
            raise ValueError("Corresponding-source file list differs from its manifest")
        for name, checksum in manifest.items():
            if hashlib.sha256(archive.read(members[name])).hexdigest() != checksum:
                raise ValueError(f"Corresponding-source content checksum mismatch: {name}")
        info = json.loads(archive.read(members["build-information.json"]))
        if set(info["binaries"]) != {"ffmpeg.exe", "ffprobe.exe"}:
            raise ValueError("Unexpected FFmpeg binary file list")
        lock = json.loads(archive.read(members["sources.json"]))
        if info["sources"] != lock["sources"]:
            raise ValueError("Source lock differs from the build information")
        for name in COMPONENTS:
            record = info["sources"][name]
            data = archive.read(members["archives/" + record["filename"]])
            if hashlib.sha256(data).hexdigest() != record["sha256"]:
                raise ValueError(f"Locked source checksum mismatch: {name}")
        if binary_dir is not None:
            for name, checksum in info["binaries"].items():
                if sha256(binary_dir / name) != checksum:
                    raise ValueError(f"FFmpeg binary does not match the source bundle: {name}")
        return info


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--archives", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--binary-dir", type=Path)
    args = parser.parse_args()
    if args.verify:
        info = verify_bundle(args.verify, args.binary_dir)
    else:
        if not all((args.work_dir, args.archives, args.output)):
            parser.error("--work-dir, --archives and --output are required")
        info = make_bundle(args.work_dir.resolve(), args.archives.resolve(), args.output.resolve())
    print(
        json.dumps(
            dict(version=info["ffmpeg_version"], binaries=info["binaries"], verified=True), indent=2
        )
    )


if __name__ == "__main__":
    main()
