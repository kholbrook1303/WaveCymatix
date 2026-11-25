"""Tests for the Windows Media plugin."""

import unittest
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from wavecymatix.core.plugins import WindowsMedia as windows_media_module
from wavecymatix.core.plugins.WindowsMedia import WindowsMedia


class WindowsMediaTests(IsolatedAsyncioTestCase):
    async def test_metadata_update_sends_track_and_marks_ownership(self):
        plugin = object.__new__(WindowsMedia)
        plugin._session = SimpleNamespace(
            get_playback_info=lambda: SimpleNamespace(playback_status="playing"),
            try_get_media_properties_async=AsyncMock(
                return_value=SimpleNamespace(
                    title="Track",
                    artist="Artist",
                    album_title="Album",
                    album_artist="",
                    track_number=1,
                    genres=[],
                    playback_type="Music",
                    subtitle="",
                    thumbnail=None,
                )
            ),
        )
        plugin._playing = False
        plugin._last_signature = None
        plugin._owns_track_info = False
        plugin.now_playing = Mock()
        plugin._load_thumbnail_rgba = AsyncMock(return_value=None)

        with patch.object(
            windows_media_module,
            "GlobalSystemMediaTransportControlsSessionPlaybackStatus",
            SimpleNamespace(PLAYING="playing"),
        ):
            await plugin._update_metadata()

        self.assertTrue(plugin._playing)
        self.assertTrue(plugin._owns_track_info)
        plugin.now_playing.set_track_info.assert_called_once_with(
            title="Track",
            artist="Artist",
            album="Album",
            album_art=None,
        )
        plugin.now_playing.display_track_info.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
