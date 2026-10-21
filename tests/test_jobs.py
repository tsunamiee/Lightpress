import ctypes
import hashlib
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image, ImageCms

from compressor import core, jobs, storage
from compressor.formats import FORMATS
from compressor.strings import ZH, EN


class JobTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lightpress-")
        self.root = Path(self.temporary.name)
        self.source = self.root / "素材"
        self.source.mkdir()
        self.output = self.root / "output"
        patcher = patch("compressor.storage.application_dir", return_value=self.root / "app")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.temporary.cleanup)

    def image(self, name="照片.png", mode="RGBA"):
        path = self.source / name
        exif = Image.Exif()
        exif[306] = "2026:10:18 12:00:00"
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        image = Image.new(mode, (128, 96), (50, 100, 180, 90) if mode == "RGBA" else (50, 100, 180))
        image.save(path, exif=exif, icc_profile=profile)
        return path

    def encode(self, paths, format="jpeg", level=3, settings=None, output=None):
        events = []
        jobs.run(
            [str(path) for path in paths],
            output or self.output,
            format,
            level,
            settings or {},
            core.Cancellation(),
            lambda kind, value: events.append((kind, value)),
        )
        self.assertFalse([v for k, v in events if k == "fatal"], events)
        return [v for k, v in events if k == "result"], events

    def video(self, path=None):
        path = path or self.source / "视频.mp4"
        subprocess.run(
            [
                core.video.binary_path("ffmpeg"),
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=160x120:rate=12",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440",
                "-t",
                "0.6",
                "-c:v",
                "mpeg4",
                "-c:a",
                "aac",
                "-y",
                str(path),
            ],
            check=True,
            capture_output=True,
            creationflags=core.video.CREATE_NO_WINDOW,
        )
        return path

    def test_all_image_formats_quality_levels_metadata_alpha_and_originals(self):
        source = self.image()
        original = hashlib.sha256(source.read_bytes()).hexdigest()
        for format in FORMATS[:4]:
            for level in range(5):
                with self.subTest(format=format.key, level=level):
                    results, _ = self.encode(
                        [source], format.key, level, output=self.output / format.key / str(level)
                    )
                    self.assertEqual(results[0]["status"], "success", results)
                    with Image.open(results[0]["output"]) as image:
                        image.load()
                        self.assertEqual(image.format, format.name.upper())
                        self.assertEqual(image.size, (128, 96))
                        self.assertEqual(image.getexif()[306], "2026:10:18 12:00:00")
                        self.assertTrue(image.info.get("icc_profile"))
                        if format.key == "jpeg":
                            self.assertEqual(image.mode, "RGB")
                            self.assertGreater(image.getpixel((0, 0))[0], 160)
                        else:
                            self.assertLess(image.convert("RGBA").getpixel((0, 0))[3], 140)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original)

    def test_metadata_can_be_removed_for_every_image_format(self):
        source = self.image()
        for format in FORMATS[:4]:
            with self.subTest(format=format.key):
                results, _ = self.encode(
                    [source],
                    format.key,
                    settings={"keep_exif": False, "keep_icc": False},
                    output=self.output / format.key,
                )
                self.assertEqual(results[0]["status"], "success")
                with Image.open(results[0]["output"]) as image:
                    image.load()
                    self.assertFalse(image.getexif())
                    self.assertFalse(image.info.get("icc_profile"))

    def test_png_highest_preserves_pixels_and_avif_can_be_read(self):
        source = self.image()
        results, _ = self.encode([source], "png", 4)
        with Image.open(source) as original, Image.open(results[0]["output"]) as result:
            self.assertEqual(original.tobytes(), result.tobytes())
        results, _ = self.encode([source], "avif")
        results, _ = self.encode(
            [Path(results[0]["output"])], "jpeg", output=self.output / "roundtrip"
        )
        self.assertEqual(results[0]["status"], "success")

    def test_collision_policies_resume_and_no_overwrite(self):
        source = self.image("照片.jpg", "RGB")
        first, _ = self.encode([source])
        target = Path(first[0]["output"])
        unchanged = target.read_bytes()
        repeated, _ = self.encode([source])
        self.assertEqual(repeated[0]["status"], "skip")
        changed, _ = self.encode([source], level=1)
        self.assertEqual(changed[0]["status"], "success")
        self.assertNotEqual(changed[0]["output"], str(target))
        self.assertEqual(target.read_bytes(), unchanged)
        skipped, _ = self.encode([source], level=2, settings={"conflict": "skip"})
        self.assertEqual(skipped[0]["status"], "skip")
        same_folder, _ = self.encode([source], output=self.source)
        self.assertNotEqual(Path(same_folder[0]["output"]), source)
        self.assertTrue(source.is_file())

    def test_folder_recursive_filters_and_format_filter(self):
        self.image("保留.png")
        self.image("排除.png")
        child = self.source / "child"
        child.mkdir()
        Image.new("RGB", (32, 32)).save(child / "深层.jpg")
        (self.source / "视频.mov").write_bytes(b"video placeholder")
        tasks, ignored = jobs.collect([self.source], self.output, "jpeg", {}, core.Cancellation())
        self.assertEqual(len(tasks), 2)
        self.assertEqual(ignored, 1)
        tasks, _ = jobs.collect(
            [self.source],
            self.output,
            "jpeg",
            {"recursive": True, "include": "*.jpg;*.png", "exclude": "排除"},
            core.Cancellation(),
        )
        self.assertEqual(len(tasks), 2)
        with self.assertRaises(jobs.JobError):
            jobs.collect([self.source], self.source, "jpeg", {}, core.Cancellation())

    def test_h264_h265_mutual_reencoding_and_av1_webm(self):
        source = self.video()
        original = source.read_bytes()
        for format, expected in (
            ("h264", "h264"),
            ("h265", "hevc"),
            ("h264", "h264"),
            ("av1", "av1"),
            ("av1_webm", "av1"),
        ):
            results, _ = self.encode(
                [source], format, output=self.output / (format + str(len(source.name)))
            )
            self.assertEqual(results[0]["status"], "success", results)
            source = Path(results[0]["output"])
            self.assertEqual(core.video.probe(source)["streams"][0]["codec_name"], expected)
            self.assertEqual(
                sum(track["codec_type"] == "audio" for track in core.probe_tracks(source)), 1
            )
            subprocess.run(
                [
                    core.video.binary_path("ffmpeg"),
                    "-v",
                    "error",
                    "-i",
                    str(source),
                    "-f",
                    "null",
                    "-",
                ],
                check=True,
                capture_output=True,
                creationflags=core.video.CREATE_NO_WINDOW,
            )
        self.assertEqual((self.source / "视频.mp4").read_bytes(), original)

    def test_auto_mixed_queue_continues_after_bad_input(self):
        self.image()
        self.video()
        (self.source / "损坏.jpg").write_bytes(b"invalid image")
        results, events = self.encode([self.source], "auto")
        self.assertEqual(
            sorted(item["status"] for item in results), ["error", "success", "success"]
        )
        self.assertEqual([v for k, v in events if k == "finished"][0]["counts"]["error"], 1)
        self.assertFalse(list(self.output.glob("*.partial*")))

    def test_portable_settings_and_atomic_replacement(self):
        storage.save_settings({"compact": {"language": "en"}, "theme": "dark"})
        storage.save_settings({"quality": 4})
        self.assertEqual(storage.read_settings()["compact"]["language"], "en")
        self.assertEqual(storage.settings_path(), self.root / "app" / "data" / "settings.json")
        self.assertFalse(list(storage.data_dir().glob("*.tmp")))
        storage.settings_path().write_text("broken", encoding="utf-8")
        self.assertEqual(storage.read_settings(), {})

    def test_windows_language_mapping(self):
        language = SimpleNamespace(restype=None)
        for identifier, expected in (
            (0x0804, "zh_CN"),
            (0x0404, "zh_CN"),
            (0x0C04, "zh_CN"),
            (0x0409, "en"),
            (0x0411, "en"),
            (0x0407, "en"),
        ):

            class Function:
                restype = None

                def __call__(self):
                    return identifier

            language = Function()
            with (
                patch.object(storage.sys, "platform", "win32"),
                patch.object(
                    ctypes,
                    "windll",
                    SimpleNamespace(kernel32=SimpleNamespace(GetUserDefaultUILanguage=language)),
                    create=True,
                ),
            ):
                self.assertEqual(storage.system_language(), expected)
        self.assertEqual(set(ZH), set(EN))


if __name__ == "__main__":
    unittest.main()
