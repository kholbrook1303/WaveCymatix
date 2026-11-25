"""Tests for the Bluetooth plugin."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from wavecymatix.core.plugins.Bluetooth import Bluetooth


class BluetoothTests(unittest.TestCase):
    def setUp(self):
        self.plugin = object.__new__(Bluetooth)
        self.plugin.now_playing = Mock()
        self.plugin._last_metadata = {}
        self.plugin._player_objects = {}
        self.plugin._active_addr = None

    def test_unwrap_returns_wrapped_value_and_preserves_plain_value(self):
        self.assertEqual(self.plugin._unwrap(SimpleNamespace(value=42)), 42)
        self.assertEqual(self.plugin._unwrap("plain"), "plain")
        self.assertIsNone(self.plugin._unwrap(None))

    def test_track_update_commits_wrapped_properties_and_clears_track(self):
        self.plugin._handle_track_update(
            "device-1",
            {
                "Title": SimpleNamespace(value="Track"),
                "Artist": SimpleNamespace(value="Artist"),
                "Album": SimpleNamespace(value="Album"),
            },
        )

        self.assertEqual(self.plugin._active_addr, "device-1")
        self.plugin.now_playing.set_track_info.assert_called_once_with(
            "Track", artist="Artist", album="Album", album_art=None
        )

        self.plugin._handle_track_update("device-1", {})

        self.plugin.now_playing.clear_track_info.assert_called_once_with()
        self.assertNotIn("device-1", self.plugin._last_metadata)


if __name__ == "__main__":
    unittest.main()
