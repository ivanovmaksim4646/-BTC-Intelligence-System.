import importlib.util
import pathlib
import unittest

MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "src" / "collector.py"
SPEC = importlib.util.spec_from_file_location("collector", MODULE_PATH)
collector = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(collector)


class CollectorTests(unittest.TestCase):
    def test_error_classes(self):
        self.assertEqual(collector.classify_error(OSError("proxy tunnel failed")), "proxy")
        self.assertEqual(collector.classify_error(OSError("name resolution failed")), "DNS")

    def test_futures_aggregation_exact_window(self):
        now = 1_800
        result = {
            "timestamp": [0, 300, 600, 900, 1200, 1500],
            "data": [[2, 1], [3, 1], [1, 1], [4, 2], [2, 3], [5, 1]],
        }
        value = collector.aggregate_futures(result, now)["M15"]
        self.assertEqual(value["window_start_utc"], collector.iso(900))
        self.assertEqual(value["buy_volume"], 11)
        self.assertEqual(value["sell_volume"], 6)
        self.assertEqual(value["delta"], 5)
        self.assertEqual(value["coverage"], "complete")

    def test_futures_aggregation_kraken_dict_shape(self):
        now = 900
        result = {
            "timestamp": [0, 300, 600],
            "data": {"buy_volume": ["2", "3", "4"], "sell_volume": ["1", "1", "2"]},
        }
        value = collector.aggregate_futures(result, now)["M15"]
        self.assertEqual(value["buy_volume"], 9)
        self.assertEqual(value["sell_volume"], 4)
        self.assertEqual(value["coverage"], "complete")

    def test_spot_coverage_rejects_missing_bars(self):
        now = 1_800
        buckets = {1500: {"buy": 1.0, "sell": 0.0, "count": 1}}
        ohlc = [[1500, "0", "0", "0", "0", "0", "1"]]
        value = collector.aggregate_spot(buckets, ohlc, 0, now)["M15"]
        self.assertEqual(value["coverage"], "partial")


if __name__ == "__main__":
    unittest.main()
