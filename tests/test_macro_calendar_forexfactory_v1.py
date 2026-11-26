import datetime as dt
import json
import unittest
from src.macro_calendar_forexfactory_v1 import parse_weekly
NOW=dt.datetime(2026,11,26,19,tzinfo=dt.timezone.utc)
def row(**kw):
    a={"title":"Core PCE Price Index m/m","country":"USD",
       "date":"2026-11-25T08:30:00-05:00","impact":"High",
       "forecast":"0.3%","previous":"0.3%"}
    a.update(kw)
    return a
class ForexFactoryFeedTests(unittest.TestCase):
    def test_timezone_and_provenance(self):
        e=parse_weekly(json.dumps([row()]),NOW)["events"][0]
        self.assertEqual(e["release_at_poland"],"2026-11-25T14:30:00+01:00")
        self.assertEqual(e["forecast"],"0.3%")
        self.assertIsNone(e["actual"])
    def test_no_forecast_stays_null(self):
        self.assertIsNone(parse_weekly([row(forecast="")],NOW)["events"][0]["forecast"])
    def test_naive_date_rejected(self):
        with self.assertRaises(ValueError):parse_weekly([row(date="2026-11-25T08:30:00")],NOW)
    def test_future_out_of_week_rejected(self):
        with self.assertRaises(ValueError):parse_weekly([row(date="2026-12-20T08:30:00-05:00")],NOW)
    def test_invalid_impact_rejected(self):
        with self.assertRaises(ValueError):parse_weekly([row(impact="Critical")],NOW)
    def test_empty_feed_rejected(self):
        with self.assertRaises(ValueError):parse_weekly([],NOW)
    def test_no_trade_even_with_high_impact(self):
        a=parse_weekly([row()],NOW)
        self.assertEqual(a["decision"],"NO_TRADE")
        self.assertFalse(a["actuals_available"])
if __name__=="__main__":unittest.main()
