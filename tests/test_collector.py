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


    def test_spot_h4_backfill_rebuilds_without_double_counting(self):
        from unittest.mock import patch

        start, end = 0, 14400
        ohlc = [[i * 300, "0", "0", "0", "0", "0", "1"] for i in range(48)]
        trades = [
            ["60000", "1", i * 300 + 1, "b" if i % 2 else "s", "l", "", str(i)]
            for i in range(48)
        ]
        pages = [
            {"result": {"XBTUSD": trades[:25], "last": str(25 * 300 * 1_000_000_000)}},
            {"result": {"XBTUSD": [trades[24]] + trades[25:] +
                        [["60000", "1", end + 1, "b", "l", "", "later"]],
                        "last": str((end + 1) * 1_000_000_000)}},
        ]
        with patch.object(collector, "public", side_effect=pages) as api:
            rebuilt, count = collector.backfill_spot_closed_window(start, end, ohlc)
        self.assertEqual(count, 2)
        self.assertEqual(sum(row["count"] for row in rebuilt.values()), 48)
        result = collector.aggregate_spot(rebuilt, ohlc, 0, end)["H4"]
        self.assertEqual(result["coverage"], "complete")
        self.assertEqual(result["total_volume"], 48)
        self.assertEqual(api.call_count, 2)

    def test_spot_h4_backfill_rejects_volume_mismatch(self):
        from unittest.mock import patch

        ohlc = [[i * 300, "0", "0", "0", "0", "0", "1"] for i in range(48)]
        page = {"result": {
            "XBTUSD": [["60000", "1", 1, "b", "l", "", "t1"],
                       ["60000", "1", 14401, "b", "l", "", "later"]],
            "last": str(14401 * 1_000_000_000)
        }}
        with patch.object(collector, "public", return_value=page):
            with self.assertRaisesRegex(RuntimeError, "cannot verify volume"):
                collector.backfill_spot_closed_window(0, 14400, ohlc)

    def test_spot_h4_backfill_rejects_stalled_pagination(self):
        from unittest.mock import patch

        ohlc = [[i * 300, "0", "0", "0", "0", "0", "1"] for i in range(48)]
        page = {"result": {"XBTUSD": [], "last": "-1"}}
        with patch.object(collector, "public", return_value=page):
            with self.assertRaisesRegex(RuntimeError, "cursor stalled"):
                collector.backfill_spot_closed_window(0, 14400, ohlc)


if __name__ == "__main__":
    unittest.main()
