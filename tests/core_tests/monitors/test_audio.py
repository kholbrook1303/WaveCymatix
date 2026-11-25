"""Tests for the core audio monitor."""

import unittest
from types import SimpleNamespace

from wavecymatix.core.monitors.Audio import Audio, DeviceCatalog


class DeviceCatalogTests(unittest.TestCase):
    def test_catalog_starts_with_independent_empty_device_maps(self):
        catalog = DeviceCatalog()

        self.assertEqual(catalog.card, {})
        self.assertEqual(catalog.sink, {})
        self.assertEqual(catalog.source, {})
        self.assertEqual(catalog.plugin_devices, {})
        self.assertIsNot(catalog.card, catalog.sink)


class AudioMicrophoneDetectionTests(unittest.TestCase):
    def setUp(self):
        self.audio = object.__new__(Audio)

    def test_detects_microphone_by_active_port_name_or_description(self):
        named_mic = SimpleNamespace(
            port_active=SimpleNamespace(name="front-mic", description="")
        )
        described_mic = SimpleNamespace(
            port_active=SimpleNamespace(name="analog-input", description="USB Mic")
        )
        other_source = SimpleNamespace(
            port_active=SimpleNamespace(name="analog-output", description="Line In")
        )

        self.assertTrue(self.audio._is_mic_source(named_mic))
        self.assertTrue(self.audio._is_mic_source(described_mic))
        self.assertFalse(self.audio._is_mic_source(other_source))
        self.assertFalse(self.audio._is_mic_source(SimpleNamespace(port_active=None)))

    def test_selects_only_a_unique_physical_alsa_microphone(self):
        mic = SimpleNamespace(
            name="alsa_input.usb-mic",
            proplist={"device.api": "alsa", "device.class": "sound"},
            port_active=SimpleNamespace(name="analog-input-mic", description=""),
        )
        monitor = SimpleNamespace(
            name="alsa_input.usb-mic.monitor",
            proplist={"device.api": "alsa", "device.class": "monitor"},
            port_active=mic.port_active,
        )
        pulse = SimpleNamespace(source_list=lambda: [monitor, mic])

        self.assertIs(self.audio._get_mic_source(pulse), mic)

        second_mic = SimpleNamespace(
            name="alsa_input.second-mic",
            proplist={"device.api": "alsa", "device.class": "sound"},
            port_active=mic.port_active,
        )
        pulse.source_list = lambda: [mic, second_mic]
        self.assertIsNone(self.audio._get_mic_source(pulse))


if __name__ == "__main__":
    unittest.main()
