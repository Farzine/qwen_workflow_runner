import threading
import time
import unittest

from qwen_runner.config import Config
from qwen_runner.resources import PipelineManager, normalize_device_id, pipeline_compatibility_key


class FakeBackend:
    instances = []

    def __init__(self, config):
        self.config = config
        self.metadata = {"pipeline": "FakePipeline"}
        self.load_calls = 0
        self.prepare_calls = []
        self.unload_calls = 0
        type(self).instances.append(self)

    def load(self):
        self.load_calls += 1
        return self

    def prepare_for_config(self, config):
        self.config = config
        self.prepare_calls.append((config.model.lora_path, config.model.lora_scale))

    def unload(self):
        self.unload_calls += 1


class BrokenBackend(FakeBackend):
    def load(self):
        raise RuntimeError("load failed")


class FailingUnloadBackend(FakeBackend):
    def unload(self):
        self.unload_calls += 1
        raise RuntimeError("unload failed")


class PipelineManagerTests(unittest.TestCase):
    def setUp(self):
        FakeBackend.instances = []
        BrokenBackend.instances = []
        self.manager = PipelineManager()

    def tearDown(self):
        self.manager.shutdown()

    @staticmethod
    def config(device="cpu", source="org/model", lora=None, scale=1.0):
        config = Config()
        config.runtime.device = device
        config.runtime.dtype = "float32" if device == "cpu" else "bfloat16"
        config.runtime.offload = "none" if device == "cpu" else "model"
        config.model.source = source
        config.model.lora_path = lora
        config.model.lora_scale = scale
        return config

    def test_generation_and_lora_changes_reuse_compatible_pipeline(self):
        first_config = self.config()
        with self.manager.acquire(first_config, FakeBackend) as first:
            backend = first.backend
            self.assertFalse(first.reused)

        second_config = self.config(lora="style.safetensors", scale=0.6)
        second_config.generation.steps = 99
        with self.manager.acquire(second_config, FakeBackend) as second:
            self.assertTrue(second.reused)
            self.assertIs(second.backend, backend)
            self.assertEqual(backend.prepare_calls, [("style.safetensors", 0.6)])

        snapshot = self.manager.snapshot()
        self.assertEqual(snapshot["policy"], "one_pipeline_per_device")
        self.assertEqual(snapshot["slots"][0]["load_count"], 1)
        self.assertEqual(snapshot["slots"][0]["reuse_count"], 1)

    def test_model_change_replaces_only_that_device_slot(self):
        with self.manager.acquire(self.config("cuda:0", "org/a"), FakeBackend) as lease:
            first = lease.backend
        with self.manager.acquire(self.config("cuda:1", "org/a"), FakeBackend) as lease:
            other_device = lease.backend
        with self.manager.acquire(self.config("cuda:0", "org/b"), FakeBackend) as lease:
            replacement = lease.backend

        self.assertIsNot(first, replacement)
        self.assertEqual(first.unload_calls, 1)
        self.assertEqual(other_device.unload_calls, 0)
        self.assertEqual(len(self.manager.snapshot()["slots"]), 2)

    def test_second_lease_waits_until_active_job_releases(self):
        config = self.config()
        entered = threading.Event()
        acquired = threading.Event()

        def contender():
            entered.set()
            with self.manager.acquire(config, FakeBackend) as lease:
                self.assertTrue(lease.reused)
                acquired.set()

        with self.manager.acquire(config, FakeBackend):
            thread = threading.Thread(target=contender)
            thread.start()
            entered.wait(1)
            time.sleep(0.03)
            self.assertFalse(acquired.is_set())
        thread.join(1)
        self.assertTrue(acquired.is_set())

    def test_failed_replacement_leaves_recoverable_empty_slot(self):
        config = self.config(source="org/broken")
        with self.assertRaisesRegex(RuntimeError, "load failed"):
            self.manager.acquire(config, BrokenBackend)
        snapshot = self.manager.snapshot()["slots"][0]
        self.assertEqual(snapshot["state"], "error")
        self.assertEqual(snapshot["active_leases"], 0)
        with self.manager.acquire(config, FakeBackend) as lease:
            self.assertFalse(lease.reused)

    def test_shutdown_unloads_and_rejects_new_work(self):
        config = self.config()
        with self.manager.acquire(config, FakeBackend) as lease:
            backend = lease.backend
        self.manager.shutdown()
        self.assertEqual(backend.unload_calls, 1)
        self.assertFalse(self.manager.snapshot()["accepting_jobs"])
        with self.assertRaisesRegex(RuntimeError, "shutting down"):
            self.manager.acquire(config, FakeBackend)

    def test_shutdown_records_unload_error_and_continues_other_slots(self):
        with self.manager.acquire(self.config("cuda:0"), FailingUnloadBackend):
            pass
        with self.manager.acquire(self.config("cuda:1"), FakeBackend) as second:
            healthy = second.backend
        self.manager.shutdown()
        slots = {slot["device"]: slot for slot in self.manager.snapshot()["slots"]}
        self.assertEqual(slots["cuda:0"]["state"], "error")
        self.assertIn("unload failed", slots["cuda:0"]["last_error"])
        self.assertEqual(healthy.unload_calls, 1)

    def test_compatibility_key_excludes_generation_and_lora(self):
        first = self.config(lora="a.safetensors", scale=0.2)
        second = self.config(lora="b.safetensors", scale=1.8)
        second.generation.steps = 123
        self.assertEqual(
            pipeline_compatibility_key(first, FakeBackend),
            pipeline_compatibility_key(second, FakeBackend),
        )
        second.runtime.dtype = "bfloat16"
        self.assertNotEqual(
            pipeline_compatibility_key(first, FakeBackend),
            pipeline_compatibility_key(second, FakeBackend),
        )
        self.assertEqual(normalize_device_id("CUDA"), "cuda:0")


if __name__ == "__main__":
    unittest.main()
