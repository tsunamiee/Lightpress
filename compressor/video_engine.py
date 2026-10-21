"""FFmpeg command construction and output checks."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

EXTS = {".mp4", ".mov", ".mkv", ".m4v", ".avi", ".webm", ".mts", ".ts"}
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
ENCODERS = {
    "av1_cpu": "libsvtav1",
    "av1_gpu": "av1_nvenc",
    "h264_cpu": "libx264",
    "h264_gpu": "h264_nvenc",
    "h265_cpu": "libx265",
    "h265_gpu": "hevc_nvenc",
}


@dataclass(frozen=True)
class Settings:
    codec: str
    control: str
    quality: int
    bitrate: int
    maxrate: int
    fps: str


def probe(path: Path) -> dict | None:
    cmd = [
        binary_path("ffprobe"),
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,width,height,avg_frame_rate,color_primaries,color_transfer,color_space,pix_fmt,duration:"
        "stream_side_data=rotation:stream_tags=rotate:format=duration",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
        timeout=45,
    )
    if result.returncode:
        return None
    try:
        data = json.loads(result.stdout)
        return data if data.get("streams") else None
    except (ValueError, TypeError):
        return None


def duration(info: dict | None) -> float:
    try:
        return float(info["format"]["duration"])
    except (ValueError, TypeError, KeyError):
        return 0.0


def video_duration(info: dict | None) -> float:
    """Prefer video duration over container duration, which may include audio padding."""
    if not info:
        return 0.0
    try:
        value = float(info["streams"][0].get("duration", 0))
        if value > 0:
            return value
    except (ValueError, TypeError, KeyError, IndexError):
        pass
    return duration(info)


def display_size(stream: dict) -> tuple[int, int, float]:
    """Return dimensions after applying the display rotation."""
    width, height = int(stream["width"]), int(stream["height"])
    rotation = 0.0
    for side_data in stream.get("side_data_list", []):
        if "rotation" in side_data:
            try:
                rotation = float(side_data["rotation"])
                break
            except (TypeError, ValueError):
                pass
    else:
        try:
            rotation = float(stream.get("tags", {}).get("rotate", 0))
        except (TypeError, ValueError):
            rotation = 0.0
    normalized = rotation % 360
    if min(abs(normalized - 90), abs(normalized - 270)) < 1.0:
        return height, width, rotation
    return width, height, rotation


def output_check(output: Path, src_info: dict | None, cfg: Settings) -> tuple[bool, str]:
    """Validate the first video stream against the source and encoding settings."""
    if not output.is_file():
        return False, f"文件不存在：{output}"
    if output.stat().st_size < 64:
        return False, f"文件过小（{output.stat().st_size} 字节）"
    out_info = probe(output)
    if not out_info:
        return False, "ffprobe 无法读取输出视频的媒体信息（可能不完整或损坏）"
    stream = out_info["streams"][0]
    expected_codec = {"h264": "h264", "h265": "hevc", "av1": "av1"}[cfg.codec.split("_")[0]]
    actual_codec = stream.get("codec_name", "未知")
    if actual_codec != expected_codec:
        return False, f"编码格式不符：预期 {expected_codec}，实际 {actual_codec}"
    if src_info:
        src_stream = src_info["streams"][0]
        # FFmpeg may bake a display matrix into the output pixels.
        src_display_w, src_display_h, src_rot = display_size(src_stream)
        out_display_w, out_display_h, out_rot = display_size(stream)
        if (src_display_w, src_display_h) != (out_display_w, out_display_h):
            return False, (
                f'显示尺寸不符：原片编码 {src_stream.get("width")}×{src_stream.get("height")}'
                f"、旋转 {src_rot:g}°、显示 {src_display_w}×{src_display_h}；"
                f'输出编码 {stream.get("width")}×{stream.get("height")}'
                f"、旋转 {out_rot:g}°、显示 {out_display_w}×{out_display_h}"
            )
        t_src, t_out = video_duration(src_info), video_duration(out_info)
        threshold = max(1.5, t_src * 0.03)
        if t_src > 0 and (t_out <= 0 or abs(t_out - t_src) > threshold):
            fmt_src, fmt_out = duration(src_info), duration(out_info)
            return False, (
                f"时长不符：源视频轨 {t_src:.3f}s、输出视频轨 {t_out:.3f}s，"
                f"允许差值 {threshold:.3f}s；源容器 {fmt_src:.3f}s、输出容器 {fmt_out:.3f}s。"
                "手机可变帧率或原片时间戳可能导致此问题"
            )
        transfer = src_stream.get("color_transfer")
        if transfer in ("arib-std-b67", "smpte2084"):
            actual_transfer = stream.get("color_transfer", "未标记")
            if actual_transfer != transfer:
                return False, f"HDR 转移函数不符：源片 {transfer}，输出 {actual_transfer}"
            pix_fmt = stream.get("pix_fmt", "")
            if not ("10" in pix_fmt or pix_fmt == "p010le"):
                return False, f'HDR 像素位深不符：预期 10-bit，实际 pix_fmt={pix_fmt or "未知"}'
    if cfg.fps != "原始帧率":
        actual_str = stream.get("avg_frame_rate", "")
        try:
            num, den = actual_str.split("/")
            actual_fps = float(num) / float(den)
            n, d = (cfg.fps.split("/") + ["1"])[:2]
            expected_fps = float(n) / float(d)
            if abs(actual_fps - expected_fps) > 0.15:
                return False, (
                    f"帧率不符：设定 {cfg.fps}（{expected_fps:.4f}fps），"
                    f"输出 avg_frame_rate={actual_str}（{actual_fps:.4f}fps）"
                )
        except (ValueError, ZeroDivisionError, TypeError) as e:
            return False, f"无法解析帧率：输出 avg_frame_rate={actual_str!r}；{e}"
    return True, "校验通过"


def ffmpeg_args(src: Path, output: Path, cfg: Settings, info: dict) -> list[str]:
    v = info["streams"][0]
    args = [
        binary_path("ffmpeg"),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-loglevel",
        "error",
        "-progress",
        "pipe:1",
        "-stats_period",
        "0.6",
        "-i",
        str(src),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-map_metadata",
        "0",
    ]
    if cfg.fps != "原始帧率":
        args += ["-vf", f"fps={cfg.fps}"]
    hdr = v.get("color_transfer") in ("arib-std-b67", "smpte2084")
    if cfg.codec == "h264_cpu":
        args += [
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-threads",
            "4",
            "-pix_fmt",
            "yuv420p10le" if hdr else "yuv420p",
        ]
    elif cfg.codec == "h265_cpu":
        args += [
            "-c:v",
            "libx265",
            "-preset",
            "medium",
            "-x265-params",
            "pools=4:frame-threads=2:log-level=error",
            "-pix_fmt",
            "yuv420p10le",
            "-tag:v",
            "hvc1",
        ]
    elif cfg.codec == "h264_gpu":
        if hdr:
            raise ValueError(
                "NVIDIA H.264 模式不能保留此 HDR 输入的 10-bit 位深，请选择 CPU 或 H.265。"
            )
        args += ["-c:v", "h264_nvenc", "-preset", "p5", "-pix_fmt", "yuv420p"]
    elif cfg.codec == "av1_gpu":
        args += ["-c:v", "av1_nvenc", "-preset", "p5", "-pix_fmt", "p010le"]
    elif cfg.codec == "av1_cpu":
        args += [
            "-c:v",
            "libsvtav1",
            "-preset",
            "6",
            "-svtav1-params",
            "lp=4",
            "-pix_fmt",
            "yuv420p10le",
        ]
    elif cfg.codec == "h265_gpu":
        args += [
            "-c:v",
            "hevc_nvenc",
            "-preset",
            "p5",
            "-profile:v",
            "main10",
            "-pix_fmt",
            "p010le",
            "-tag:v",
            "hvc1",
        ]
    else:
        raise ValueError("不支持的视频编码器")
    if cfg.control == "bitrate":
        args += ["-b:v", f"{cfg.bitrate}M"]
        if cfg.codec.endswith("_gpu"):
            args += ["-rc", "vbr", "-maxrate", f"{cfg.maxrate}M", "-bufsize", f"{cfg.maxrate * 2}M"]
        else:
            args += ["-maxrate", f"{cfg.maxrate}M", "-bufsize", f"{cfg.maxrate * 2}M"]
    elif cfg.codec.endswith("_cpu"):
        args += ["-crf", str(cfg.quality)]
    else:
        args += ["-rc", "vbr", "-cq", str(cfg.quality), "-b:v", "0"]
    # Leave unspecified color tags unset.
    for key, flag in [
        ("color_primaries", "-color_primaries"),
        ("color_transfer", "-color_trc"),
        ("color_space", "-colorspace"),
    ]:
        val = v.get(key, "")
        if val and val not in ("unknown", "unspecified", "reserved"):
            args.extend([flag, val])
    args += ["-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-f", "mp4", str(output)]
    return args


def binary_path(name: str) -> str:
    if getattr(sys, "frozen", False):
        external = Path(sys.executable).parent / "bin" / (name + ".exe")
        if external.is_file():
            return str(external)
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    bundled = base / "bin" / (name + ".exe")
    if bundled.is_file():
        return str(bundled)
    located = shutil.which(name)
    if located:
        return located
    raise RuntimeError(f"未找到 {name}，请在应用目录的 bin 文件夹中放置 FFmpeg 工具。")
