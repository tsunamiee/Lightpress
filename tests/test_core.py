import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from compressor import core


class CompressorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="compressor-test-")
        self.root = Path(self.temp.name)
        self.source = self.root / "中文素材"
        self.source.mkdir()
        self.output = self.source / "压缩输出"
        self.cache_file = self.root / "appdata" / "history.sqlite3"
        history_patch = patch("compressor.history.history_path", return_value=self.cache_file)
        self.history_path = history_patch.start()
        self.addCleanup(history_patch.stop)

    def tearDown(self):
        self.temp.cleanup()

    def image(self, name="照片.png", mode="RGB"):
        path = self.source / name
        Image.new(mode, (128, 96), (40, 80, 140, 90) if mode == "RGBA" else (40, 80, 140)).save(
            path
        )
        return path

    def run_queue(self, tasks, options=None, cancel=None):
        events = []
        core.run(
            tasks,
            self.output,
            options or core.Options(skip_larger=False),
            cancel or core.Cancellation(),
            lambda k, v: events.append((k, v)),
        )
        fatal = [data for kind, data in events if kind == "fatal"]
        self.assertFalse(fatal, fatal)
        return [v for k, v in events if k == "result"], events

    def test_scan_excludes_outputs_and_unifies_filters(self):
        self.image("旅行.png")
        self.image("其他.png")
        self.output.mkdir()
        Image.new("RGB", (10, 10)).save(self.output / "旅行.png")
        self.assertEqual(
            [t.relative.name for t in core.scan(self.source, self.output, "旅行")], ["旅行.png"]
        )
        self.assertEqual(len(core.scan(self.source, self.output, "*.png", "其他")), 1)
        self.assertEqual(len(core.scan(self.source, self.output, "re:^旅行")), 1)
        with self.assertRaises(Exception):
            core.patterns("re:[")

    def test_path_and_parameter_validation(self):
        with self.assertRaises(ValueError):
            core.validate_paths(str(self.source), str(self.source))
        with self.assertRaises(ValueError):
            core.validate_paths(str(self.source), str(self.root))
        for fps in ("0", "1/0", "abc", "300"):
            with self.assertRaises(ValueError):
                core.Options(fps=fps).validate()
        with self.assertRaises(ValueError):
            core.Options(codec="h265_gpu", container="webm").validate()
        core.Options(fps="60000/1001").validate()

    def test_image_conversion_alpha_and_original_unchanged(self):
        path = self.image(mode="RGBA")
        before = hashlib.sha256(path.read_bytes()).digest()
        tasks = core.scan(self.source, self.output)
        results, _ = self.run_queue(tasks)
        self.assertEqual(results[0]["status"], "success", results)
        with Image.open(results[0]["output"]) as output:
            output.load()
            self.assertEqual(output.size, (128, 96))
            self.assertIn("A", output.getbands())
        self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), before)
        self.assertFalse(list(self.output.rglob("*.partial*")))

    def test_orientation_is_normalized(self):
        path = self.source / "旋转.jpg"
        image = Image.new("RGB", (120, 80), "red")
        exif = image.getexif()
        exif[274] = 6
        image.save(path, exif=exif)
        results, _ = self.run_queue(core.scan(self.source, self.output))
        self.assertEqual(results[0]["status"], "success")
        with Image.open(results[0]["output"]) as out:
            self.assertEqual(out.size, (80, 120))
            self.assertNotIn(out.getexif().get(274), (6, 8))

    def test_resume_source_change_and_corrupt_output(self):
        path = self.image()
        tasks = core.scan(self.source, self.output)
        self.assertEqual(self.run_queue(tasks)[0][0]["status"], "success")
        self.assertEqual(self.run_queue(tasks)[0][0]["status"], "skip")
        Image.new("RGB", (128, 96), "red").save(path)
        self.assertEqual(self.run_queue(tasks)[0][0]["status"], "success")
        target = core.destination(tasks[0], self.output, core.Options(skip_larger=False))
        target.write_bytes(b"bad output")
        self.assertEqual(self.run_queue(tasks)[0][0]["status"], "success")

    def test_multiframe_is_rejected(self):
        path = self.source / "多页.tiff"
        one = Image.new("RGB", (50, 50), "red")
        one.save(path, save_all=True, append_images=[Image.new("RGB", (50, 50), "blue")])
        results, _ = self.run_queue(core.scan(self.source, self.output))
        self.assertEqual(results[0]["status"], "error")
        self.assertIn("多帧", results[0]["reason"])
        self.assertTrue(path.is_file())

    def test_records_are_outside_output(self):
        self.image()
        results, _ = self.run_queue(core.scan(self.source, self.output))
        self.assertEqual(results[0]["status"], "success")
        self.assertTrue(self.cache_file.is_file())
        self.assertEqual([p.suffix for p in self.output.iterdir()], [".avif"])

    def test_legacy_records_migrate_without_reencoding(self):
        self.image()
        tasks = core.scan(self.source, self.output)
        options = core.Options(skip_larger=False)
        self.run_queue(tasks, options)
        target = core.destination(tasks[0], self.output, options)
        stat = target.stat()
        old_dir = self.output / ".compressor"
        old_dir.mkdir()
        old_record = old_dir / (hashlib.sha256(str(target).encode()).hexdigest() + ".json")
        old_record.write_text(
            json.dumps(
                dict(
                    source=core.fingerprint(tasks[0], options),
                    output_size=stat.st_size,
                    output_mtime_ns=stat.st_mtime_ns,
                )
            ),
            encoding="utf-8",
        )
        migrated = self.root / "new-appdata" / "history.sqlite3"
        self.history_path.return_value = migrated
        results, _ = self.run_queue(tasks, options)
        self.assertEqual(results[0]["status"], "skip")
        self.assertEqual(target.stat().st_mtime_ns, stat.st_mtime_ns)
        self.assertTrue(migrated.is_file())
        self.assertFalse(old_dir.exists())

    def test_history_does_not_remove_unrelated_files(self):
        self.image()
        old_dir = self.output / ".compressor"
        old_dir.mkdir(parents=True)
        note = old_dir / "notes.txt"
        note.write_text("keep", encoding="utf-8")
        self.run_queue(core.scan(self.source, self.output))
        self.assertEqual(note.read_text(encoding="utf-8"), "keep")

    def test_cache_failure_does_not_fail_conversion(self):
        self.image()
        blocked = self.root / "not-a-directory"
        blocked.write_text("file", encoding="utf-8")
        self.history_path.return_value = blocked / "history.sqlite3"
        results, events = self.run_queue(core.scan(self.source, self.output))
        self.assertEqual(results[0]["status"], "success")
        self.assertTrue(
            any(kind == "log" and "处理记录" in data["message"] for kind, data in events)
        )
        self.assertFalse((self.output / ".compressor").exists())

    def test_mpo_requires_opt_in_and_keeps_only_primary(self):
        path = self.source / "multi.JPG"
        first = Image.new("RGB", (128, 96), "red")
        exif = first.getexif()
        exif[306] = "2026:10:18 10:00:00"
        first.save(
            path,
            format="MPO",
            save_all=True,
            append_images=[Image.new("RGB", (64, 48), "blue")],
            exif=exif,
            xmp=b"<metadata>auxiliary-image-reference</metadata>",
        )
        original = hashlib.sha256(path.read_bytes()).digest()
        tasks = core.scan(self.source, self.output)
        results, _ = self.run_queue(tasks)
        self.assertEqual(results[0]["status"], "error")
        self.assertIn("MPO", results[0]["reason"])
        options = core.Options(skip_larger=False, image_primary_only=True)
        results, _ = self.run_queue(tasks, options)
        self.assertEqual(results[0]["status"], "success", results)
        self.assertIn("未保留附加图", results[0]["reason"])
        with Image.open(results[0]["output"]) as output:
            self.assertEqual(output.size, (128, 96))
            self.assertNotIn("xmp", output.info)
            self.assertEqual(output.getexif().get(306), "2026:10:18 10:00:00")
            red, _, blue = output.convert("RGB").getpixel((64, 48))
            self.assertGreater(red, blue + 100)
        self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), original)
        self.assertEqual(self.run_queue(tasks, options)[0][0]["status"], "skip")

    def test_same_name_jpg_and_mov_do_not_make_jpg_multiframe(self):
        self.image("IMG_4862.JPG")
        self.make_video().rename(self.source / "IMG_4862.MOV")
        with Image.open(self.source / "IMG_4862.JPG") as image:
            self.assertEqual(getattr(image, "n_frames", 1), 1)
        results, _ = self.run_queue(core.scan(self.source, self.output))
        self.assertEqual([r["status"] for r in results], ["success", "success"], results)

    def test_larger_output_is_removed(self):
        Image.new("RGB", (1, 1), "white").save(self.source / "tiny.png")
        results, _ = self.run_queue(
            core.scan(self.source, self.output), core.Options(skip_larger=True, image_quality=100)
        )
        self.assertEqual(results[0]["status"], "larger")
        self.assertFalse(Path(results[0]["output"]).exists())
        self.assertEqual(results[0]["saved"], 0)

    def test_pre_cancelled_queue_keeps_originals(self):
        path = self.image()
        cancel = core.Cancellation()
        cancel.cancel()
        results, events = self.run_queue(core.scan(self.source, self.output), cancel=cancel)
        self.assertEqual(results, [])
        self.assertTrue(events[-1][1]["cancelled"])
        self.assertTrue(path.exists())

    def make_video(self):
        target = self.source / "测试视频.mp4"
        subprocess.run(
            [
                core.video.binary_path("ffmpeg"),
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=320x240:rate=12",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440",
                "-t",
                "1",
                "-c:v",
                "mpeg4",
                "-q:v",
                "2",
                "-c:a",
                "aac",
                "-y",
                str(target),
            ],
            check=True,
            capture_output=True,
            creationflags=core.video.CREATE_NO_WINDOW,
            timeout=30,
        )
        return target

    def test_mixed_queue_av1_mp4_audio_and_resume(self):
        self.image()
        original = self.make_video()
        checksum = hashlib.sha256(original.read_bytes()).digest()
        tasks = core.scan(self.source, self.output)
        results, _ = self.run_queue(tasks)
        self.assertEqual([r["status"] for r in results], ["success", "success"], results)
        video_result = next(r for r in results if r["output"].endswith(".mp4"))
        info = core.video.probe(Path(video_result["output"]))
        self.assertEqual(info["streams"][0]["codec_name"], "av1")
        self.assertEqual(info["streams"][0]["avg_frame_rate"], "12/1")
        self.assertEqual(
            len(
                [
                    t
                    for t in core.probe_tracks(Path(video_result["output"]))
                    if t["codec_type"] == "audio"
                ]
            ),
            1,
        )
        self.assertEqual([r["status"] for r in self.run_queue(tasks)[0]], ["skip", "skip"])
        self.assertEqual(hashlib.sha256(original.read_bytes()).digest(), checksum)

    def test_webm_av1_opus(self):
        self.make_video()
        options = core.Options(skip_larger=False, container="webm")
        result = self.run_queue(core.scan(self.source, self.output), options)[0][0]
        self.assertEqual(result["status"], "success", result)
        process = subprocess.run(
            [
                core.video.binary_path("ffprobe"),
                "-v",
                "error",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "csv=p=0",
                result["output"],
            ],
            capture_output=True,
            text=True,
            creationflags=core.video.CREATE_NO_WINDOW,
        )
        self.assertIn("av1", process.stdout)
        self.assertIn("opus", process.stdout)

    def test_small_silent_video_is_valid(self):
        source = self.source / "still.mp4"
        subprocess.run(
            [
                core.video.binary_path("ffmpeg"),
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=black:size=64x64:rate=1",
                "-frames:v",
                "1",
                "-c:v",
                "mpeg4",
                "-y",
                str(source),
            ],
            check=True,
            capture_output=True,
            creationflags=core.video.CREATE_NO_WINDOW,
            timeout=30,
        )
        results, _ = self.run_queue(core.scan(self.source, self.output))
        self.assertEqual(results[0]["status"], "success", results)
        self.assertLess(results[0]["size"], 2048)

    def test_video_cancellation_cleans_partial_output(self):
        self.make_video()
        tasks = core.scan(self.source, self.output)
        cancel = core.Cancellation()
        events = []

        def emit(kind, data):
            events.append((kind, data))
            if kind == "stage" and data["status"] == "压缩中":
                cancel.cancel()

        core.run(tasks, self.output, core.Options(skip_larger=False), cancel, emit)
        results = [data for kind, data in events if kind == "result"]
        self.assertEqual(results[0]["status"], "cancel", results)
        self.assertFalse(list(self.output.rglob("*.partial*")))


if __name__ == "__main__":
    unittest.main()
