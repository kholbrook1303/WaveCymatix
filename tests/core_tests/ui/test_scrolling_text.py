import unittest
from unittest.mock import Mock, patch

from wavecymatix.core.ui.ScrollingText import ScrollingText


class ScrollingTextTests(unittest.TestCase):
    def test_pingpong_scroll_advances_and_reverses_at_boundary(self):
        text = ScrollingText(["long text"], max_width=50, speed=10)
        text.last_time = 5
        text._text_size = Mock(return_value=(100, 12))

        with patch("wavecymatix.core.ui.ScrollingText.time.perf_counter", return_value=5.5):
            text.update()
        self.assertEqual(text.scroll_offset, 5)

        text.scroll_offset = 49
        text.last_time = 5.5
        with patch("wavecymatix.core.ui.ScrollingText.time.perf_counter", return_value=6):
            text.update()
        self.assertEqual(text.scroll_offset, 50)
        self.assertEqual(text.direction, -1)

    def test_empty_text_has_zero_height(self):
        text = ScrollingText([])

        self.assertEqual(text.get_total_height(), 0)


if __name__ == "__main__":
    unittest.main()
