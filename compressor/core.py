"""File discovery, task execution and output records."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from PIL import Image

from . import image_engine as images
from . import video_engine as video
from .history import History
from . import storage

Event = Callable[[str, dict], None]
VIDEO_EXTS = video.EXTS
IMAGE_EXTS = images.SUPPORTED_SUFFIXES
try:
    import pillow_heif

    pillow_heif.register_heif_opener()
    IMAGE_EXTS = IMAGE_EXTS | images.OPTIONAL_SUFFIXES
except (ImportError, OSError):
    pass


@dataclass(frozen=True)
class Options:
    image_quality: int = 55
    image_speed: int = 6
    sampling: str = "4:2:0"
    keep_exif: bool = True
    keep_icc: bool = True
    codec: str = "av1_cpu"
    rate_mode: str = "quality"
    video_quality: int = 30
    bitrate: int = 18
    maxrate: int = 30
    fps: str = "原始帧率"
    container: str = "mp4"
    skip_larger: bool = True
    image_primary_only: bool = False
    image_format: str = "AVIF"
    png_colors: int | None = None
    naming: str = "hashed"
    conflict: str = "replace"

    def validate(self):
        images.Options(
            self.image_quality,
            self.image_speed,
            self.sampling,
            format=self.image_format,
            png_colors=self.png_colors,
        ).validate()
        if self.codec not in video.ENCODERS:
            raise ValueError("请选择支持的视频编码器")
        if self.rate_mode not in ("quality", "bitrate"):
            raise ValueError("请选择有效的码率控制方式")
        if not 1 <= self.video_quality <= 51:
            raise ValueError("视频质量参数应为 1–51")
        if not 1 <= self.bitrate <= 500 or not self.bitrate <= self.maxrate <= 500:
            raise ValueError("码率应为 1–500 Mbps，最大码率不能小于目标码率")
        if self.container not in ("mp4", "webm"):
            raise ValueError("请选择 MP4 或 WebM")
        if self.container == "webm" and not self.codec.startswith("av1"):
            raise ValueError("此 WebM 输出仅支持 AV1，请使用 MP4 或选择 AV1")
        if self.naming not in ("hashed", "simple") or self.conflict not in (
            "replace",
            "number",
            "skip",
        ):
            raise ValueError("不支持的输出命名或重名处理方式")
        if self.fps != "原始帧率":
            from fractions import Fraction

            try:
                if (
                    not re.fullmatch(r"\d+(?:\.\d+)?(?:/\d+)?", self.fps)
                    or not 1 <= float(Fraction(self.fps)) <= 240
                ):
                    raise ValueError()
            except (ValueError, ZeroDivisionError):
                raise ValueError("帧率应为 1–240，例如 30、59.94、60000/1001") from None


@dataclass(frozen=True)
class Task:
    source: Path
    relative: Path
    kind: str
    size: int


class Cancellation:
    def __init__(self):
        self.event = threading.Event()
        self.lock = threading.Lock()
        self.process = None

    def cancel(self):
        self.event.set()
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                try:
                    self.process.terminate()
                except OSError:
                    pass

    def attach(self, process):
        with self.lock:
            self.process = process
            if process is not None and self.event.is_set() and process.poll() is None:
                process.terminate()


class ProcessingError(RuntimeError):
    def __init__(self, reason, code):
        self.code = code
        super().__init__(reason)


def settings_path():
    return storage.settings_path()


def read_settings():
    return storage.read_settings()


def save_settings(value):
    storage.save_settings(value)


def patterns(text: str) -> list[str]:
    result = [s.strip() for s in re.split("[;；\n]+", text) if s.strip()]
    for value in result:
        if value.lower().startswith("re:"):
            re.compile(value[3:], re.I)
    return result


def matches(relative: Path, values: list[str]) -> bool:
    names = (relative.name.casefold(), relative.as_posix().casefold())
    for value in values:
        if value.lower().startswith("re:"):
            if any(re.search(value[3:], name, re.I) for name in names):
                return True
        else:
            value = value.replace("\\", "/").casefold()
            if any(
                (
                    fnmatch.fnmatchcase(name, value)
                    if any(c in value for c in "*?[")
                    else value in name
                )
                for name in names
            ):
                return True
    return False


def validate_paths(source: str, output: str) -> tuple[Path, Path]:
    if not source.strip() or not output.strip():
        raise ValueError("请先选择来源文件夹和输出文件夹")
    root, dest = Path(source).expanduser().resolve(), Path(output).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("来源文件夹不存在")
    if root == dest or dest in root.parents:
        raise ValueError("输出目录不能与来源相同，也不能是来源的上级目录")
    return root, dest


def scan(
    root: Path,
    output: Path,
    include="*",
    exclude="",
    recursive=True,
    kind="all",
    cancel: Cancellation | None = None,
) -> list[Task]:
    root, output = root.resolve(), output.resolve()
    include_values, exclude_values = patterns(include), patterns(exclude)
    result = []
    for base, dirs, files in os.walk(root, followlinks=False):
        if cancel and cancel.event.is_set():
            break
        folder = Path(base)
        dirs[:] = sorted(
            d
            for d in dirs
            if recursive
            and not (folder / d).is_symlink()
            and (folder / d).resolve() != output
            and d != ".compressor"
        )
        for name in sorted(files):
            path = folder / name
            if path.is_symlink() or not path.is_file():
                continue
            ext = path.suffix.casefold()
            media = "image" if ext in IMAGE_EXTS else "video" if ext in VIDEO_EXTS else None
            if (
                media is None
                or (kind != "all" and kind != media)
                or ".partial." in name
                or ".failed." in name
            ):
                continue
            relative = path.relative_to(root)
            if include_values and not matches(relative, include_values):
                continue
            if exclude_values and matches(relative, exclude_values):
                continue
            result.append(Task(path, relative, media, path.stat().st_size))
    return sorted(result, key=lambda t: t.relative.as_posix().casefold())


def profile(task: Task, options: Options) -> dict:
    all_values = asdict(options)
    keys = (
        ("image_quality", "image_speed", "sampling", "keep_exif", "keep_icc")
        if task.kind == "image"
        else ("codec", "rate_mode", "video_quality", "bitrate", "maxrate", "fps", "container")
    )
    result = {key: all_values[key] for key in keys}
    if task.kind == "image" and options.image_primary_only:
        result["image_primary_only"] = True
    if task.kind == "image" and options.image_format != "AVIF":
        result["image_format"] = options.image_format
    if task.kind == "image" and options.image_format == "PNG":
        result["png_colors"] = options.png_colors
    return result


def destination(task: Task, output: Path, options: Options) -> Path:
    digest = hashlib.sha256(
        json.dumps(profile(task, options), sort_keys=True).encode()
    ).hexdigest()[:10]
    ext = (
        {"JPEG": "jpg", "WEBP": "webp", "PNG": "png", "AVIF": "avif"}[options.image_format]
        if task.kind == "image"
        else options.container
    )
    stem = task.source.stem[:70]
    if options.naming == "simple":
        return output / task.relative.parent / f"{stem}_compressed.{ext}"
    # Relative-path hash avoids collisions when long source names share a prefix.
    name_hash = hashlib.sha256(task.relative.as_posix().encode()).hexdigest()[:8]
    return (
        output
        / task.relative.parent
        / f"{stem}__{task.source.suffix[1:]}_{name_hash}_{digest}.{ext}"
    )


def fingerprint(task: Task, options: Options) -> dict:
    stat = task.source.stat()
    return dict(
        source=str(task.source.resolve()),
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        profile=profile(task, options),
        engine=1,
    )


def video_config(options: Options) -> video.Settings:
    return video.Settings(
        codec=options.codec,
        control=options.rate_mode,
        quality=options.video_quality,
        bitrate=options.bitrate,
        maxrate=options.maxrate,
        fps=options.fps,
    )


def probe_tracks(path: Path) -> list:
    process = subprocess.run(
        [
            video.binary_path("ffprobe"),
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,channels:stream_tags=language",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=45,
        creationflags=video.CREATE_NO_WINDOW,
    )
    if process.returncode:
        raise RuntimeError("无法读取媒体轨道")
    return json.loads(process.stdout).get("streams", [])


def validate_video(path: Path, info: dict, cfg, source_tracks: list):
    good, reason = video.output_check(path, info, cfg)
    if not good:
        raise RuntimeError(reason)
    tracks = probe_tracks(path)
    audio_in = [s for s in source_tracks if s.get("codec_type") == "audio"]
    audio_out = [s for s in tracks if s.get("codec_type") == "audio"]
    if len(audio_in) != len(audio_out):
        raise RuntimeError("音轨数量不符，未保存输出")


def encode_video(
    task: Task, temp: Path, output: Path, options: Options, cancel: Cancellation, emit: Event
):
    info = video.probe(task.source)
    if not info:
        raise RuntimeError("无法读取源视频")
    tracks = probe_tracks(task.source)
    if (
        any(t.get("codec_type") in ("subtitle", "attachment", "data") for t in tracks)
        or sum(t.get("codec_type") == "video" for t in tracks) > 1
    ):
        emit(
            "log",
            {
                "message": f"{task.relative}：仅保留首个视频轨及所有音轨，字幕、附加视频及数据轨不转存；原文件保留。"
            },
        )
    cfg = video_config(options)
    args = video.ffmpeg_args(task.source, temp, cfg, info)
    if options.container == "webm":
        offset = args.index("-c:a")
        args[offset:] = ["-c:a", "libopus", "-b:a", "128k", "-f", "webm", str(temp)]
    seconds = video.video_duration(info)
    diagnostic = []
    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=video.CREATE_NO_WINDOW,
    )
    cancel.attach(process)
    try:
        for line in process.stdout:
            if cancel.event.is_set():
                break
            line = line.strip()
            if line.startswith("out_time_us=") and seconds:
                try:
                    emit(
                        "fraction",
                        {"fraction": min(0.98, max(0, int(line.split("=")[1]) / 1e6 / seconds))},
                    )
                except ValueError:
                    pass
            elif line and "=" not in line:
                diagnostic.append(line)
                diagnostic = diagnostic[-12:]
        try:
            code = process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            code = process.wait()
        if cancel.event.is_set():
            raise InterruptedError("任务已停止")
        if code:
            raise RuntimeError("FFmpeg 编码失败：" + " | ".join(diagnostic[-4:]))
        emit("stage", {"status": "校验中"})
        validate_video(temp, info, cfg, tracks)
        transfer = info["streams"][0].get("color_transfer")
        if transfer in ("arib-std-b67", "smpte2084"):
            emit(
                "log",
                {"message": f"{task.relative}：已检查 HDR 标签和位深；动态元数据不在校验范围内。"},
            )
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        if process.stdout:
            process.stdout.close()
        cancel.attach(None)


def cached_output(target, task, before, options, history, output):
    old = history.get(target, output / ".compressor")
    stat = target.stat() if target.is_file() else None
    if not (
        stat
        and old.get("source") == before
        and old.get("output_size") == stat.st_size
        and old.get("output_mtime_ns") == stat.st_mtime_ns
    ):
        return False
    try:
        if task.kind == "image":
            with Image.open(task.source) as raw:
                expected = images.display_size(raw)
            return images.check_existing(target, task.source, expected, options.image_format)
        validate_video(
            target, video.probe(task.source), video_config(options), probe_tracks(task.source)
        )
        return True
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired):
        return False


def select_target(task, output, options, history, before):
    base = destination(task, output, options)
    target = base
    number = 1
    while target.exists():
        if cached_output(target, task, before, options, history, output):
            return target, True
        if options.conflict != "number":
            break
        target = base.with_name(f"{base.stem} ({number}){base.suffix}")
        number += 1
    return target, False


def commit_output(temporary, target, conflict):
    if conflict == "replace":
        os.replace(temporary, target)
        return target, True
    base = target
    number = 1
    while True:
        try:
            descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if conflict == "skip":
                return target, False
            target = base.with_name(f"{base.stem} ({number}){base.suffix}")
            number += 1
            continue
        os.close(descriptor)
        try:
            os.replace(temporary, target)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        return target, True


def run(tasks: list[Task], output: Path, options: Options, cancel: Cancellation, emit: Event):
    counts = {"success": 0, "skip": 0, "larger": 0, "error": 0, "cancel": 0}
    saved = 0
    started = time.monotonic()
    history = None
    try:
        options.validate()
        output.mkdir(parents=True, exist_ok=True)
        history = History(lambda message: emit("log", {"message": message}))
        for index, task in enumerate(tasks):
            if cancel.event.is_set():
                break
            target = destination(task, output, options)
            temp = target.with_name(
                f".{target.stem}.{uuid.uuid4().hex[:12]}.partial{target.suffix}"
            )
            size_after = 0
            status = "error"
            reason = ""
            reason_code = "conversion_failed"
            conversion_note = ""
            emit("current", {"index": index, "name": task.relative.as_posix()})
            try:
                before = fingerprint(task, options)
                target, cached = select_target(task, output, options, history, before)
                if cached:
                    reason_code = "cached"
                    status, reason, size_after = (
                        "skip",
                        "来源、参数及已有输出检查通过",
                        target.stat().st_size,
                    )
                    continue
                if options.conflict == "skip" and target.exists():
                    reason_code = "skip"
                    status, reason = "skip", "同名输出已存在，按设置跳过"
                    continue
                if target.resolve() == task.source.resolve():
                    raise ValueError("输出路径与原文件相同，未执行覆盖")
                temp = target.with_name(
                    f".{target.stem}.{uuid.uuid4().hex[:12]}.partial{target.suffix}"
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                emit("stage", {"status": "压缩中"})
                if task.kind == "image":
                    images.assert_encoder(options.image_format)
                    with Image.open(task.source) as raw:
                        if raw.mode.startswith("I") or raw.mode == "F":
                            emit(
                                "log",
                                {
                                    "message": f"{task.relative}：高位深输入将转换为 8-bit {options.image_format}；原始文件保留。"
                                },
                            )
                    opts = images.Options(
                        options.image_quality,
                        options.image_speed,
                        options.sampling,
                        options.keep_exif,
                        options.keep_icc,
                        False,
                        True,
                        primary_only=options.image_primary_only,
                        format=options.image_format,
                        png_colors=options.png_colors,
                    )
                    result = images.convert_one(
                        images.Task(task.source, temp, task.relative, task.size), opts
                    )
                    if result.status != "success":
                        raise ProcessingError(result.reason, result.code or "image_failed")
                    if result.discarded_frames:
                        conversion_note = result.reason
                else:
                    encode_video(task, temp, output, options, cancel, emit)
                if cancel.event.is_set():
                    raise InterruptedError("任务已停止")
                if fingerprint(task, options) != before:
                    raise RuntimeError("压缩期间源文件发生变化，未提交输出")
                size_after = temp.stat().st_size
                if options.skip_larger and size_after >= before["size"]:
                    reason_code = "larger"
                    status, reason = "larger", "输出未变小，未保存"
                else:
                    target, committed = commit_output(temp, target, options.conflict)
                    if not committed:
                        reason_code = "skip"
                        status, reason = "skip", "同名输出已存在，按设置跳过"
                        continue
                    result_stat = target.stat()
                    history.put(
                        target,
                        dict(
                            source=before,
                            output_size=result_stat.st_size,
                            output_mtime_ns=result_stat.st_mtime_ns,
                        ),
                    )
                    status, reason = "success", conversion_note or "压缩与校验完成"
                    reason_code = "primary_only" if conversion_note else "success"
                    saved += max(0, before["size"] - size_after)
            except InterruptedError as exc:
                status, reason = "cancel", str(exc)
                reason_code = "cancel"
            except Exception as exc:
                reason = str(exc)
                reason_code = getattr(exc, "code", "conversion_failed")
            finally:
                try:
                    temp.unlink(missing_ok=True)
                except OSError:
                    pass
                counts[status] += 1
                emit(
                    "result",
                    dict(
                        index=index,
                        status=status,
                        reason=reason,
                        code=reason_code,
                        size=size_after,
                        output=str(target),
                        saved=saved,
                        counts=counts.copy(),
                    ),
                )
        emit(
            "finished",
            dict(
                counts=counts,
                saved=saved,
                cancelled=cancel.event.is_set(),
                elapsed=time.monotonic() - started,
            ),
        )
    except Exception as exc:
        emit("fatal", {"message": str(exc)})
    finally:
        if history:
            history.close()


def capabilities() -> dict:
    from PIL import features

    result = {"avif": bool(features.check("avif")), "video": False, "encoders": [], "message": ""}
    try:
        probe = subprocess.run(
            [video.binary_path("ffmpeg"), "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=video.CREATE_NO_WINDOW,
            timeout=15,
        )
        video.binary_path("ffprobe")
        result["video"] = probe.returncode == 0
        result["encoders"] = [
            name for name in (*video.ENCODERS.values(), "libopus", "aac") if name in probe.stdout
        ]
    except Exception as exc:
        result["message"] = str(exc)
    return result
