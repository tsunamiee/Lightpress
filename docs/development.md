# 开发与构建

界面使用 Tkinter，SVG 图标通过 resvg-py 按显示尺寸渲染，图片通过 Pillow 编码，视频以独立进程调用 FFmpeg。最低 Python 版本为 3.11；Windows 便携版在 Python 3.13 下构建。

## 环境

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m compressor
```

视频测试需要 PATH 中有 FFmpeg 和 ffprobe，包含 `libx264`、`libx265`、`libsvtav1`、`aac`、`libopus`。

## 检查

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
python -m black --check compressor tests tools main.py build_release.py
python -m pyflakes compressor tests tools main.py build_release.py
```

界面检查需要桌面会话，使用生成的素材，数据写入指定测试目录：

```powershell
python -m tests.compact_smoke artifacts/compact
```

`python -m compressor --check artifacts/environment.json` 检查 SVG 渲染、四种图片格式的编码 / 解码、视频依赖、系统语言和配置位置，不保存用户配置。`--classic` 可打开原有完整参数界面。

## Windows 发行版

```powershell
python build_release.py --ffmpeg-dir C:\Build\ffmpeg\output\bin `
  --ffmpeg-source-bundle release/FFmpeg-7.1.5-Lightpress-source.zip
```

省略 `--ffmpeg-dir` 时不捆绑 FFmpeg。捆绑时必须同时提供对应源码包，构建脚本先校验源码包内容及两个可执行文件的哈希，再进行打包。

FFmpeg 的源码版本和校验值固定在 `tools/ffmpeg/sources.json`；工具链及完整编译步骤见 [FFmpeg 构建说明](../tools/ffmpeg/README.md)。完成编译后生成对应源码包：

```powershell
python -m tools.ffmpeg.bundle --work-dir C:/Build/ffmpeg `
  --archives C:/Build/archives --output release/FFmpeg-7.1.5-Lightpress-source.zip
```

程序位于 `release/<版本>/Lightpress/Lightpress.exe`，便携 ZIP 位于 `release/`。构建记录组件版本、FFmpeg 参数和文件哈希，并复制许可证。程序文件名保持英文，窗口名称由界面语言决定。`data/` 不进入发行包，用户在解压后首次运行时生成。

发布便携版时，将 FFmpeg 对应源码包及其 `.sha256` 校验文件放在同一 Release 的附件中。该包包含全部锁定的依赖源码、构建材料及许可声明，不需要放入主 Git 仓库。

源码包按文件清单生成，不包含本机配置、运行报告、构建产物、测试媒体或本地开发配置：

```powershell
python tools/source_archive.py
python tools/check_release.py --source-archive release/Lightpress-1.0.0-source.zip `
  --application-dir release/1.0.0/Lightpress `
  --ffmpeg-source-bundle release/FFmpeg-7.1.5-Lightpress-source.zip
```

检查涵盖发布文件清单、本机路径、常见凭据和图片元数据。报告只记录文件名与问题类型，不记录匹配到的敏感内容。提交前仍需人工确认新增文件、截图和日志。

## 代码结构

| 模块 | 职责 |
| --- | --- |
| `compact.py` | 默认轻量窗口与后台事件处理 |
| `graphics.py` / `about.py` | SVG 渲染、关于窗口与本地许可证查看器 |
| `dialogs.py` | 高级设置与任务详情 |
| `strings.py` | 简体中文与英文文案 |
| `formats.py` | 格式定义与五挡质量映射 |
| `jobs.py` | 文件选择、筛选与任务准备 |
| `core.py` | 扫描、编码队列、取消、命名与提交 |
| `storage.py` | 软件目录下的配置、原子写入、首次系统语言 |
| `history.py` | SQLite 处理记录与旧记录迁移 |
| `image_engine.py` | 图片转换、透明度、元数据与校验 |
| `video_engine.py` | FFmpeg 参数、探测与校验 |
| `window_theme.py` | Windows 原生标题栏主题 |
| `ui.py` / `theme.py` | 原有完整参数界面 |

后台线程只向事件队列写入，不接触 Tk。输出先写临时文件并校验，再提交到目标；轻量界面不覆盖原件，重名提交使用独占创建。停止与退出时清理当前临时文件。

新格式应同时补充编码、解码验证、元数据开关、透明度和缓存测试。语言修改需保持两份文案的键一致。
