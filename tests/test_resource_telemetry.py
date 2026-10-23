from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from awcc_linux.resource_telemetry import ResourceReader


class ResourceTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.proc = self.root / "proc"
        self.sys = self.root / "sys"
        self.proc.mkdir()
        self.sys.mkdir()
        self.reader = ResourceReader(self.proc, self.sys)

    def write(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_cpu_percent_needs_two_samples_and_does_not_double_count_guests(self):
        self.write(self.proc / "stat", "cpu 100 0 0 900 0 0 0 0 1000 0\n")
        self.assertIsNone(self.reader._cpu_percent())
        self.write(self.proc / "stat", "cpu 150 0 0 950 0 0 0 0 2000 0\n")
        self.assertEqual(self.reader._cpu_percent(), 50)
        self.assertIsNone(self.reader._cpu_percent())  # No new interval.

    def test_reset_or_malformed_cpu_counters_do_not_fabricate_load(self):
        self.write(self.proc / "stat", "cpu 100 0 0 900\n")
        self.reader._cpu_percent()
        self.write(self.proc / "stat", "cpu 10 0 0 90\n")
        self.assertIsNone(self.reader._cpu_percent())
        self.write(self.proc / "stat", "cpu invalid\n")
        self.assertIsNone(self.reader._cpu_percent())
        self.write(self.proc / "stat", "cpu 20 0 0 180\n")
        self.assertIsNone(self.reader._cpu_percent())
        self.write(self.proc / "stat", "cpu 30 0 0 270\n")
        self.assertEqual(self.reader._cpu_percent(), 10)

    def test_iowait_is_idle(self):
        self.write(self.proc / "stat", "cpu 100 0 0 900 0\n")
        self.reader._cpu_percent()
        self.write(self.proc / "stat", "cpu 110 0 0 900 90\n")
        self.assertEqual(self.reader._cpu_percent(), 10)

    def test_cpu_frequency_averages_valid_logical_threads_in_mhz(self):
        for index, value in enumerate(("2000000", "3000000", "N/A", "0")):
            self.write(self.sys / f"devices/system/cpu/cpu{index}/cpufreq/scaling_cur_freq", value)
        self.assertEqual(self.reader._cpu_mhz(), 2500)

    def test_cpu_frequency_can_fallback_to_cpuinfo(self):
        self.write(self.proc / "cpuinfo", "cpu MHz : 2100.5\ncpu MHz : nan\ncpu MHz : 2300.5\n")
        self.assertEqual(self.reader._cpu_mhz(), 2200.5)

    def test_ram_uses_available_not_just_free_and_converts_kib_to_bytes(self):
        self.write(self.proc / "meminfo", "MemTotal: 16000 kB\nMemAvailable: 6000 kB\nMemFree: 1000 kB\nCached: 5000 kB\n")
        self.assertEqual(self.reader._memory(), (10000 * 1024, 16000 * 1024))

    def test_missing_or_invalid_available_memory_is_unknown(self):
        for content, expected in (
            ("MemTotal: 16000 kB\n", (None, 16000 * 1024)),
            ("MemTotal: 16000 kB\nMemAvailable: 18000 kB\n", (None, 16000 * 1024)),
            ("MemTotal: 0 kB\n", (None, None)),
            ("MemTotal: -1 kB\n", (None, None)),
        ):
            self.write(self.proc / "meminfo", content)
            self.assertEqual(self.reader._memory(), expected)

    def test_gpu_query_reads_graphics_clock_and_utilization_only(self):
        with patch("awcc_linux.resource_telemetry.shutil.which", return_value="/usr/bin/nvidia-smi"), patch(
            "awcc_linux.resource_telemetry.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, "210, 0\n", ""),
        ) as run:
            self.assertEqual(self.reader._gpu(), (210, 0))
        self.assertEqual(run.call_args.args[0], ["nvidia-smi", "--query-gpu=clocks.current.graphics,utilization.gpu", "--format=csv,noheader,nounits", "--id=0"])
        self.assertEqual(run.call_args.kwargs["timeout"], 2)

    def test_bad_gpu_fields_are_independently_unknown(self):
        with patch("awcc_linux.resource_telemetry.shutil.which", return_value="nvidia-smi"), patch(
            "awcc_linux.resource_telemetry.subprocess.run",
        ) as run:
            for output, expected in (("N/A, 42", (None, 42)), ("1500, nan", (1500, None)), ("inf, 101", (None, None)), ("bad output", (None, None)), ("100, 10\n200, 20", (None, None))):
                run.return_value = subprocess.CompletedProcess([], 0, output, "")
                self.assertEqual(self.reader._gpu(), expected)

    def test_gpu_failure_does_not_hide_cpu_or_memory(self):
        self.write(self.proc / "cpuinfo", "cpu MHz : 2100\n")
        self.write(self.proc / "meminfo", "MemTotal: 16000 kB\nMemAvailable: 6000 kB\n")
        with patch("awcc_linux.resource_telemetry.shutil.which", return_value="nvidia-smi"), patch(
            "awcc_linux.resource_telemetry.subprocess.run", side_effect=subprocess.TimeoutExpired("nvidia-smi", 2),
        ):
            metrics = self.reader.read()
        self.assertEqual(metrics.cpu_mhz, 2100)
        self.assertEqual(metrics.ram_used_bytes, 10000 * 1024)
        self.assertIsNone(metrics.gpu_mhz)
        self.assertIsNone(metrics.gpu_percent)

    def test_missing_resource_files_and_gpu_degrade_to_unknown(self):
        with patch("awcc_linux.resource_telemetry.shutil.which", return_value=None):
            metrics = self.reader.read()
        self.assertTrue(all(getattr(metrics, key) is None for key in metrics.__dataclass_fields__))
