"""Tests for ProjectM visual diagnostics and callbacks."""

import ctypes
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from wavecymatix.core.visual.ProjectM import ProjectM, on_preset_switch_failed


class ProjectMDiagnosticsTests(unittest.TestCase):
    def test_preset_switch_failure_callback_matches_native_arguments(self):
        instance = SimpleNamespace(_on_preset_switch_failed=Mock())
        user_data = ctypes.py_object(instance)
        user_data_ptr = ctypes.cast(ctypes.pointer(user_data), ctypes.c_void_p)

        on_preset_switch_failed(b"preset.milk", b"load failed", user_data_ptr)

        instance._on_preset_switch_failed.assert_called_once_with(
            b"preset.milk", b"load failed"
        )

    def test_playlist_item_string_is_freed_after_decoding(self):
        item = ctypes.create_string_buffer(b"preset.milk")
        freed_pointers = []
        projectm = object.__new__(ProjectM)
        projectm.projectm_playlist = 123
        projectm.projectm_playlist_lib = SimpleNamespace(
            projectm_playlist_item=lambda _playlist, _index: ctypes.addressof(item),
            projectm_playlist_free_string=freed_pointers.append,
        )

        result = projectm._get_preset_item(2)

        self.assertEqual(result, "preset.milk")
        self.assertEqual(freed_pointers, [ctypes.addressof(item)])

    def test_diagnostics_snapshot_reports_visual_settings(self):
        def set_window_size(_instance, width_ptr, height_ptr):
            ctypes.cast(width_ptr, ctypes.POINTER(ctypes.c_size_t)).contents.value = 1920
            ctypes.cast(height_ptr, ctypes.POINTER(ctypes.c_size_t)).contents.value = 1080

        projectm = object.__new__(ProjectM)
        projectm.projectm = 123
        projectm.projectm_playlist = 456
        projectm.projectm_lib = SimpleNamespace(
            projectm_get_window_size=set_window_size,
            projectm_get_beat_sensitivity=lambda _instance: 1.25,
            projectm_get_hard_cut_enabled=lambda _instance: True,
            projectm_get_hard_cut_duration=lambda _instance: 30.0,
            projectm_get_hard_cut_sensitivity=lambda _instance: 1.5,
            projectm_get_preset_duration=lambda _instance: 60.0,
            projectm_get_soft_cut_duration=lambda _instance: 2.0,
            projectm_get_aspect_correction=lambda _instance: True,
            projectm_get_fps=lambda _instance: 59,
        )
        projectm.projectm_playlist_lib = SimpleNamespace(
            projectm_playlist_size=lambda _playlist: 12,
        )
        projectm._get_mesh_size = Mock(return_value=(64, 32))
        projectm._get_active_preset_index = Mock(return_value=4)
        projectm.get_preset_shuffle = Mock(return_value=True)
        projectm.target_fps = Mock(return_value=60)
        projectm.real_fps = 59.5
        projectm.current_preset_start = None

        snapshot = projectm.get_diagnostics_snapshot()

        self.assertEqual(snapshot["beat_sensitivity"], 1.25)
        self.assertTrue(snapshot["hard_cut_enabled"])
        self.assertEqual(snapshot["hard_cut_sensitivity"], 1.5)
        self.assertEqual(snapshot["mesh_size"], (64, 32))
        self.assertEqual(snapshot["viewport_size"], (1920, 1080))
        self.assertEqual(snapshot["playlist_index"], 4)
        self.assertEqual(snapshot["playlist_count"], 12)
        self.assertTrue(snapshot["shuffle"])


if __name__ == "__main__":
    unittest.main()
