"""Prepare file selections for the shared compression engine."""

import os
from pathlib import Path

from . import core
from .formats import get_format


class JobError(ValueError):
    def __init__(self, code, detail=""):
        self.code = code
        super().__init__(detail or code)


def encoding_options(format_key, quality, settings):
    if not isinstance(quality, int) or not 0 <= quality <= 4:
        raise JobError("invalid_quality")
    format = get_format(format_key)
    image_format = get_format("avif") if format.kind in ("all", "videos") else format
    video_format = get_format("h264") if format.kind in ("all", "images") else format
    codec = video_format.key.split("_")[0] + (
        "_gpu" if settings.get("encoder") == "nvidia" else "_cpu"
    )
    options = core.Options(
        image_format=image_format.name.upper(),
        image_quality=image_format.levels[quality] if image_format.parameter == "quality" else 80,
        png_colors=image_format.levels[quality] if image_format.key == "png" else None,
        sampling="4:4:4" if quality == 4 else "4:2:0",
        keep_exif=settings.get("keep_exif", True),
        keep_icc=settings.get("keep_icc", True),
        image_primary_only=settings.get("primary_only", False),
        skip_larger=settings.get("skip_larger", False),
        codec=codec,
        video_quality=video_format.levels[quality],
        container="webm" if video_format.key == "av1_webm" else "mp4",
        fps=settings.get("fps", "原始帧率"),
        naming="simple",
        conflict=settings.get("conflict", "number"),
    )
    options.validate()
    return options


def collect(paths, output, format_key, settings, cancel):
    if not paths:
        raise JobError("missing_source")
    output = Path(output).expanduser().resolve()
    if output.exists() and not output.is_dir():
        raise JobError("invalid_output")
    format = get_format(format_key)
    kind = {"images": "image", "videos": "video", "all": "all"}[format.kind]
    include, exclude = settings.get("include", "*"), settings.get("exclude", "")
    core.patterns(include)
    core.patterns(exclude)
    tasks, ignored, seen = [], 0, set()
    for value in paths:
        if cancel.event.is_set():
            break
        path = Path(value).expanduser().resolve()
        if not path.exists():
            raise JobError("invalid_source", str(path))
        if path.is_dir():
            if path == output or output in path.parents:
                raise JobError("output_inside_source_error")
            candidates = core.scan(
                path, output, include, exclude, settings.get("recursive", False), cancel=cancel
            )
        else:
            relative = Path(path.name)
            suffix = path.suffix.lower()
            media_kind = (
                "image"
                if suffix in core.IMAGE_EXTS
                else "video" if suffix in core.VIDEO_EXTS else None
            )
            if not media_kind:
                ignored += 1
                continue
            if (
                core.patterns(include) and not core.matches(relative, core.patterns(include))
            ) or core.matches(relative, core.patterns(exclude)):
                continue
            candidates = [core.Task(path, relative, media_kind, path.stat().st_size)]
        for task in candidates:
            key = os.path.normcase(str(task.source.resolve()))
            if key in seen:
                continue
            seen.add(key)
            if kind != "all" and task.kind != kind:
                ignored += 1
            else:
                tasks.append(task)
    return tasks, ignored


def run(paths, output, format_key, quality, settings, cancel, emit):
    try:
        options = encoding_options(format_key, quality, settings)
        tasks, ignored = collect(paths, output, format_key, settings, cancel)
        emit("prepared", {"tasks": tasks, "ignored": ignored})
        if cancel.event.is_set():
            emit("finished", {"counts": {}, "cancelled": True, "saved": 0, "elapsed": 0})
            return
        if not tasks:
            raise JobError("no_matching_files")
        if any(task.kind == "video" for task in tasks):
            capabilities = core.capabilities()
            encoder = core.video.ENCODERS[options.codec]
            if not capabilities["video"] or encoder not in capabilities["encoders"]:
                raise JobError("encoder_unavailable", encoder)
        core.run(tasks, Path(output).expanduser().resolve(), options, cancel, emit)
    except Exception as error:
        emit("fatal", {"code": getattr(error, "code", "job_failed"), "message": str(error)})
