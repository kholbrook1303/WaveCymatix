from configparser import ConfigParser
import unittest
from pathlib import Path

from wavecymatix.core.ui.GuiManager import GuiManager
from wavecymatix.lib.config import Config


class ConfigTests(unittest.TestCase):
    def test_application_toml_files_parse_with_native_types(self):
        config_directory = Path(__file__).parents[1] / "conf"
        settings = Config(config_directory / "settings.toml")
        for path in config_directory.glob("*.toml"):
            Config(path)

        self.assertIsInstance(settings.general["log_level"], int)
        self.assertEqual(settings.ui["window_selected_color"], [41, 74, 122])
        self.assertEqual(settings.ui["window_deselected_color"], [20, 20, 20])
        self.assertEqual(settings.ui["window_border_color"], [0, 0, 0])
        self.assertEqual(settings.ui["overlay_border_color"], [128, 128, 128])
        self.assertEqual(settings.ui["window_background_alpha"], 0.75)
        gui_manager = GuiManager.__new__(GuiManager)
        gui_manager._ui_settings = settings.ui
        self.assertEqual(
            gui_manager._get_color_setting("window_selected_color", (0, 0, 0)),
            (41 / 255, 74 / 255, 122 / 255),
        )
        self.assertEqual(
            gui_manager._get_color_setting("window_deselected_color", (0, 0, 0)),
            (20 / 255, 20 / 255, 20 / 255),
        )
        self.assertIsInstance(settings.ui["visuals_enabled"], bool)
        self.assertEqual(
            settings.automatic["card_profile_types"],
            ["input-output", "input", "output"],
        )
        self.assertIs(settings.projectm["window.fullscreen"], True)
        self.assertEqual(
            Config(config_directory / "audio_sources.toml").general["audio_sources"],
            [],
        )
        self.assertTrue((config_directory / "sprites.ini").is_file())

    def test_projectm_sprite_ini_ignores_its_slash_comments(self):
        config_directory = Path(__file__).parents[1] / "conf"
        sprites = ConfigParser(
            allow_no_value=True,
            comment_prefixes=("#", ";", "//"),
        )
        sprites.read(config_directory / "sprites.ini")

        self.assertEqual(len(sprites.sections()), 10)
        self.assertFalse(
            any(
                name.startswith("//")
                for section in sprites.sections()
                for name, _ in sprites.items(section)
            )
        )


if __name__ == "__main__":
    unittest.main()
