# 第三方组件声明

[English](THIRD_PARTY_NOTICES.md) | 简体中文

轻压源码采用 MIT 许可证，第三方组件遵循各自的许可条款。完整许可文本随附于 `licenses/` 文件夹，也可在应用的“开源组件”窗口查看。

## 应用组件

| 组件 | 许可证 | 来源与声明 |
| --- | --- | --- |
| Pillow | MIT-CMU，含随附图像库的声明 | [源码](https://github.com/python-pillow/Pillow)；`licenses/Pillow.txt` |
| Lucide 图标 | ISC；部分源自 Feather 的内容采用 MIT | [源码](https://github.com/lucide-icons/lucide)；`licenses/Lucide.txt` |
| resvg-py | MIT | [源码](https://github.com/baseplate-admin/resvg-py)；`licenses/resvg-py.txt` |
| resvg | MIT 或 Apache 2.0 | [源码](https://github.com/linebender/resvg)；`licenses/resvg-MIT.txt`、`licenses/resvg-Apache-2.0.txt` |
| Python | PSF License | [许可](https://www.python.org/psf/license/)；`licenses/Python.txt` |
| Tcl/Tk | Tcl/Tk 许可条款 | [许可](https://www.tcl-lang.org/software/tcltk/license.html)；`licenses/Tk-license.terms` |
| PyInstaller 引导程序 | GPL，附针对生成应用分发的例外 | [许可](https://pyinstaller.org/en/stable/license.html)；`licenses/PyInstaller.txt` |

## FFmpeg

Windows 便携版包含从源码构建的 FFmpeg 7.1.5，采用 GPL v3 或以后版本。轻压以独立进程调用 FFmpeg；应用的 MIT 许可证不覆盖 FFmpeg 及其依赖。

该构建包含 x264、x265、SVT-AV1、dav1d、Opus、zlib 和 NVIDIA 编码接口。确切版本、下载地址与校验值记录在 `tools/ffmpeg/sources.json`，构建步骤见 `tools/ffmpeg/README.md`。

同一 Release 提供 `FFmpeg-7.1.5-Lightpress-source.zip`，包含实际使用的上游源码归档、构建脚本、配置、工具链版本及许可材料。运行应用无需下载该文件。

便携包中附有以下记录：

| 文件 | 内容 |
| --- | --- |
| `FFmpeg-SOURCE.txt` | 对应源码包名称及 SHA-256 校验值 |
| `licenses/FFmpeg.txt` | GPL v3 许可原文 |
| `licenses/FFmpeg-dependencies.txt` | 依赖的许可证及署名声明 |
| `licenses/FFmpeg-build-information.json` | 源码版本、构建参数、工具链及可执行文件校验值 |
| `bundle.json` | 应用组件版本及 FFmpeg 源码包信息 |
| `SHA256SUMS.json` | 便携包文件校验值 |

不捆绑 FFmpeg 的构建使用用户自行安装的版本，并适用该版本的许可证。再次分发时，应按实际 FFmpeg 构建的许可提供相应材料，详见 [FFmpeg 许可说明](https://ffmpeg.org/legal.html)。

## 编解码格式的专利政策

软件许可与媒体格式的专利授权是不同事项。相关政策见 [AOMedia](https://aomedia.org/about/legal/) 和 [Opus](https://opus-codec.org/license/)。
