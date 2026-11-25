import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import sdl2

from wavecymatix.core.InputEventListener import InputEventListener, SDLInputEventListener


class InputEventListenerTests(unittest.TestCase):
    def test_pointer_coordinates_are_clamped_to_window_bounds(self):
        listener = object.__new__(InputEventListener)
        listener._get_window_size = Mock(return_value=(640, 480))

        self.assertEqual(listener._clamp_pointer(-10, 500), (0, 479))
        self.assertEqual(listener._clamp_pointer(100.9, 20.8), (100, 20))


class SDLInputEventListenerTests(unittest.TestCase):
    def setUp(self):
        self.listener = object.__new__(SDLInputEventListener)
        self.listener.ui_ctrl = Mock()
        self.listener.input_digits = ""
        self.listener.last_digit_time = 0
        self.listener.sprite_logo = False
        self.listener.thread_event = Mock()

    def test_rotates_normalized_touch_coordinates(self):
        self.assertEqual(self.listener.rotate_coords(0.2, 0.3, 90), (0.3, 0.8))
        self.assertEqual(self.listener.rotate_coords(0.2, 0.3, 180), (0.8, 0.7))
        self.assertEqual(self.listener.rotate_coords(0.2, 0.3, 270), (0.7, 0.2))
        self.assertEqual(self.listener.rotate_coords(0.2, 0.3, 0), (0.2, 0.3))

    def test_vertical_active_region_excludes_top_and_bottom_margins(self):
        self.assertTrue(self.listener.in_active_vertical_region(0.5))
        self.assertTrue(self.listener.in_active_vertical_region(0.2))
        self.assertFalse(self.listener.in_active_vertical_region(0.1))
        self.assertFalse(self.listener.in_active_vertical_region(0.9))

    def test_right_arrow_advances_visual(self):
        event = SimpleNamespace(
            key=SimpleNamespace(
                keysym=SimpleNamespace(sym=sdl2.SDLK_RIGHT, mod=0)
            )
        )

        self.listener.key_event(event, True)

        self.listener.ui_ctrl.next_visual.assert_called_once_with()

    def test_controller_axis_only_triggers_on_state_transition(self):
        self.listener.controller_axis_states = {
            sdl2.SDL_CONTROLLER_AXIS_LEFTX: "NEUTRAL"
        }
        event = SimpleNamespace(
            caxis=SimpleNamespace(
                axis=sdl2.SDL_CONTROLLER_AXIS_LEFTX,
                value=20000,
            )
        )

        self.listener.controller_axis_event(event)
        self.listener.controller_axis_event(event)

        self.listener.ui_ctrl.next_visual.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
