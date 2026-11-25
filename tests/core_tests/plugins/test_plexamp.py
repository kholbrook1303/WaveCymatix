"""Tests for the Plexamp plugin."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from wavecymatix.core.plugins.Plexamp import Plexamp


class PlexampTests(unittest.TestCase):
    def test_track_commit_maps_track_fields_to_now_playing(self):
        plugin = object.__new__(Plexamp)
        plugin._track_initialized = False
        plugin._fetch_artwork = Mock(return_value=None)
        plugin.now_playing = Mock()
        session = SimpleNamespace(
            type="track",
            title="Track",
            grandparentTitle="Artist",
            parentTitle="Album",
            thumb="/library/metadata/cover",
        )

        plugin._commit_track(session)

        self.assertTrue(plugin._track_initialized)
        plugin._fetch_artwork.assert_called_once_with(session.thumb)
        plugin.now_playing.set_track_info.assert_called_once_with(
            "Track", artist="Artist", album="Album", album_art=None
        )

    def test_artwork_resize_preserves_aspect_ratio_within_texture_limit(self):
        from PIL import Image

        plugin = object.__new__(Plexamp)
        resized = plugin._resize_album_art(Image.new("RGBA", (4096, 2048)))

        self.assertEqual(resized.size, (Plexamp.MAX_TEXTURE_SIZE, 1024))


if __name__ == "__main__":
    unittest.main()
