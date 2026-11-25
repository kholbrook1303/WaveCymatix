import unittest
from unittest.mock import Mock

from wavecymatix.core.visual.Slideshow import Slideshow


class SlideshowTests(unittest.TestCase):
    def test_image_rect_covers_area_while_preserving_aspect_ratio(self):
        slideshow = object.__new__(Slideshow)

        x, y, width, height = slideshow._compute_image_rect(1600, 900, 1000, 1000)

        self.assertAlmostEqual(width, 1000 * 16 / 9)
        self.assertAlmostEqual(height, 1000)
        self.assertLess(x, 0)
        self.assertEqual(y, 0)

    def test_applied_images_are_initialized_in_order_without_shuffle(self):
        slideshow = object.__new__(Slideshow)
        slideshow.gui_manager = Mock()
        slideshow.gui_manager.load_texture.side_effect = [
            ("texture-1", 640, 480),
            ("texture-2", 800, 600),
        ]
        slideshow.randomize = True

        slideshow._apply_images(["one.jpg", "two.png"], shuffle=False)

        self.assertEqual(slideshow.current_index, 0)
        self.assertEqual(slideshow.next_index, 1)
        self.assertEqual(slideshow.current_texture, "texture-1")
        self.assertEqual(slideshow.next_texture, "texture-2")
        self.assertEqual(slideshow.images, ["one.jpg", "two.png"])


if __name__ == "__main__":
    unittest.main()
