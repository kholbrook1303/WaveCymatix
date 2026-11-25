import unittest
from unittest.mock import Mock

from wavecymatix.core.ui.NowPlayingUI import NowPlayingUI


class NowPlayingUITests(unittest.TestCase):
    def setUp(self):
        self.gui = Mock()
        self.ui = NowPlayingUI(self.gui, Mock())

    def test_track_updates_display_and_clear_resets_track_state(self):
        self.ui.set_track_info("Track", artist="Artist", album="Album")

        self.assertEqual(self.ui.text, "Track")
        self.assertEqual(self.ui.artist, "Artist")
        self.assertEqual(self.ui.album, "Album")
        self.assertTrue(self.ui.visible)
        self.assertTrue(self.ui.needs_burnin_update)

        self.ui.clear_track_info()

        self.assertEqual(self.ui.text, "")
        self.assertFalse(self.ui.visible)
        self.assertIsNone(self.ui.time_shown)
        self.assertFalse(self.ui.album_ready)

    def test_overlay_hides_after_timeout_unless_pinned(self):
        self.ui.visible = True
        self.ui.text = "Track"
        self.ui.time_shown = 10
        with unittest.mock.patch("wavecymatix.core.ui.NowPlayingUI.time.time", return_value=21):
            self.assertFalse(self.ui._should_show_overlay())
        self.assertFalse(self.ui.visible)

        self.ui.visible = True
        self.ui.keep_visible = True
        self.assertTrue(self.ui._should_show_overlay())


if __name__ == "__main__":
    unittest.main()
