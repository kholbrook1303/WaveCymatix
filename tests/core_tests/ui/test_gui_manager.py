import unittest
from unittest.mock import patch

from PIL import Image

from wavecymatix.core.ui.GuiManager import GuiManager, GL


class GuiManagerTests(unittest.TestCase):
    def test_compute_safe_region_centers_ultrawide_screen_in_sixteen_nine_area(self):
        manager = object.__new__(GuiManager)

        x, y, width, height = manager.compute_safe_region(2560, 1080)

        self.assertAlmostEqual(width / height, 16 / 9)
        self.assertAlmostEqual(x, 320)
        self.assertEqual(y, 0)

    def test_scale_px_applies_ui_scale_and_minimum(self):
        manager = object.__new__(GuiManager)
        manager.ui_scale = 1.5

        self.assertEqual(manager.scale_px(10), 15)
        self.assertEqual(manager.scale_px(0.2, min_value=1), 1)
        self.assertEqual(manager.scale_px(10, as_int=False), 15.0)

    def test_load_texture_generates_mipmaps_for_minification(self):
        manager = object.__new__(GuiManager)
        image = Image.new("RGBA", (16, 16))

        with (
            patch("wavecymatix.core.ui.GuiManager.Image.open", return_value=image),
            patch.object(GL, "glGenTextures", return_value=7),
            patch.object(GL, "glBindTexture") as bind_texture,
            patch.object(GL, "glTexParameteri") as tex_parameter,
            patch.object(GL, "glTexImage2D") as tex_image,
            patch.object(GL, "glGenerateMipmap") as generate_mipmap,
        ):
            texture, width, height = manager.load_texture("icon.png")

        self.assertEqual((texture, width, height), (7, 16, 16))
        tex_parameter.assert_any_call(
            GL.GL_TEXTURE_2D,
            GL.GL_TEXTURE_MIN_FILTER,
            GL.GL_LINEAR_MIPMAP_LINEAR,
        )
        tex_parameter.assert_any_call(
            GL.GL_TEXTURE_2D,
            GL.GL_TEXTURE_MAG_FILTER,
            GL.GL_LINEAR,
        )
        tex_image.assert_called_once()
        generate_mipmap.assert_called_once_with(GL.GL_TEXTURE_2D)
        self.assertEqual(bind_texture.call_count, 2)


if __name__ == "__main__":
    unittest.main()
