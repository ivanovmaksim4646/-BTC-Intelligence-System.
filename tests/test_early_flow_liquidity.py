import datetime as dt
import unittest
from src.report_feed import spot_persistence, okx_visible_liquidity

NOW=dt.datetime(2026,11,28,14,30,tzinfo=dt.timezone.utc)
END=int(NOW.timestamp())*1000

class TestEarlyFlowAndLiquidity(unittest.TestCase):
    def history(self, sign=1):
        return [dict(instrument="BTC-USDT",start_ms=t-300000,end_ms=t,
                     volume_reconciled=True,delta_btc_reconciled=str(sign*2),
                     volume_btc_reconciled="10",open_usdt="100",
                     close_usdt=str(100+sign))
                for t in range(END-3300000,END+1,300000)]

    def test_persistence_long_and_short(self):
        for sign,label in [(1,"LONG"),(-1,"SHORT")]:
            result=spot_persistence(self.history(sign),NOW)
            self.assertEqual(result["direction"],"WATCH "+label)
            self.assertEqual(result["price_response"],"aligned")
            self.assertIsNone(result["trade_signal"])

    def test_gap_and_conflict_withheld(self):
        rows=self.history()
        self.assertEqual(spot_persistence(rows[:-1],NOW)["status"],"unavailable")
        self.assertEqual(spot_persistence(rows+[dict(rows[-1],delta_btc_reconciled="3")],NOW)["status"],"unavailable")

    def test_book_freshness(self):
        doc=dict(source="OKX BTC-USDT-SWAP",classification="public_rest_snapshot_research_only",
                 generated_at_utc=NOW.isoformat(),book=dict(status="snapshot_only",timestamp_ms=END,
                    best_bid=100,best_ask=101,bid_walls=[dict(price=100,btc=2)],ask_walls=[dict(price=101,btc=3)]))
        result=okx_visible_liquidity(doc,None,NOW)
        self.assertEqual(result["status"],"snapshot_only")
        self.assertIsNone(result["liquidation_heatmap"])
        self.assertEqual(okx_visible_liquidity(doc,None,NOW+dt.timedelta(minutes=16))["status"],"unavailable")
