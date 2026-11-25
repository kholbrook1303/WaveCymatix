import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from wavecymatix.core.UIController import UIController


class UIControllerTests(unittest.TestCase):
    def test_available_visual_modes_follow_configuration(self):
        config = SimpleNamespace(
            ui={"visuals_enabled": True, "default_visual_mode": "projectm"},
            visuals={
                "projectm_enabled": True,
                "video_background_enabled": False,
                "slideshow_enabled": True,
            },
        )

        controller = UIController(config, Mock(), [])

        self.assertEqual(
            controller.visual_modes,
            [("projectm", "ProjectM"), ("slideshow", "Slideshow"), ("none", "None")],
        )
        self.assertEqual(controller.get_visual_mode(), "none")

    def test_visual_mode_switch_hides_other_modes_and_starts_video(self):
        controller = object.__new__(UIController)
        controller.projectm = SimpleNamespace(visible=True)
        controller.slideshow_ui = SimpleNamespace(visible=True)
        controller.video_background = Mock()
        controller.video_background.visible = False
        controller.set_visual_mode("video_background")

        self.assertFalse(controller.projectm.visible)
        self.assertFalse(controller.slideshow_ui.visible)
        self.assertTrue(controller.video_background.visible)
        controller.video_background.stop.assert_called_once_with()
        controller.video_background.start.assert_called_once_with()
        self.assertEqual(controller.visual_mode, "video_background")

    def test_playback_toggle_targets_the_first_active_handler(self):
        first = Mock()
        first.handler_active = True
        first.is_playing.return_value = True
        second = Mock()
        second.handler_active = True
        controller = object.__new__(UIController)
        controller.plugins = [first, second]

        controller.toggle_playback()

        first.pause.assert_called_once_with()
        second.pause.assert_not_called()
        second.play.assert_not_called()


if __name__ == "__main__":
    unittest.main()
