"""Tests for the Spotify plugin."""

import unittest
from unittest.mock import Mock

from wavecymatix.core.plugins.Spotify import Spotify


class SpotifyTests(unittest.TestCase):
    def setUp(self):
        self.plugin = object.__new__(Spotify)
        self.plugin.now_playing = Mock()
        self.plugin._last_track_id = None
        self.plugin._fetch_artwork = Mock(return_value=None)

    def test_metadata_is_normalized_and_displayed(self):
        self.plugin._handle_metadata(
            {
                "mpris:trackid": "/track/1",
                "xesam:title": "Track",
                "xesam:artist": ["Artist One", "Artist Two"],
                "xesam:album": "Album",
            }
        )

        self.plugin.now_playing.set_track_info.assert_called_once_with(
            title="Track",
            artist="Artist One, Artist Two",
            album="Album",
            album_art=None,
        )
        self.plugin.now_playing.display_track_info.assert_called_once_with()

    def test_duplicate_track_id_does_not_commit_metadata_again(self):
        metadata = {
            "mpris:trackid": "/track/1",
            "xesam:title": "Track",
        }
        self.plugin._handle_metadata(metadata)
        self.plugin._handle_metadata(metadata)

        self.plugin.now_playing.set_track_info.assert_called_once()


if __name__ == "__main__":
    unittest.main()
