import unittest
from types import SimpleNamespace

from qwen_runner.system import probe_runtime_capabilities


class RuntimeCapabilityTests(unittest.TestCase):
    def test_cpu_runtime_is_ready_with_supported_settings(self):
        report = probe_runtime_capabilities(device="cpu", dtype="float32", offload="none")

        self.assertEqual(report["selected_device"]["type"], "cpu")
        self.assertTrue(report["selected_device"]["available"])
        self.assertTrue(report["production_backend"]["ready"])
        self.assertIn("torch", report)
        self.assertIn("cuda", report)

    def test_cpu_runtime_rejects_cuda_style_settings(self):
        report = probe_runtime_capabilities(device="cpu", dtype="bfloat16", offload="model")

        self.assertFalse(report["production_backend"]["ready"])
        self.assertIn("dtype=float32", report["production_backend"]["message"])

    def test_invalid_device_is_reported_without_raising(self):
        report = probe_runtime_capabilities(device="not-a-device", dtype="float32", offload="none")

        self.assertFalse(report["production_backend"]["ready"])
        self.assertIn("Invalid device", report["production_backend"]["message"])

    def test_cuda_inventory_reports_live_memory_and_host_capacity(self):
        class FakeCuda:
            @staticmethod
            def is_available(): return True
            @staticmethod
            def device_count(): return 1
            @staticmethod
            def get_device_properties(index):
                self.assertEqual(index, 0)
                return SimpleNamespace(
                    name="Test GPU", total_memory=24 * 1024**3, major=8, minor=6,
                    multi_processor_count=84,
                )
            @staticmethod
            def mem_get_info(index): return (18 * 1024**3, 24 * 1024**3)
            @staticmethod
            def memory_allocated(index): return 2 * 1024**3
            @staticmethod
            def memory_reserved(index): return 3 * 1024**3
            @staticmethod
            def is_bf16_supported(): return True

        class FakeTorch:
            __version__ = "9.9.0"
            version = SimpleNamespace(cuda="12.6")
            cuda = FakeCuda()
            backends = SimpleNamespace(mps=SimpleNamespace(is_available=lambda: False))

            @staticmethod
            def device(value):
                if value != "cuda:0":
                    raise ValueError(value)
                return SimpleNamespace(type="cuda", index=0)

        report = probe_runtime_capabilities(
            device="cuda:0", dtype="bfloat16", offload="model", torch_module=FakeTorch()
        )

        gpu = report["cuda"]["devices"][0]
        self.assertEqual(gpu["name"], "Test GPU")
        self.assertEqual(gpu["free_memory_bytes"], 18 * 1024**3)
        self.assertEqual(gpu["used_memory_bytes"], 6 * 1024**3)
        self.assertEqual(gpu["process_reserved_bytes"], 3 * 1024**3)
        self.assertEqual(report["selected_device"]["free_memory_bytes"], 18 * 1024**3)
        self.assertEqual(report["torch"]["cuda_runtime"], "12.6")
        self.assertIn("cpu", report["host"])
        self.assertIn("memory", report["host"])
        self.assertTrue(report["production_backend"]["ready"])


if __name__ == "__main__":
    unittest.main()
