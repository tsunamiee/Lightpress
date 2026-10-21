"""Image conversion, metadata handling and output validation."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, PngImagePlugin, features

SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".tif", ".tiff", ".bmp"}
OUTPUT_FORMATS = {"AVIF", "JPEG", "WEBP", "PNG"}
# HEIC decoding is registered by core when pillow-heif is installed.
OPTIONAL_SUFFIXES = {".heic", ".heif"}


@dataclass(frozen=True)
class Options:
    quality: int = 55
    speed: int = 6
    subsampling: str = "4:2:0"
    keep_exif: bool = True
    keep_icc: bool = True
    skip_larger: bool = True
    overwrite: bool = False
    primary_only: bool = False
    format: str = "AVIF"
    png_colors: int | None = None

    def validate(self) -> None:
        if not 0 <= self.quality <= 100:
            raise ValueError("质量需处于 0-100")
        if not 0 <= self.speed <= 10:
            raise ValueError("编码速度需处于 0-10")
        if self.subsampling not in ("4:2:0", "4:4:4"):
            raise ValueError("不支持的色度采样模式")
        if self.format not in OUTPUT_FORMATS:
            raise ValueError("不支持的图片输出格式")
        if self.png_colors is not None and not 2 <= self.png_colors <= 256:
            raise ValueError("PNG 调色板颜色数应为 2–256")


@dataclass(frozen=True)
class Task:
    source: Path
    destination: Path
    relative: Path
    source_bytes: int


@dataclass(frozen=True)
class Result:
    status: str  # success, skip, larger, error
    reason: str
    source_bytes: int
    output_bytes: int = 0
    discarded_frames: int = 0
    code: str = ""


def assert_encoder(format="AVIF") -> None:
    feature = {"AVIF": "avif", "JPEG": "jpg", "WEBP": "webp", "PNG": "zlib"}[format]
    if not features.check(feature):
        raise RuntimeError(f"当前 Pillow 不支持 {format} 编码，请重新安装项目依赖。")
    if format == "AVIF" and ".avif" not in Image.registered_extensions():
        raise RuntimeError("当前 Pillow 不支持 AVIF，请重新安装项目依赖。")


def display_size(image: Image.Image) -> tuple[int, int]:
    rotation = image.getexif().get(274, 1)
    return (image.height, image.width) if rotation in (5, 6, 7, 8) else image.size


def check_existing(
    output: Path,
    input_path: Path,
    expected_size: tuple[int, int] | None = None,
    format="AVIF",
) -> bool:
    try:
        if not output.is_file() or output.stat().st_size < 64:
            return False
        if output.stat().st_mtime_ns < input_path.stat().st_mtime_ns:
            return False
        with Image.open(output) as im:
            if im.format != format or (expected_size is not None and im.size != expected_size):
                return False
            im.load()
        return True
    except (OSError, ValueError, SyntaxError):
        return False


def _convert_pixels(img: Image.Image, save_opts: dict) -> Image.Image:
    # Convert CMYK pixels before attaching an RGB profile.
    if img.mode == "CMYK":
        profile = img.info.get("icc_profile")
        if profile:
            from io import BytesIO
            from PIL import ImageCms

            dest = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
            img = ImageCms.profileToProfile(img, BytesIO(profile), dest, outputMode="RGB")
            if "icc_profile" in save_opts:
                save_opts["icc_profile"] = dest.tobytes()
        else:
            img = img.convert("RGB")
            # The source profile cannot describe the converted RGB pixels.
            save_opts.pop("icc_profile", None)
    if img.mode not in ("RGB", "RGBA", "L", "LA"):
        has_transparency = "A" in img.getbands() or "transparency" in img.info
        img = img.convert("RGBA" if has_transparency else "RGB")
    return img


def convert_one(task: Task, options: Options) -> Result:
    options.validate()
    tmp = task.destination.with_name(
        f".{task.destination.stem}.{uuid.uuid4().hex[:12]}.partial{task.destination.suffix}"
    )
    task.destination.parent.mkdir(parents=True, exist_ok=True)
    size = task.source.stat().st_size
    try:
        with Image.open(task.source) as raw:
            frames = getattr(raw, "n_frames", 1)
            multi_jpeg = raw.format in ("MPO", "JPEG") and frames > 1
            if frames > 1:
                if not multi_jpeg or not options.primary_only:
                    reason = (
                        f"JPG 内部包含 {frames} 幅图像（{raw.format}）。如只需静态照片，可勾选“多图 JPG 仅保留主图”。"
                        if multi_jpeg
                        else f"不支持多帧/多页图像（{raw.format}，{frames} 帧），已跳过"
                    )
                    return Result(
                        "error", reason, size, code="multi_jpeg" if multi_jpeg else "multiframe"
                    )
                raw.seek(0)
            expected = display_size(raw)
            if not options.overwrite and check_existing(
                task.destination, task.source, expected, options.format
            ):
                return Result(
                    "skip",
                    "已有可读取的对应 AVIF 文件，已跳过",
                    size,
                    task.destination.stat().st_size,
                )
            # Bake orientation into pixels before removing the EXIF rotation.
            img = ImageOps.exif_transpose(raw)
            img.load()
            opts: dict = dict(
                format=options.format,
                icc_profile=b"" if not options.keep_icc else img.info.get("icc_profile", b""),
                exif=b"",
            )
            if options.keep_icc and img.info.get("icc_profile"):
                opts["icc_profile"] = img.info["icc_profile"]
            if options.keep_exif:
                exif = img.getexif()
                if exif and len(exif):
                    opts["exif"] = exif.tobytes()
                # Multi-picture XMP can reference auxiliary images that are not exported.
                if not multi_jpeg and img.info.get("xmp"):
                    opts["xmp"] = img.info["xmp"]
            img = _convert_pixels(img, opts)
            if options.format == "AVIF":
                opts.update(
                    quality=options.quality,
                    speed=options.speed,
                    subsampling=options.subsampling,
                    max_threads=8,
                )
            elif options.format == "JPEG":
                if "A" in img.getbands():
                    rgba = img.convert("RGBA")
                    background = Image.new("RGB", img.size, "white")
                    background.paste(rgba, mask=rgba.getchannel("A"))
                    img.close()
                    img = background
                opts.update(
                    quality=options.quality,
                    optimize=True,
                    progressive=True,
                    subsampling=0 if options.subsampling == "4:4:4" else 2,
                )
            elif options.format == "WEBP":
                opts.update(quality=options.quality, method=6)
            elif options.format == "PNG":
                if options.png_colors:
                    quantized = img.convert("RGBA").quantize(
                        colors=options.png_colors, method=Image.Quantize.FASTOCTREE
                    )
                    img.close()
                    img = quantized
                opts.update(compress_level=9)
                if opts.get("xmp"):
                    pnginfo = PngImagePlugin.PngInfo()
                    pnginfo.add_itxt(
                        "XML:com.adobe.xmp", opts.pop("xmp").decode("utf-8", errors="replace")
                    )
                    opts["pnginfo"] = pnginfo
            try:
                img.save(tmp, **opts)
            finally:
                img.close()

        with Image.open(tmp) as result_img:
            if result_img.format != options.format:
                raise ValueError(f"输出格式不是 {options.format}")
            result_img.load()
            if result_img.size != expected:
                raise ValueError(f"分辨率不符：期望 {expected}，输出 {result_img.size}")
            if (
                options.keep_icc
                and opts.get("icc_profile")
                and not result_img.info.get("icc_profile")
            ):
                raise ValueError("输出文件丢失 ICC 色彩配置；已阻止保存")
        new_size = tmp.stat().st_size
        if options.skip_larger and new_size >= size:
            return Result(
                "larger",
                f"压缩后未变小（{size/1024:.1f} → {new_size/1024:.1f} KiB），未保留",
                size,
                new_size,
            )
        os.replace(tmp, task.destination)
        discarded = frames - 1 if multi_jpeg else 0
        reason = "已转换 JPG 主图；未保留附加图及其 HDR/深度等信息" if discarded else "转换成功"
        return Result("success", reason, size, new_size, discarded_frames=discarded)
    except Exception as exc:
        return Result("error", f"{type(exc).__name__}: {exc}", size, code="image_failed")
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
