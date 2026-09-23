import unittest

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


if __name__ == "__main__":
    unittest.main()
