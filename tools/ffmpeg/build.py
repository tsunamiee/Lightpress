"""Build the Windows FFmpeg tools from the locked source archives."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

HERE = Path(__file__).resolve().parent
COMPONENTS = ("zlib", "opus", "dav1d", "x264", "x265", "svt-av1", "nv-codec-headers", "ffmpeg")


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class Build:
    def __init__(self, args):
        self.args = args
        self.work = args.work_dir.resolve()
        self.archives = args.archives.resolve()
        self.prefix = self.work / "prefix"
        self.output = self.work / "output"
        self.logs = self.work / "logs"
        for folder in (self.prefix, self.output, self.logs, self.work / "stamps"):
            folder.mkdir(parents=True, exist_ok=True)
        self.lock = json.loads((HERE / "sources.json").read_text(encoding="utf-8"))
        self.env = os.environ.copy()
        extra_paths = [args.gcc_bin, args.nasm.parent, args.ninja.parent, args.cmake.parent]
        self.env["PATH"] = (
            os.pathsep.join(str(path.resolve()) for path in extra_paths)
            + os.pathsep
            + self.env["PATH"]
        )
        self.env["PYTHONPATH"] = str(args.meson_modules.resolve())
        self.env["PKG_CONFIG_PATH"] = str(self.prefix / "lib/pkgconfig")
        self.env["PKG_CONFIG_LIBDIR"] = self.env["PKG_CONFIG_PATH"]
        self.env["SOURCE_DATE_EPOCH"] = "1741564800"
        temporary = self.work / "tmp"
        temporary.mkdir(exist_ok=True)
        for name in ("TMPDIR", "TMP", "TEMP"):
            self.env[name] = temporary.as_posix()
        self.env["CMAKE_BUILD_PARALLEL_LEVEL"] = str(args.jobs)
        self.flags = f"-O2 -ffile-prefix-map={self.work.as_posix()}=/usr/src/lightpress-ffmpeg"
        self.env["CFLAGS"] = self.flags
        self.env["CXXFLAGS"] = self.flags
        self.env["LDFLAGS"] = "-static-libgcc -static-libstdc++"
        self.env["CC"] = "gcc"
        self.env["CXX"] = "g++"
        self.record_toolchain()

    def record_toolchain(self):
        commands = {
            "gcc": [self.args.gcc_bin / "gcc.exe", "--version"],
            "target": [self.args.gcc_bin / "gcc.exe", "-dumpmachine"],
            "cmake": [self.args.cmake, "--version"],
            "ninja": [self.args.ninja, "--version"],
            "nasm": [self.args.nasm, "--version"],
            "meson": [sys.executable, "-m", "mesonbuild.mesonmain", "--version"],
            "bash": [self.args.bash, "--version"],
        }
        versions = {"python": sys.version.split()[0]}
        for name, command in commands.items():
            result = subprocess.run(
                [str(part) for part in command],
                env=self.env,
                capture_output=True,
                text=True,
                check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            versions[name] = result.stdout.splitlines()[0]
        version_file = self.args.gcc_bin.parent / "VERSION.txt"
        if version_file.is_file():
            versions["w64devkit"] = version_file.read_text(encoding="utf-8").strip()
        (self.work / "toolchain.json").write_text(
            json.dumps(versions, indent=2) + "\n", encoding="utf-8"
        )

    def run(self, label, command, cwd=None, input=None):
        cwd = cwd or self.work
        (self.work / "state.json").write_text(
            json.dumps(dict(step=label, command=[str(part) for part in command]), indent=2),
            encoding="utf-8",
        )
        print(label, flush=True)
        with (self.logs / f"{label}.log").open("wb") as log:
            subprocess.run(
                [str(part) for part in command],
                cwd=cwd,
                env=self.env,
                input=input.encode() if input is not None else None,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0),
            )

    def source(self, name):
        record = self.lock["sources"][name]
        archive_path = self.archives / record["filename"]
        if sha256(archive_path) != record["sha256"]:
            raise ValueError(f"Source checksum mismatch: {record['filename']}")
        destination = self.work / "sources" / name
        if not destination.exists():
            destination.mkdir(parents=True)
            with tarfile.open(archive_path) as archive:
                archive.extractall(destination, filter="data")
        children = list(destination.iterdir())
        return children[0] if len(children) == 1 and children[0].is_dir() else destination

    def cmake(self, name, source, options=(), install=True):
        folder = self.work / "build" / name
        self.run(
            f"{name}-configure",
            [
                self.args.cmake,
                "-S",
                source,
                "-B",
                folder,
                "-G",
                "Ninja",
                f"-DCMAKE_MAKE_PROGRAM={self.args.ninja.resolve().as_posix()}",
                "-DCMAKE_BUILD_TYPE=Release",
                f"-DCMAKE_INSTALL_PREFIX={self.prefix.as_posix()}",
                "-DCMAKE_INSTALL_LIBDIR=lib",
                "-DCMAKE_C_COMPILER=gcc",
                "-DCMAKE_CXX_COMPILER=g++",
                f"-DCMAKE_C_FLAGS={self.flags}",
                f"-DCMAKE_CXX_FLAGS={self.flags}",
                "-DCMAKE_EXE_LINKER_FLAGS=-static-libgcc -static-libstdc++",
                "-DCMAKE_SHARED_LINKER_FLAGS=-static-libgcc -static-libstdc++",
                *options,
            ],
        )
        self.run(
            f"{name}-compile",
            [self.args.cmake, "--build", folder, "--parallel", str(self.args.jobs)],
        )
        if install:
            self.run(f"{name}-install", [self.args.cmake, "--install", folder])
        return folder

    def build_zlib(self, source):
        folder = self.cmake("zlib", source, ["-DZLIB_BUILD_EXAMPLES=OFF"], install=False)
        (self.prefix / "include").mkdir(exist_ok=True)
        (self.prefix / "lib/pkgconfig").mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / "zlib.h", self.prefix / "include/zlib.h")
        shutil.copy2(folder / "zconf.h", self.prefix / "include/zconf.h")
        shutil.copy2(folder / "libzlibstatic.a", self.prefix / "lib/libz.a")
        self.pc("zlib", "zlib", self.lock["sources"]["zlib"]["version"], "-lz")

    def pc(self, filename, name, version, libraries, private=""):
        folder = self.prefix / "lib/pkgconfig"
        folder.mkdir(parents=True, exist_ok=True)
        text = f"prefix={self.prefix.as_posix()}\nlibdir=${{prefix}}/lib\nincludedir=${{prefix}}/include\n\nName: {name}\nDescription: {name}\nVersion: {version}\nLibs: -L${{libdir}} {libraries}\nLibs.private: {private}\nCflags: -I${{includedir}}\n"
        (folder / f"{filename}.pc").write_text(text, encoding="utf-8")

    def build_opus(self, source):
        self.cmake(
            "opus",
            source,
            [
                "-DBUILD_SHARED_LIBS=OFF",
                "-DOPUS_BUILD_PROGRAMS=OFF",
                "-DOPUS_BUILD_TESTING=OFF",
                "-DOPUS_INSTALL_PKG_CONFIG_MODULE=ON",
                "-DOPUS_INSTALL_CMAKE_CONFIG_MODULE=OFF",
            ],
        )

    def build_dav1d(self, source):
        folder = self.work / "build/dav1d"
        if not (folder / "build.ninja").exists():
            self.run(
                "dav1d-configure",
                [
                    sys.executable,
                    "-m",
                    "mesonbuild.mesonmain",
                    "setup",
                    folder,
                    source,
                    "--prefix",
                    self.prefix.as_posix(),
                    "--libdir",
                    "lib",
                    "--buildtype",
                    "release",
                    "--default-library",
                    "static",
                    "-Denable_tools=false",
                    "-Denable_tests=false",
                ],
            )
        self.run("dav1d-compile", [self.args.ninja, "-C", folder, "-j", str(self.args.jobs)])
        self.run("dav1d-install", [self.args.ninja, "-C", folder, "install"])

    def build_x264(self, source):
        folder = self.work / "build/x264"
        folder.mkdir(parents=True, exist_ok=True)
        self.run(
            "x264-configure",
            [
                self.args.bash,
                source / "configure",
                f"--prefix={self.prefix.as_posix()}",
                "--enable-static",
                "--disable-shared",
                "--disable-cli",
                "--disable-opencl",
                "--bit-depth=all",
            ],
            folder,
        )
        self.run(
            "x264-compile", [self.args.gcc_bin / "make.exe", "-j", str(self.args.jobs)], folder
        )
        self.run("x264-install", [self.args.gcc_bin / "make.exe", "install"], folder)

    def build_x265(self, source):
        options = [
            "-DENABLE_SHARED=OFF",
            "-DENABLE_CLI=OFF",
            "-DENABLE_LIBNUMA=OFF",
            "-DENABLE_TESTS=OFF",
            "-DENABLE_HDR10_PLUS=OFF",
        ]
        high = self.cmake(
            "x265-10",
            source / "source",
            [*options, "-DHIGH_BIT_DEPTH=ON", "-DEXPORT_C_API=OFF"],
            install=False,
        )
        main = self.work / "build/x265-8"
        main.mkdir(parents=True, exist_ok=True)
        shutil.copy2(high / "libx265.a", main / "libx265_main10.a")
        self.cmake(
            "x265-8",
            source / "source",
            [*options, "-DEXTRA_LIB=x265_main10.a", "-DEXTRA_LINK_FLAGS=-L.", "-DLINKED_10BIT=ON"],
            install=False,
        )
        shutil.copy2(main / "libx265.a", main / "libx265_main.a")
        self.run(
            "x265-combine",
            [self.args.gcc_bin / "ar.exe", "-M"],
            main,
            "CREATE libx265.a\nADDLIB libx265_main.a\nADDLIB libx265_main10.a\nSAVE\nEND\n",
        )
        (self.prefix / "include").mkdir(exist_ok=True)
        shutil.copy2(source / "source/x265.h", self.prefix / "include/x265.h")
        shutil.copy2(main / "x265_config.h", self.prefix / "include/x265_config.h")
        shutil.copy2(main / "libx265.a", self.prefix / "lib/libx265.a")
        self.pc("x265", "x265", self.lock["sources"]["x265"]["version"], "-lx265", "-lstdc++ -lm")

    def build_svt_av1(self, source):
        self.cmake(
            "svt-av1",
            source,
            [
                "-DBUILD_SHARED_LIBS=OFF",
                "-DBUILD_APPS=OFF",
                "-DBUILD_TESTING=OFF",
                "-DSVT_AV1_LTO=OFF",
                "-DEXCLUDE_HASH=ON",
                "-DREPRODUCIBLE_BUILDS=ON",
            ],
        )

    def build_nv_codec_headers(self, source):
        shutil.copytree(
            source / "include/ffnvcodec", self.prefix / "include/ffnvcodec", dirs_exist_ok=True
        )
        text = (
            (source / "ffnvcodec.pc.in")
            .read_text(encoding="utf-8")
            .replace("@@PREFIX@@", self.prefix.as_posix())
        )
        (self.prefix / "lib/pkgconfig/ffnvcodec.pc").write_text(text, encoding="utf-8")

    def build_ffmpeg(self, source):
        folder = self.work / "build/ffmpeg"
        folder.mkdir(parents=True, exist_ok=True)
        # configure preserves an existing wrapper, including paths from another shell.
        (folder / "Makefile").unlink(missing_ok=True)
        relative_source = os.path.relpath(source, folder).replace("\\", "/")
        relative_prefix = os.path.relpath(self.prefix, folder).replace("\\", "/")
        self.env["CFLAGS"] = f"{self.flags} -I{relative_prefix}/include"
        self.env["CXXFLAGS"] = self.env["CFLAGS"]
        self.env["LDFLAGS"] = f"-L{relative_prefix}/lib -static -static-libgcc -static-libstdc++"
        options = [
            "--prefix=/lightpress-ffmpeg",
            "--target-os=mingw32",
            "--arch=x86_64",
            "--cc=gcc",
            "--cxx=g++",
            "--pkg-config=pkg-config",
            "--pkg-config-flags=--static",
            "--enable-gpl",
            "--enable-version3",
            "--disable-autodetect",
            "--disable-shared",
            "--enable-static",
            "--disable-debug",
            "--disable-doc",
            "--disable-ffplay",
            "--disable-network",
            "--disable-devices",
            "--enable-indev=lavfi",
            "--enable-libx264",
            "--enable-libx265",
            "--enable-libsvtav1",
            "--enable-libdav1d",
            "--enable-libopus",
            "--enable-zlib",
            "--enable-ffnvcodec",
            "--enable-nvenc",
        ]
        self.run(
            "ffmpeg-configure",
            [self.args.gcc_bin / "sh.exe", f"{relative_source}/configure", *options],
            folder,
        )
        self.run(
            "ffmpeg-compile", [self.args.gcc_bin / "make.exe", "-j", str(self.args.jobs)], folder
        )
        (self.output / "bin").mkdir(exist_ok=True)
        for name in ("ffmpeg.exe", "ffprobe.exe"):
            shutil.copy2(folder / name, self.output / "bin" / name)
        (self.output / "configure.json").write_text(json.dumps(options, indent=2), encoding="utf-8")

    def build(self, name):
        source = self.source(name)
        stamp = self.work / "stamps" / f"{name}.json"
        if stamp.exists() and name not in self.args.rebuild:
            if (
                json.loads(stamp.read_text(encoding="utf-8"))["source"]
                != self.lock["sources"][name]["sha256"]
            ):
                raise ValueError("Source lock changed; use a new build directory.")
            print(f"{name}: already built", flush=True)
            return
        getattr(self, "build_" + name.replace("-", "_"))(source)
        stamp.write_text(
            json.dumps(
                dict(source=self.lock["sources"][name]["sha256"], recipe=sha256(Path(__file__))),
                indent=2,
            ),
            encoding="utf-8",
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--archives", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    for name in ("gcc-bin", "cmake", "ninja", "nasm", "bash", "meson-modules"):
        parser.add_argument(f"--{name}", type=Path)
    parser.add_argument("--jobs", type=int, default=2, choices=range(1, 9))
    parser.add_argument("--only", nargs="+", choices=COMPONENTS)
    parser.add_argument("--rebuild", nargs="*", default=[], choices=COMPONENTS)
    args = parser.parse_args()
    if args.verify_only:
        lock = json.loads((HERE / "sources.json").read_text(encoding="utf-8"))
        for record in lock["sources"].values():
            if sha256(args.archives / record["filename"]) != record["sha256"]:
                raise ValueError(f"Source checksum mismatch: {record['filename']}")
        print("All source archive checksums match the lock file.")
        return
    for name in ("gcc_bin", "cmake", "ninja", "nasm", "bash", "meson_modules"):
        if getattr(args, name) is None:
            parser.error(f"--{name.replace('_', '-')} is required for compilation")
    build = Build(args)
    for name in args.only or COMPONENTS:
        build.build(name)
    (build.work / "state.json").write_text(
        json.dumps(dict(status="complete", components=args.only or COMPONENTS), indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
