import unittest

from llm_top_tk.analyzer import local_analysis, summary
from llm_top_tk.collectors import AlertManager, Snapshot, human_bytes


class MonitorTests(unittest.TestCase):
    def test_human_bytes(self):
        self.assertEqual(human_bytes(1536), "1.5 KiB")

    def test_alerts(self):
        snap = Snapshot(0, cpu=96, memory=92, per_cpu=[10, 99])
        components = [alert["component"] for alert in AlertManager.check(snap)]
        self.assertIn("CPU", components)
        self.assertIn("Memory", components)

    def test_local_analysis_names_busy_process(self):
        snap = Snapshot(0, cpu=91, processes=[{"name": "python", "cpu": 88, "memory": 4}])
        self.assertIn("python", local_analysis(snap))
        self.assertIn("CPU avg", summary(snap))


if __name__ == "__main__":
    unittest.main()
