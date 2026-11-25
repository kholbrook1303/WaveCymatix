import unittest
from unittest.mock import Mock

from wavecymatix.core.ui.DiagnosticsUI import DiagnosticsUI


class DiagnosticsUITests(unittest.TestCase):
    def test_metrics_and_formatters_handle_zero_and_missing_values(self):
        diagnostics = DiagnosticsUI(Mock(), Mock())

        diagnostics.update_metrics(0.25, 0.01)

        self.assertEqual(diagnostics.current_fps, 4)
        self.assertEqual(diagnostics.swap_time, 0.01)
        self.assertEqual(diagnostics._fmt_ms(0.0125), "12.5ms")
        self.assertEqual(diagnostics._fmt_s(1.236), "1.24s")
        self.assertEqual(diagnostics._fmt_status("fps_below_target"), "Fps Below Target")
        self.assertEqual(diagnostics._fmt_reason(None), "N/A")

        diagnostics.update_metrics(0)
        self.assertEqual(diagnostics.current_fps, 0)

    def test_toggle_flips_overlay_visibility(self):
        diagnostics = DiagnosticsUI(Mock(), Mock())

        diagnostics.toggle()
        self.assertTrue(diagnostics.visible)
        diagnostics.toggle()
        self.assertFalse(diagnostics.visible)


if __name__ == "__main__":
    unittest.main()
