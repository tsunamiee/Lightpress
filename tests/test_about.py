"""Regression checks for the component license list, without creating windows."""

from pathlib import Path
import tempfile
import unittest

from compressor.about import component_licenses, license_text


class ComponentLicenseTests(unittest.TestCase):
    def test_ffmpeg_prefers_bundled_license_and_excludes_application(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            folder = base / "licenses"
            folder.mkdir()
            (base / "LICENSE").write_text("Application MIT license", encoding="utf-8")
            primary = folder / "FFmpeg.txt"
            primary.write_text("Actual build license", encoding="utf-8")
            (folder / "FFmpeg-GPL-v3.txt").write_text("Fallback license", encoding="utf-8")
            entries = component_licenses(base)
            self.assertEqual([name for name, _ in entries], ["FFmpeg"])
            self.assertEqual(license_text(entries[0][1]), "Actual build license")
            primary.unlink()
            entries = component_licenses(base)
            self.assertEqual([name for name, _ in entries], ["FFmpeg"])
            self.assertEqual(license_text(entries[0][1]), "Fallback license")

    def test_dual_license_keeps_both_texts_in_one_component(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            folder = base / "licenses"
            folder.mkdir()
            (folder / "resvg-MIT.txt").write_text("MIT permission text", encoding="utf-8")
            (folder / "resvg-Apache-2.0.txt").write_text("Apache permission text", encoding="utf-8")
            entries = component_licenses(base)
            self.assertEqual([name for name, _ in entries], ["resvg"])
            text = license_text(entries[0][1])
            self.assertIn("MIT permission text", text)
            self.assertIn("Apache permission text", text)


if __name__ == "__main__":
    unittest.main()
