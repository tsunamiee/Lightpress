# FFmpeg build for Lightpress

This recipe builds Windows x64 `ffmpeg.exe` and `ffprobe.exe` from the source archives listed in `sources.json`. It enables H.264, HEVC and AV1 encoding, AV1 decoding, AAC and Opus audio, NVIDIA encoder interfaces, and FFmpeg's native file formats and filters. Network input and physical capture devices are disabled; the `lavfi` virtual input is retained for generated test fixtures.

The resulting FFmpeg build is distributed under GPL v3 or later. Lightpress build scripts use the MIT license; see `licenses/Lightpress-build-scripts-MIT.txt` in the corresponding-source asset. Each upstream source archive retains its own license files. Compiler runtime notices are included separately.

## Contents of the corresponding-source asset

- `archives/`: the exact upstream source archives used in the build.
- `sources.json`: versions, original URLs and SHA-256 checksums.
- `build.py`: the complete build recipe. No upstream source patches are used.
- `build-information.json`: enabled options, toolchain versions and the hashes of the matching executables.
- `THIRD_PARTY_NOTICES.txt`, `COPYING.GPLv3`, `licenses/`: license and attribution materials.
- `SHA256SUMS.json`: checksums for the source asset's files.

This asset does not contain the compiler or the resulting executables. Install the general-purpose build tools below, then build using the included archives; source downloads are not needed during compilation.

## Build tools

The tested Windows toolchain is GCC 15.2.0 from w64devkit 2.5.0, CMake 3.31.6, Ninja 1.12.1, NASM 2.16.03, Meson 1.7.2, Git for Windows Bash, and Python 3.13. The tools must target Windows x86-64; no MSYS2 runtime DLL is linked into the output.

Sources for the general-purpose tools:

- [w64devkit](https://github.com/skeeto/w64devkit/releases/tag/v2.5.0)
- [CMake](https://cmake.org/download/), [Ninja](https://github.com/ninja-build/ninja/releases)
- [NASM](https://www.nasm.us/pub/nasm/releasebuilds/2.16.03/)
- [Meson](https://pypi.org/project/meson/1.7.2/), [Git for Windows](https://gitforwindows.org/)

## Compile

Use a short working path without spaces. Set each tool path to its actual location. `--meson-modules` is the directory containing the installed `mesonbuild` Python package; it can be a separate `pip install --target` directory.

```powershell
python build.py --work-dir C:/Build/ffmpeg --archives archives --verify-only

python build.py --work-dir C:/Build/ffmpeg --archives archives `
  --gcc-bin C:/BuildTools/w64devkit/bin `
  --cmake C:/BuildTools/cmake/bin/cmake.exe `
  --ninja C:/BuildTools/ninja/ninja.exe `
  --nasm C:/BuildTools/nasm/nasm.exe `
  --bash "C:/Program Files/Git/bin/bash.exe" `
  --meson-modules C:/BuildTools/python-packages --jobs 2
```

The executables are written to `C:/Build/ffmpeg/output/bin`. Component logs and progress are saved below the working directory. Build processes use a low scheduling priority and do not open console windows. Completed components are reused; use a new working directory when changing the source lock.

The recipe compiles x264 for 8-bit and 10-bit output and combines x265's 8-bit and 10-bit libraries. All non-system codec libraries are linked statically. NVIDIA encoding still requires a supported GPU and driver at runtime; their binaries are not part of this source asset.

The build records source and output hashes. It does not claim that different compilers or build paths produce byte-identical executables.
