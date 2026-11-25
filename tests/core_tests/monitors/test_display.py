"""Tests for the core display monitor."""

import os
import unittest
from unittest import mock

from wavecymatix.core.monitors.Display import Display, drmModeConnector, drmModeModeInfo


class DisplayTests(unittest.TestCase):
    def setUp(self):
        self.display = object.__new__(Display)

    def test_refresh_rate_returns_zero_for_incomplete_timing(self):
        mode = drmModeModeInfo()
        mode.clock = 148500
        mode.htotal = 2200
        mode.vtotal = 0

        self.assertEqual(self.display.get_refresh_rate(mode), 0.0)

    def test_refresh_rate_uses_pixel_clock_and_totals(self):
        mode = drmModeModeInfo()
        mode.clock = 148500
        mode.htotal = 2200
        mode.vtotal = 1125

        self.assertEqual(self.display.get_refresh_rate(mode), 60.0)

    def test_connector_name_includes_type_and_connector_index(self):
        connector = drmModeConnector()
        connector.connector_type = drmModeConnector.DRM_MODE_CONNECTOR_DisplayPort
        connector.connector_type_id = 2

        self.assertEqual(self.display.get_connector_name(connector), "DP-2")

    def test_wayland_resolution_uses_compositor_specific_command(self):
        self.display.compositor = "kde"
        self.display.resolution = "1920x1080"
        configs = [
            {
                "device": "DP-2",
                "current_resolution": {},
                "resolutions": {"1920x1080": [60]},
            }
        ]

        with (
            mock.patch("wavecymatix.core.monitors.Display.shutil.which", return_value="kscreen-doctor"),
            mock.patch("wavecymatix.core.monitors.Display.execute_managed", return_value=True) as execute,
        ):
            self.display._enforce_wayland_resolution(configs)

        execute.assert_called_once_with(
            ["kscreen-doctor", "output.DP-2.mode.1920x1080"]
        )

    def test_display_type_uses_session_type_before_desktop_hints(self):
        with mock.patch.dict(
            os.environ,
            {
                "XDG_SESSION_TYPE": "wayland",
                "XDG_SESSION_DESKTOP": "GNOME",
                "XDG_CURRENT_DESKTOP": "GNOME",
            },
            clear=True,
        ):
            self.assertEqual(self.display._get_display_type(), "wayland")


if __name__ == "__main__":
    unittest.main()
