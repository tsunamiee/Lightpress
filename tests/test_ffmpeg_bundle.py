"""Reject mismatched FFmpeg binaries and altered source assets."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from tools.ffmpeg.build import COMPONENTS
from tools.ffmpeg.bundle import verify_bundle


class SourceBundleTests(unittest.TestCase):
    def make_asset(self, root, *, alter_source=False):
        payload = {
            name: b"example"
            for name in ("build.py", "README.md", "COPYING.GPLv3", "THIRD_PARTY_NOTICES.txt")
        }
        sources = {}
        for name in COMPONENTS:
            content = ("source-" + name).encode()
            filename = name + ".tar.gz"
            sources[name] = dict(filename=filename, sha256=hashlib.sha256(content).hexdigest())
            payload["archives/" + filename] = content
        binaries = {}
        for name in ("ffmpeg.exe", "ffprobe.exe"):
            content = ("binary-" + name).encode()
            (root / name).write_bytes(content)
            binaries[name] = hashlib.sha256(content).hexdigest()
        payload["sources.json"] = json.dumps(dict(sources=sources)).encode()
        payload["build-information.json"] = json.dumps(
            dict(sources=sources, binaries=binaries)
        ).encode()
        manifest = {name: hashlib.sha256(content).hexdigest() for name, content in payload.items()}
        payload["SHA256SUMS.json"] = json.dumps(manifest).encode()
        if alter_source:
            payload["archives/ffmpeg.tar.gz"] = b"changed source"
        path = root / "source.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for name, content in payload.items():
                archive.writestr("ffmpeg-source/" + name, content)
        return path

    def test_matching_source_and_binaries_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            info = verify_bundle(self.make_asset(root), root)
            self.assertEqual(set(info["sources"]), set(COMPONENTS))

    def test_binary_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            asset = self.make_asset(root)
            (root / "ffmpeg.exe").write_bytes(b"different binary")
            with self.assertRaisesRegex(ValueError, "binary does not match"):
                verify_bundle(asset, root)

    def test_modified_source_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "content checksum mismatch"):
                verify_bundle(self.make_asset(root, alter_source=True), root)


if __name__ == "__main__":
    unittest.main()
