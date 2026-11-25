import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from wavecymatix.core.RenderingLoop import RenderingLoop, SignalMonitor
from wavecymatix.core.SDLRenderingWindow import SDLRenderingWindow


class RenderingComponentTests(unittest.TestCase):
    def test_signal_monitor_records_exit_signal(self):
        with patch("wavecymatix.core.RenderingLoop.signal.signal"):
            monitor = SignalMonitor()

        monitor.set_exit(2, None)

        self.assertTrue(monitor.exit)

    def test_viewport_size_tracks_drawable_changes(self):
        loop = object.__new__(RenderingLoop)
        loop.sdl_rendering = Mock()
        loop.sdl_rendering.get_drawable_size.return_value = (1920, 1080)
        loop.render_width = 1280
        loop.render_height = 720

        loop.check_viewport_size()

        self.assertEqual((loop.render_width, loop.render_height), (1920, 1080))

    def test_window_geometry_respects_explicit_position(self):
        window = object.__new__(SDLRenderingWindow)
        window.config = SimpleNamespace(
            projectm={
                "window.width": 1024,
                "window.height": 768,
                "window.left": 25,
                "window.top": 40,
                "window.overrideposition": True,
            }
        )

        self.assertEqual(window._compute_window_geometry(), (25, 40, 1024, 768))

    def test_window_geometry_uses_sdl_default_position_without_override(self):
        window = object.__new__(SDLRenderingWindow)
        window.config = SimpleNamespace(
            projectm={
                "window.width": 800,
                "window.height": 600,
                "window.overrideposition": False,
            }
        )

        geometry = window._compute_window_geometry()

        self.assertEqual(
            geometry,
            (sdl_window_position_undefined(), sdl_window_position_undefined(), 800, 600),
        )


def sdl_window_position_undefined():
    import sdl2

    return sdl2.SDL_WINDOWPOS_UNDEFINED


if __name__ == "__main__":
    unittest.main()
