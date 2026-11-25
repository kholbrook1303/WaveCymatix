import unittest
from unittest.mock import Mock

from wavecymatix.core.ui.MediaPlayerUI import MediaPlayerUI


class MediaPlayerUITests(unittest.TestCase):
    def setUp(self):
        self.ui = object.__new__(MediaPlayerUI)
        self.ui._drag_payloads = {}
        self.ui.sprite_popup = False
        self.ui.playlist_popup = False
        self.ui.sprite_popup_just_opened = False
        self.ui.playlist_popup_just_opened = False
        self.ui.ui_ctrl = Mock()

    def test_drag_payload_decodes_text_and_bytes_json(self):
        self.assertEqual(self.ui._decode_dnd_payload('["track.mp3"]'), ["track.mp3"])
        self.assertEqual(
            self.ui._decode_dnd_payload(b'{"paths":["track.mp3"]}'),
            {"paths": ["track.mp3"]},
        )
        self.assertIsNone(self.ui._decode_dnd_payload(b"not-json"))
        self.assertIsNone(self.ui._decode_dnd_payload(None))

    def test_opening_sprite_popup_closes_playlist_popup(self):
        self.ui.playlist_popup = True

        self.ui.toggle_sprite_popup()

        self.assertTrue(self.ui.sprite_popup)
        self.assertFalse(self.ui.playlist_popup)
        self.assertTrue(self.ui.sprite_popup_just_opened)


if __name__ == "__main__":
    unittest.main()
