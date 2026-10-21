# Third-party notices

English | [简体中文](THIRD_PARTY_NOTICES.zh-CN.md)

Lightpress source code is licensed under MIT. Third-party components remain subject to their respective licenses. Full license texts are included in `licenses/` and can be viewed in the application's **Open-source components** window.

## Application components

| Component | License | Source and notices |
| --- | --- | --- |
| Pillow | MIT-CMU, with bundled library notices | [Source](https://github.com/python-pillow/Pillow); `licenses/Pillow.txt` |
| Lucide icons | ISC; MIT for portions derived from Feather | [Source](https://github.com/lucide-icons/lucide); `licenses/Lucide.txt` |
| resvg-py | MIT | [Source](https://github.com/baseplate-admin/resvg-py); `licenses/resvg-py.txt` |
| resvg | MIT or Apache 2.0 | [Source](https://github.com/linebender/resvg); `licenses/resvg-MIT.txt`, `licenses/resvg-Apache-2.0.txt` |
| Python | PSF License | [License](https://www.python.org/psf/license/); `licenses/Python.txt` |
| Tcl/Tk | Tcl/Tk license terms | [License](https://www.tcl-lang.org/software/tcltk/license.html); `licenses/Tk-license.terms` |
| PyInstaller bootloader | GPL with an exception for distributing generated applications | [License](https://pyinstaller.org/en/stable/license.html); `licenses/PyInstaller.txt` |

## FFmpeg

The Windows portable release includes FFmpeg 7.1.5, built from source under GPL v3 or later. Lightpress invokes FFmpeg as a separate process. The application's MIT license does not cover FFmpeg or its dependencies.

The build includes x264, x265, SVT-AV1, dav1d, Opus, zlib and NVIDIA encoding interfaces. Exact source versions, download URLs and checksums are recorded in `tools/ffmpeg/sources.json`; the build recipe is documented in `tools/ffmpeg/README.md`.

The same Release provides `FFmpeg-7.1.5-Lightpress-source.zip`, containing the upstream source archives used for the build, build scripts, configuration, toolchain versions and license materials. This archive is not required to run the application.

The portable package contains these records:

| File | Contents |
| --- | --- |
| `FFmpeg-SOURCE.txt` | Matching source asset name and SHA-256 checksum |
| `licenses/FFmpeg.txt` | GPL v3 license text |
| `licenses/FFmpeg-dependencies.txt` | Dependency licenses and attribution notices |
| `licenses/FFmpeg-build-information.json` | Source versions, build options, toolchain and executable checksums |
| `bundle.json` | Application component versions and FFmpeg source reference |
| `SHA256SUMS.json` | Portable package file checksums |

Builds made without bundled FFmpeg use the user's installed copy and its applicable license. Redistributors must provide the materials required by the license of the actual FFmpeg build they distribute. See [FFmpeg's licensing information](https://ffmpeg.org/legal.html).

## Codec patent policies

Software licenses and media patent rights are separate matters. See the published policies from [AOMedia](https://aomedia.org/about/legal/) and [Opus](https://opus-codec.org/license/).
