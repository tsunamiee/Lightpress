# Lightpress（轻压）

[English](README.md) | 简体中文

轻压是一款轻量的 Windows 图片与视频压缩工具。支持单个文件与文件夹批量转换，可选择输出格式和质量，保留原文件。所有文件均在本地处理。

![轻压浅色界面](docs/screenshots/light.png)

[深色外观](docs/screenshots/dark.png) · [使用说明](docs/usage.md) · [开发与构建](docs/development.md)

## 功能

- 批量转换图片和视频，支持子文件夹及文件筛选。
- JPEG、WebP、AVIF、PNG、H.264、H.265 和 AV1，统一提供五挡质量选择。
- 支持 CPU 视频编码，也可使用 NVIDIA 显卡加速。
- 显示转换进度，支持取消任务和查看逐个文件的处理结果。
- 支持中英文，可自动识别系统语言或手动切换。
- 提供浅色、深色主题，配置随软件保存在本地。

## 开始使用

从 Releases 下载 `Lightpress-1.0.0-Windows-x64.zip`，完整解压后运行 `Lightpress.exe`。请保留同目录的 `bin` 和 `_internal` 文件夹。便携版已包含 Python、FFmpeg 和 ffprobe，无需另行安装运行环境。

1. 使用输入框右侧的图标选择文件或文件夹。
2. 选择输出文件夹、格式和质量档位。
3. 点击“转换”。点击底部状态行可查看每个文件的处理结果。

“自动”模式将图片转换为 AVIF，视频转换为 H.264 MP4。选择具体格式时，只处理对应类型的文件。设置中提供文件筛选、元数据保留、视频编码器和帧率选项。

## 格式支持

| 类型 | 输入 | 输出 |
| --- | --- | --- |
| 图片 | JPEG、PNG、WebP、AVIF、TIFF、BMP | JPEG、WebP、AVIF、PNG |
| 视频 | MP4、MOV、MKV、M4V、AVI、WebM、MTS、TS | MP4（H.264/H.265/AV1 + AAC）、WebM（AV1 + Opus） |

CPU 编码不需要独立显卡。NVIDIA 编码需要兼容的显卡与驱动。从源码运行时，可额外安装 `pillow-heif` 启用 HEIC/HEIF 输入；便携版不包含该插件。

## 配置与升级

配置和处理记录保存在软件目录下的 `data/` 文件夹中。请将软件解压到可写目录，升级时保留 `data/`。媒体输出文件夹中不会生成配置文件。

## 从源码运行

需要 Python 3.11 或更高版本。安装依赖后启动应用：

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m compressor
```

安装依赖后，也可通过 `start.bat` 启动。视频处理需要 FFmpeg 和 ffprobe，可放在项目的 `bin/` 文件夹或加入 PATH，并包含 `libx264`、`libx265`、`libsvtav1`、`aac` 和 `libopus` 编码器。测试及打包步骤见[开发说明](docs/development.md)。

## 媒体处理说明

- JPEG、WebP、AVIF 和视频转换采用有损编码，保持分辨率不等于无损。
- PNG 的前四挡质量会减少颜色数量，最高档保留原始颜色。JPEG 的透明区域以白色填充。
- 图片输出为 8-bit，不支持动画和多页图片；多图 JPEG 需在设置中选择仅保留主图。
- 实况照片的 JPG 与 MOV 分别处理，转换后不保留实况配对效果。
- 视频保留首个视频轨和所有音轨，不保留字幕、附件及其他视频轨。
- 不进行 Log、HDR、SDR 之间的色彩转换，也不保证保留 HDR 动态元数据。批量处理 HDR 素材前，请先检查少量样片。

质量参数、元数据和处理记录的详细说明见[使用说明](docs/usage.md)。

## 许可证

轻压源码采用 [MIT 许可证](LICENSE)。第三方组件遵循各自的许可证，详见[第三方组件声明](THIRD_PARTY_NOTICES.zh-CN.md)。

随附的 FFmpeg 构建采用 GPL v3 或以后版本。同一 Release 中的 `FFmpeg-7.1.5-Lightpress-source.zip` 提供其对应源码、依赖和构建材料，使用轻压无需下载该文件。
