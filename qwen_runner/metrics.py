"""Inference-only wall time, CUDA allocator peaks and sampled process RSS."""
import threading
import time


class InferenceMetrics:
    def __init__(self, torch_module, device, poll_seconds=0.02):
        import psutil
        self.torch, self.device = torch_module, torch_module.device(device)
        self.process = psutil.Process()
        self.interval = poll_seconds
        self.done = threading.Event()
        self.result = {}

    def _sync(self):
        if self.device.type == 'cuda': self.torch.cuda.synchronize(self.device)
        elif self.device.type == 'mps': self.torch.mps.synchronize()

    def _sample(self):
        rss = self.process.memory_info().rss
        self.peak_rss = max(self.peak_rss, rss)
        if self.device.type == 'mps':
            self.peak_mps = max(self.peak_mps, self.torch.mps.current_allocated_memory())

    def _poll(self):
        while not self.done.wait(self.interval):
            try: self._sample()
            except Exception as error: self.poll_error = str(error)

    def __enter__(self):
        self._sync()
        self.start_rss = self.peak_rss = self.process.memory_info().rss
        self.peak_mps = 0
        self.poll_error = None
        self.start_allocated = self.start_reserved = None
        if self.device.type == 'cuda':
            self.start_allocated = self.torch.cuda.memory_allocated(self.device)
            self.start_reserved = self.torch.cuda.memory_reserved(self.device)
            self.torch.cuda.reset_peak_memory_stats(self.device)
        self._sample()
        self.thread = threading.Thread(target=self._poll, daemon=True)
        self.thread.start()
        self.start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        sync_error = None
        try: self._sync()
        except Exception as error: sync_error = repr(error)
        elapsed = time.perf_counter() - self.start
        self.done.set()
        self.thread.join(timeout=2)
        try: self._sample()
        except Exception as error: self.poll_error = str(error)
        self.result = {
            "inference_seconds": elapsed,
            "process_rss_baseline_bytes": self.start_rss,
            "process_rss_peak_bytes": self.peak_rss,
            "process_rss_peak_increase_bytes": self.peak_rss - self.start_rss,
            "rss_method": "sampled current-process resident set, includes loaded model; excludes other processes",
            "memory_poll_seconds": self.interval,
            "gpu_peak_allocated_bytes": None, "gpu_peak_reserved_bytes": None,
            "synchronization_error": sync_error, "memory_poll_error": self.poll_error,
        }
        if self.device.type == 'cuda':
            allocated = self.torch.cuda.max_memory_allocated(self.device)
            self.result.update(gpu_baseline_allocated_bytes=self.start_allocated,
                               gpu_baseline_reserved_bytes=self.start_reserved,
                               gpu_peak_allocated_bytes=allocated,
                               gpu_peak_allocated_increase_bytes=allocated - self.start_allocated,
                               gpu_peak_reserved_bytes=self.torch.cuda.max_memory_reserved(self.device),
                               gpu_memory_method='PyTorch allocator peaks for the selected CUDA device; not total device VRAM')
        elif self.device.type == 'mps':
            self.result.update(mps_sampled_peak_allocated_bytes=self.peak_mps,
                               gpu_memory_method='Sampled PyTorch MPS allocated memory; unified memory overlaps RSS')
        if sync_error and exc_type is None: raise RuntimeError(sync_error)
        return False
