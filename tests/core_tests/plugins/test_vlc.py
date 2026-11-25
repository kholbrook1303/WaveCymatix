"""Tests for the VLC plugin."""

import unittest
from unittest import mock

from wavecymatix.core.plugins.VLC import VLC


class VLCTests(unittest.TestCase):
    def setUp(self):
        self.plugin = object.__new__(VLC)
        self.plugin._audio_extensions = VLC.AUDIO_EXTENSIONS

    def test_file_uri_is_decoded_and_windows_drive_prefix_is_normalized(self):
        self.assertEqual(
            self.plugin._file_uri_to_path("file:///C:/Music/Track%20One.flac"),
            "C:/Music/Track One.flac",
        )

    def test_path_input_accepts_supported_file_extensions_case_insensitively(self):
        with (
            mock.patch("wavecymatix.core.plugins.VLC.os.path.isdir", return_value=False),
            mock.patch("wavecymatix.core.plugins.VLC.os.path.splitext", return_value=("track", ".FLAC")),
        ):
            self.assertEqual(
                self.plugin._expand_path_input("track.FLAC"),
                ["track.FLAC"],
            )

        with (
            mock.patch("wavecymatix.core.plugins.VLC.os.path.isdir", return_value=False),
            mock.patch("wavecymatix.core.plugins.VLC.os.path.splitext", return_value=("track", ".txt")),
        ):
            self.assertEqual(self.plugin._expand_path_input("track.txt"), [])


if __name__ == "__main__":
    unittest.main()
