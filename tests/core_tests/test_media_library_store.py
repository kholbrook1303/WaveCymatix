import os
import tempfile
import unittest
from pathlib import Path

from wavecymatix.core.MediaLibraryStore import MediaLibraryStore


class MediaLibraryStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = MediaLibraryStore(
            media_type="audio_local",
            section_config={"playlistdbpath": os.path.join(self.temp_dir.name, "library.db")},
            supported_extensions=(".mp3", ".flac"),
            key_prefix="vlc",
            system_playlists=("all", "favorites"),
            default_playlist="mix",
        )
        self.paths = [
            os.path.join(self.temp_dir.name, "z-track.mp3"),
            os.path.join(self.temp_dir.name, "a-track.flac"),
        ]
        for path in self.paths:
            Path(path).touch()

    def tearDown(self):
        self.store.close()
        self.temp_dir.cleanup()

    def test_sync_creates_sorted_all_playlist_and_ignores_unsupported_files(self):
        unsupported_path = os.path.join(self.temp_dir.name, "ignore.txt")
        Path(unsupported_path).touch()
        self.store.sync_library([*self.paths, unsupported_path])

        self.assertEqual(self.store.get_playlist_items("all"), sorted(self.paths, key=str.lower))
        self.assertEqual(self.store.playlist_size("all"), 2)

    def test_custom_playlist_operations_preserve_order_and_reject_system_delete(self):
        self.store.sync_library(self.paths)
        self.assertTrue(self.store.create_playlist(" mix "))
        self.assertEqual(
            self.store.add_items_to_playlist("mix", self.paths),
            2,
        )
        self.assertEqual(self.store.add_items_to_playlist("mix", [self.paths[0]]), 0)
        self.assertEqual(
            self.store.get_playlist_items("mix"),
            self.paths,
        )

        self.assertTrue(self.store.move_item_in_playlist("mix", 0, 1))
        self.assertEqual(self.store.get_playlist_items("mix"), list(reversed(self.paths)))
        self.assertFalse(self.store.delete_playlist("all"))
        self.assertTrue(self.store.delete_playlist("mix"))
        self.assertEqual(self.store.get_playlist_items("mix"), [])

    def test_favorites_and_video_window_round_trip(self):
        self.store.sync_library(self.paths)
        self.assertEqual(self.store.add_items_to_favorites([self.paths[0]]), 1)
        self.assertTrue(self.store.is_favorite(self.paths[0]))
        self.assertEqual(self.store.remove_items_from_favorites([self.paths[0]]), 1)
        self.assertFalse(self.store.is_favorite(self.paths[0]))

        self.assertTrue(self.store.set_video_item_window(self.paths[1], 1.25, 8.5))
        self.assertEqual(
            self.store.get_video_item_window(self.paths[1]),
            {"start_sec": 1.25, "stop_sec": 8.5},
        )

    def test_configured_startup_playlist_is_used_when_nonempty(self):
        self.store.create_playlist("mix")
        self.store.add_items_to_playlist("mix", [self.paths[0]])

        self.assertEqual(self.store.resolve_startup_playlist(), "mix")


if __name__ == "__main__":
    unittest.main()
