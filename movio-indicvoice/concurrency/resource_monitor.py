"""
GPU/CPU/RAM resource sampler for load tests.

Uses pynvml when available; otherwise logs "GPU monitoring unavailable" gracefully.
Samples every 1 second while running.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger("concurrency.resource_monitor")


@dataclass
class ResourceSample:
    ts: float
    cpu_percent: float
    ram_mb: float
    gpu_util: float | None
    gpu_mem_mb: float | None


@dataclass
class ResourceMonitor:
    interval_sec: float = 1.0
    samples: list[ResourceSample] = field(default_factory=list)
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None
    _gpu_ok: bool = False
    _nvml = None
    _handle = None

    def _init_gpu(self) -> None:
        try:
            import pynvml

            pynvml.nvmlInit()
            self._nvml = pynvml
            self._handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            self._gpu_ok = True
            logger.info("GPU monitoring enabled via pynvml")
        except Exception as exc:  # noqa: BLE001
            self._gpu_ok = False
            logger.warning("GPU monitoring unavailable (%s)", exc)

    def _sample_once(self) -> ResourceSample:
        import psutil

        proc = psutil.Process()
        cpu = psutil.cpu_percent(interval=None)
        ram_mb = proc.memory_info().rss / (1024 * 1024)
        gpu_util = None
        gpu_mem = None
        if self._gpu_ok and self._nvml and self._handle is not None:
            try:
                util = self._nvml.nvmlDeviceGetUtilizationRates(self._handle)
                mem = self._nvml.nvmlDeviceGetMemoryInfo(self._handle)
                gpu_util = float(util.gpu)
                gpu_mem = float(mem.used) / (1024 * 1024)
            except Exception as exc:  # noqa: BLE001
                logger.debug("GPU sample failed: %s", exc)
        return ResourceSample(
            ts=time.time(),
            cpu_percent=cpu,
            ram_mb=ram_mb,
            gpu_util=gpu_util,
            gpu_mem_mb=gpu_mem,
        )

    def _loop(self) -> None:
        # Prime cpu_percent
        try:
            import psutil

            psutil.cpu_percent(interval=None)
        except Exception:  # noqa: BLE001
            pass
        while not self._stop.is_set():
            self.samples.append(self._sample_once())
            self._stop.wait(self.interval_sec)

    def start(self) -> None:
        self.samples.clear()
        self._stop.clear()
        self._init_gpu()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        if self._gpu_ok and self._nvml:
            try:
                self._nvml.nvmlShutdown()
            except Exception:  # noqa: BLE001
                pass

    def summary(self) -> dict:
        if not self.samples:
            return {
                "avg_cpu_percent": 0.0,
                "avg_ram_mb": 0.0,
                "avg_gpu_util": None,
                "avg_memory_mb": None,
                "n_samples": 0,
                "gpu_monitoring": self._gpu_ok,
            }
        gpu_utils = [s.gpu_util for s in self.samples if s.gpu_util is not None]
        gpu_mems = [s.gpu_mem_mb for s in self.samples if s.gpu_mem_mb is not None]
        return {
            "avg_cpu_percent": round(sum(s.cpu_percent for s in self.samples) / len(self.samples), 2),
            "avg_ram_mb": round(sum(s.ram_mb for s in self.samples) / len(self.samples), 2),
            "avg_gpu_util": round(sum(gpu_utils) / len(gpu_utils), 2) if gpu_utils else None,
            "avg_memory_mb": round(sum(gpu_mems) / len(gpu_mems), 2) if gpu_mems else None,
            "n_samples": len(self.samples),
            "gpu_monitoring": self._gpu_ok,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    mon = ResourceMonitor(interval_sec=1.0)
    mon.start()
    time.sleep(3)
    mon.stop()
    print(mon.summary())
