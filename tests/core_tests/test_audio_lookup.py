import os
import tempfile
import unittest
import wave

import numpy as np

from wavecymatix.core.AudioLookup import AudioLookup


class AudioLookupTests(unittest.TestCase):
    def setUp(self):
        self.lookup = object.__new__(AudioLookup)
        self.lookup.channels = 2
        self.lookup.sample_rate = 22050

    def test_float_pcm_is_clipped_and_mixed_to_mono_int16(self):
        pcm = np.array(
            [[-1.5, -0.5], [0.25, 0.75], [1.5, 0.5]],
            dtype=np.float32,
        )

        mono = self.lookup._pcm_float_to_int16_mono(pcm)

        np.testing.assert_array_equal(
            mono,
            np.array([-32767, 16383, 32767], dtype=np.int16),
        )

    def test_wav_writer_outputs_mono_16_bit_at_configured_rate(self):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as file:
            wav_path = file.name
        self.lookup.tmp_wav_path = wav_path
        try:
            self.lookup._write_wav(np.array([100, -100], dtype=np.int16))

            with wave.open(wav_path, "rb") as wav_file:
                self.assertEqual(wav_file.getnchannels(), 1)
                self.assertEqual(wav_file.getsampwidth(), 2)
                self.assertEqual(wav_file.getframerate(), 22050)
                self.assertEqual(wav_file.getnframes(), 2)
        finally:
            os.remove(wav_path)


if __name__ == "__main__":
    unittest.main()
