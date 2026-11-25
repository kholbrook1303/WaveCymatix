import importlib.util
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "visual_preset_benchmark.py"
)
SPEC = importlib.util.spec_from_file_location("visual_preset_benchmark", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


class VisualPresetBenchmarkTests(unittest.TestCase):
    def test_profile_id_is_stable_and_changes_with_resolution(self):
        args = Namespace(
            windowed=False,
            width=1920,
            height=1080,
            mesh_x=64,
            mesh_y=32,
            duration=10.0,
            warmup=1.0,
            target_fps=30.0,
        )

        profile = benchmark.build_profile(args)
        profile_id = benchmark._stable_id(profile)
        self.assertEqual(profile_id, benchmark._stable_id(profile))

        args.width = 1280
        self.assertNotEqual(profile_id, benchmark._stable_id(benchmark.build_profile(args)))

    def test_percentile_uses_nearest_rank(self):
        self.assertEqual(benchmark.percentile([5.0, 1.0, 4.0, 2.0, 3.0], 50), 3.0)
        self.assertEqual(benchmark.percentile([5.0, 1.0, 4.0, 2.0, 3.0], 95), 5.0)
        with self.assertRaises(ValueError):
            benchmark.percentile([], 95)

    def test_windows_library_loading_uses_global_ctypes_module(self):
        with tempfile.TemporaryDirectory() as directory:
            app_root = Path(directory)
            runtime_dir = app_root / "runtime" / "artifacts"
            runtime_dir.mkdir(parents=True)
            library_path = runtime_dir / "projectM-4.dll"
            library_path.touch()

            renderer = object.__new__(benchmark.BenchmarkRenderer)
            renderer.app_root = app_root
            expected_library = object()

            with (
                patch.object(benchmark.os, "name", "nt"),
                patch.object(benchmark.ctypes, "CDLL", return_value=expected_library),
            ):
                library = renderer._load_library("projectM-4", "projectM-4.dll")

        self.assertIs(library, expected_library)

    def test_passed_lower_tier_skips_higher_tier_and_same_machine_resumes(self):
        entry = {"benchmarkResults": {
            "profile": {
                "tiers": {
                    "low": {"runs": [{"machineId": "gpu-a", "status": "pass"}]}
                }
            }
        }}

        self.assertFalse(
            benchmark.preset_needs_benchmark(entry, "medium", "profile", "gpu-b")
        )
        self.assertFalse(
            benchmark.preset_needs_benchmark(entry, "low", "profile", "gpu-a")
        )
        self.assertTrue(
            benchmark.preset_needs_benchmark(entry, "low", "profile", "gpu-b")
        )
        self.assertTrue(
            benchmark.preset_needs_benchmark(
                entry, "low", "profile", "gpu-a", force=True
            )
        )

    def test_classification_waits_for_lower_tiers_then_sets_minimum(self):
        entry = {}
        profile = {
            "fullscreen": True,
            "width": 1920,
            "height": 1080,
        }

        benchmark.record_result(
            entry,
            "profile",
            profile,
            "very_low",
            {"machineId": "gpu-a", "status": "fail"},
        )
        self.assertIsNone(entry.get("minimumTierLevel"))

        benchmark.record_result(
            entry,
            "profile",
            profile,
            "low",
            {"machineId": "gpu-b", "status": "pass"},
        )
        self.assertEqual(entry["minimumTierLevel"], 1)
        self.assertEqual(entry["benchmarkStatus"], "classified")

    def test_mixed_results_clear_automatic_classification(self):
        entry = {}
        profile = {"width": 1920, "height": 1080}
        benchmark.record_result(
            entry,
            "profile",
            profile,
            "very_low",
            {"machineId": "gpu-a", "status": "pass"},
        )
        benchmark.record_result(
            entry,
            "profile",
            profile,
            "very_low",
            {"machineId": "gpu-b", "status": "fail"},
        )
        self.assertIsNone(entry["minimumTierLevel"])
        self.assertEqual(entry["benchmarkStatus"], "mixed")


if __name__ == "__main__":
    unittest.main()
