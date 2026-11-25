import unittest
from types import SimpleNamespace
from unittest import mock

from wavecymatix.core.PerformancePolicy import PerformancePolicy


class PerformancePolicyTests(unittest.TestCase):
    def test_disabled_policy_reports_disabled_without_action(self):
        policy = PerformancePolicy(
            SimpleNamespace(performance={"enabled": False})
        )

        snapshot = policy.evaluate("projectm", "ProjectM", 0.1, 0.0, False)

        self.assertEqual(snapshot["state"], "DISABLED")
        self.assertEqual(snapshot["last_action"], "none")
        self.assertEqual(snapshot["last_suppressed_reason"], "policy_disabled")

    def test_low_fps_policy_requests_visual_advance(self):
        policy = PerformancePolicy(
            SimpleNamespace(
                performance={
                    "enabled": True,
                    "fps_policy_enabled": True,
                    "fps_target": 60,
                    "tolerance": 0.8,
                    "perf_policy_action": "advance_visual",
                }
            )
        )

        with mock.patch("wavecymatix.core.PerformancePolicy.time.time", return_value=100):
            snapshot = policy.evaluate("slideshow", "Slideshow", 1 / 20, 0, False)

        self.assertEqual(snapshot["fps_status"], "UNSTABLE")
        self.assertEqual(snapshot["last_action"], "advance_visual")
        self.assertEqual(snapshot["last_action_reason"], "fps_below_tolerance")

    def test_locked_visual_suppresses_low_fps_action(self):
        policy = PerformancePolicy(
            SimpleNamespace(
                performance={
                    "fps_policy_enabled": True,
                    "fps_target": 60,
                    "tolerance": 0.8,
                }
            )
        )

        with mock.patch("wavecymatix.core.PerformancePolicy.time.time", return_value=100):
            snapshot = policy.evaluate("video", "Video", 1 / 20, 0, True)

        self.assertEqual(snapshot["last_action"], "none")
        self.assertEqual(snapshot["last_suppressed_reason"], "visual_locked")


if __name__ == "__main__":
    unittest.main()
