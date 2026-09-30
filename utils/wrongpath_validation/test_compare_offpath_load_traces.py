import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "bin" / "compare_offpath_load_traces.py"
spec = importlib.util.spec_from_file_location("compare_offpath_load_traces", SCRIPT)
comparison = importlib.util.module_from_spec(spec)
spec.loader.exec_module(comparison)

FIELDS = [
    "event_id", "event", "core", "cycle", "sim_time", "committed_insts", "pc",
    "onpath_observation", "map_version", "load_operand", "old_va", "va",
]


def row(event_id, event, observation, version, va, old_va="", core=0):
    return [event_id, event, core, 10 + event_id, 100 + event_id, 5, "0x400100",
            observation, version, 0, old_va, va]


class CompareOffpathLoadTracesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def write(self, name, rows):
        path = Path(self.temp.name) / name
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(FIELDS)
            writer.writerows(rows)
        return path

    def test_same_address_different_cycle_and_count(self):
        baseline = self.write("a.csv", [
            row(1, "map_insert", 1, 1, "0x1000"),
            row(2, "offpath_generate", 1, 1, "0x1000"),
        ])
        candidate = self.write("b.csv", [
            row(1, "map_insert", 1, 1, "0x1000"),
            row(2, "offpath_generate", 1, 1, "0x1000"),
            row(3, "offpath_generate", 1, 1, "0x1000"),
        ])
        a, b = comparison.read_trace(baseline), comparison.read_trace(candidate)
        result = comparison.compare(a, b)
        self.assertEqual(result["common_contexts"], 1)
        self.assertEqual(result["changed_contexts"], [])
        self.assertEqual(sum(a["offpath_vas"].values()), 1)
        self.assertEqual(sum(b["offpath_vas"].values()), 2)

    def test_changed_reused_address_in_common_context(self):
        baseline = self.write("a.csv", [
            row(1, "map_insert", 1, 1, "0x1000"),
            row(2, "offpath_generate", 1, 1, "0x1000"),
        ])
        candidate = self.write("b.csv", [
            row(1, "map_insert", 1, 1, "0x2000"),
            row(2, "offpath_generate", 1, 1, "0x2000"),
        ])
        result = comparison.compare(comparison.read_trace(baseline), comparison.read_trace(candidate))
        self.assertEqual(len(result["changed_contexts"]), 1)
        self.assertEqual(len(result["changed_onpath_contexts"]), 1)

    def test_one_run_only_context_not_counted_as_changed(self):
        baseline = self.write("a.csv", [row(1, "offpath_generate", 1, 1, "0x1000")])
        candidate = self.write("b.csv", [row(1, "offpath_generate", 2, 2, "0x2000")])
        result = comparison.compare(comparison.read_trace(baseline), comparison.read_trace(candidate))
        self.assertEqual(result["common_contexts"], 0)
        self.assertEqual(result["changed_contexts"], [])
        self.assertEqual(result["only_baseline_contexts"], 1)
        self.assertEqual(result["only_candidate_contexts"], 1)

    def test_rejects_summary_csv(self):
        path = Path(self.temp.name) / "summary.csv"
        path.write_text("core,pc,offpath_load_count,load_operand_count,distinct_reused_vas\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "not a selected-load event CSV"):
            comparison.read_trace(path)


if __name__ == "__main__":
    unittest.main()
