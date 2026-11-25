import unittest
from unittest.mock import Mock

from wavecymatix.core.ui.ToolbarUI import ToolbarUI


class ToolbarUITests(unittest.TestCase):
    def test_toggle_ui_menu_updates_open_state_and_request_state(self):
        toolbar = ToolbarUI(Mock(), Mock(), Mock())

        toolbar.toggle_ui_menu()

        self.assertTrue(toolbar.ui_popup_open)
        self.assertTrue(toolbar.ui_popup_request_open)

        toolbar.toggle_ui_menu()

        self.assertFalse(toolbar.ui_popup_open)
        self.assertFalse(toolbar.ui_popup_request_open)


if __name__ == "__main__":
    unittest.main()
