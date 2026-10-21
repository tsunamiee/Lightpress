"""Check SVG rendering without a desktop session."""

import io
import unittest

from PIL import Image, ImageChops, ImageStat

from compressor.graphics import asset_dir, render_icon


class GraphicsTests(unittest.TestCase):
    def test_icons_render_at_requested_sizes(self):
        for source in (asset_dir() / "icons").glob("*.svg"):
            for size in (24, 30, 36, 48):
                with self.subTest(icon=source.stem, size=size):
                    image = Image.open(io.BytesIO(render_icon(source.stem, "#3869EC", size)))
                    image.load()
                    self.assertEqual(image.size, (size, size))
                    self.assertEqual(image.mode, "RGBA")
                    self.assertIsNotNone(image.getbbox())
                    self.assertEqual(image.getpixel((0, 0))[3], 0)

    def test_quality_ring_is_centered_and_not_clipped(self):
        for size in (24, 30, 36, 48):
            with self.subTest(size=size):
                image = Image.open(io.BytesIO(render_icon("quality-thumb", "#3869EC", size)))
                alpha = image.getchannel("A")
                left, top, right, bottom = alpha.getbbox()
                self.assertGreater(left, 0)
                self.assertGreater(top, 0)
                self.assertEqual((left, top), (size - right, size - bottom))
                for direction in (Image.Transpose.FLIP_LEFT_RIGHT, Image.Transpose.FLIP_TOP_BOTTOM):
                    delta = ImageChops.difference(alpha, alpha.transpose(direction))
                    self.assertLessEqual(ImageStat.Stat(delta).mean[0], 0.5)

    def test_quality_ring_uses_theme_colors(self):
        for accent, surface in (("#3869EC", "#FFFFFF"), ("#91AEFF", "#222A38")):
            with self.subTest(accent=accent):
                image = Image.open(
                    io.BytesIO(render_icon("quality-thumb", accent, surface=surface))
                )
                expected_accent = tuple(bytes.fromhex(accent[1:]))
                expected_surface = tuple(bytes.fromhex(surface[1:]))
                self.assertEqual(image.getpixel((12, 12)), expected_accent + (255,))
                self.assertEqual(image.getpixel((12, 6)), expected_surface + (255,))


if __name__ == "__main__":
    unittest.main()
