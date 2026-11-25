import unittest
from unittest import mock

from wavecymatix.core.FPSLimiter import FPSLimiter


class FPSLimiterTests(unittest.TestCase):
    def test_target_fps_and_unlimited_mode(self):
        limiter = FPSLimiter()

        limiter.target_fps(50)
        self.assertEqual(limiter.target_frame_time, 20)
        limiter.target_fps(0)
        self.assertEqual(limiter.target_frame_time, 0)

    def test_fps_uses_positive_recent_frame_times(self):
        limiter = FPSLimiter()
        limiter.last_frame_times = [10, 20, 0]

        self.assertAlmostEqual(limiter.fps(), 2000 / 30)

    def test_end_frame_delays_short_frames_and_records_measured_duration(self):
        limiter = FPSLimiter()
        limiter.last_tick_count = 100
        limiter.target_frame_time = 20
        limiter.next_frame_times_offset = 0
        with (
            mock.patch("wavecymatix.core.FPSLimiter.sdl2.SDL_GetTicks", side_effect=[110, 120]),
            mock.patch("wavecymatix.core.FPSLimiter.sdl2.SDL_Delay") as delay,
        ):
            limiter.end_frame()

        delay.assert_called_once_with(10)
        self.assertEqual(limiter.last_frame_times[0], 20)
        self.assertEqual(limiter.next_frame_times_offset, 1)


if __name__ == "__main__":
    unittest.main()
