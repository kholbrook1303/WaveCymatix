"""Tests for the Airplay plugin."""

import unittest
from unittest.mock import Mock, patch

from wavecymatix.core.plugins.Airplay import Airplay


class VariantStub:
    def __init__(self, value):
        self.value = value


class AirplayTests(unittest.TestCase):
    def setUp(self):
        self.plugin = object.__new__(Airplay)
        self.plugin.now_playing = Mock()
        self.plugin.handler_active = False

    def test_metadata_commits_track_and_normalizes_artist_list(self):
        with patch("wavecymatix.core.plugins.Airplay.Variant", VariantStub):
            self.plugin._commit_metadata(
                {
                    "xesam:title": VariantStub("Track"),
                    "xesam:artist": VariantStub(["Artist One", "Artist Two"]),
                    "xesam:album": VariantStub("Album"),
                }
            )

        self.assertTrue(self.plugin.handler_active)
        self.plugin.now_playing.set_track_info.assert_called_once_with(
            "Track",
            artist="Artist One, Artist Two",
            album="Album",
            album_art=None,
        )

    def test_missing_title_clears_track_and_marks_plugin_inactive(self):
        self.plugin.handler_active = True

        self.plugin._commit_metadata({"xesam:title": ""})

        self.assertFalse(self.plugin.handler_active)
        self.plugin.now_playing.clear_track_info.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
