import unittest
from collections import deque
from threading import Lock
from unittest import mock

import numpy as np

from wavecymatix.core.AudioCapture import AudioCapture
from wavecymatix.core.AudioCaptureImpl_SDL import AudioCaptureImpl as SDLAudioCaptureImpl
from wavecymatix.core.AudioCaptureImpl_WASAPI import AudioCaptureImpl as WASAPIAudioCaptureImpl


class AudioCaptureTests(unittest.TestCase):
    def setUp(self):
        self.capture = object.__new__(AudioCapture)
        self.capture.sample_rate = 4
        self.capture.channels = 1
        self.capture._pcm_cache_seconds = 1
        self.capture._pcm_cache = deque()
        self.capture._pcm_cache_samples = 0
        self.capture._pcm_cache_lock = Lock()
        self.capture._pcm_max_samples = 4

    def test_pcm_cache_keeps_only_recent_samples_and_returns_snapshots(self):
        self.capture.push_pcm(np.array([1, 2, 3], dtype=np.float32))
        self.capture.push_pcm(np.array([4, 5, 6], dtype=np.float32))

        np.testing.assert_array_equal(
            self.capture.snapshot_pcm(), np.array([4, 5, 6], dtype=np.float32)
        )
        np.testing.assert_array_equal(
            self.capture.snapshot_pcm_seconds(0.5),
            np.array([5, 6], dtype=np.float32),
        )

    def test_pcm_cache_returns_none_when_empty_or_too_short(self):
        self.assertIsNone(self.capture.snapshot_pcm())
        self.assertIsNone(self.capture.snapshot_pcm_seconds(1))

    def test_device_selection_uses_wave_cymatix_monitor_or_default(self):
        self.assertEqual(
            self.capture.get_initial_audio_device_index(
                {0: b"Microphone", 2: b"Monitor of WaveCymatix-NULL-Sink"}
            ),
            2,
        )
        self.assertEqual(
            self.capture.get_initial_audio_device_index({0: b"Microphone"}),
            -1,
        )


class AudioCaptureBackendTests(unittest.TestCase):
    def test_sdl_backend_uses_requested_fps_to_bound_sample_count(self):
        config = mock.Mock()
        config.projectm.get.return_value = 200

        with mock.patch("wavecymatix.core.AudioCaptureImpl_SDL.sdl2.SDL_InitSubSystem"):
            backend = SDLAudioCaptureImpl(config, object())

        self.assertEqual(backend.requestedSampleCount, 300)

    def test_sdl_backend_forwards_pcm_and_reports_audio_devices(self):
        callback = mock.Mock()
        config = mock.Mock()
        config.projectm.get.return_value = 60
        with mock.patch("wavecymatix.core.AudioCaptureImpl_SDL.sdl2.SDL_InitSubSystem"):
            backend = SDLAudioCaptureImpl(config, object(), on_pcm=callback)
        backend.push_pcm([0.25, -0.25])

        callback.assert_called_once_with([0.25, -0.25])
        with (
            mock.patch(
                "wavecymatix.core.AudioCaptureImpl_SDL.sdl2.SDL_GetNumAudioDevices",
                return_value=1,
            ),
            mock.patch(
                "wavecymatix.core.AudioCaptureImpl_SDL.sdl2.SDL_GetAudioDeviceName",
                return_value=b"Input",
            ),
        ):
            self.assertEqual(backend.audio_device_list(), {-1: "Default capturing device", 0: b"Input"})

    def test_wasapi_device_index_rejects_out_of_range_values(self):
        backend = object.__new__(WASAPIAudioCaptureImpl)
        backend.devices = [{"name": "Speakers"}]
        backend.device_index = -1
        backend.capture_restart = False

        backend.audio_device_index(1)
        self.assertEqual(backend.device_index, -1)
        self.assertFalse(backend.capture_restart)

        backend.audio_device_index(0)
        self.assertEqual(backend.device_index, 0)
        self.assertTrue(backend.capture_restart)


if __name__ == "__main__":
    unittest.main()
