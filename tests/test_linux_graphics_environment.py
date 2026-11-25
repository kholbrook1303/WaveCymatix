"""Tests for Linux graphics environment setup."""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from wavecymatix.lib.common import configure_linux_graphics_environment


class LinuxGraphicsEnvironmentTests(unittest.TestCase):
    def test_application_sets_mesa_override_before_loading_sdl(self):
        entrypoint = (
            Path(__file__).parents[1] / "src" / "wavecymatix" / "app.py"
        )
        source = entrypoint.read_text(encoding="utf-8")

        self.assertLess(
            source.index("configure_linux_graphics_environment()"),
            source.index("from wavecymatix.core.RenderingLoop import RenderingLoop"),
        )

    def test_sets_mesa_override_for_linux(self):
        with (
            mock.patch.object(sys, "platform", "linux"),
            mock.patch.dict(os.environ, {}, clear=True),
        ):
            configure_linux_graphics_environment()

            self.assertEqual(os.environ["MESA_GL_VERSION_OVERRIDE"], "3.3")

    def test_preserves_existing_mesa_override(self):
        with (
            mock.patch.object(sys, "platform", "linux"),
            mock.patch.dict(os.environ, {"MESA_GL_VERSION_OVERRIDE": "4.5"}),
        ):
            configure_linux_graphics_environment()

            self.assertEqual(os.environ["MESA_GL_VERSION_OVERRIDE"], "4.5")

    def test_does_not_set_mesa_override_on_other_platforms(self):
        with (
            mock.patch.object(sys, "platform", "darwin"),
            mock.patch.dict(os.environ, {}, clear=True),
        ):
            configure_linux_graphics_environment()

            self.assertNotIn("MESA_GL_VERSION_OVERRIDE", os.environ)


if __name__ == "__main__":
    unittest.main()
