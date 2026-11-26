import datetime as dt
import unittest
from src.official_bea_calendar_v1 import parse_bea
NOW=dt.datetime(2026,11,26,19,0,tzinfo=dt.timezone.utc)
def fixture(gdp="2026-12-23T13:30:00+00:00",pce="2026-12-23T13:30:00+00:00"):
    return {"Gross Domestic Product":{"release_dates":[gdp]},
        "Personal Income and Outlays":{"release_dates":[pce]}}
class BEAOfficialCalendarTests(unittest.TestCase):
    def test_both_utc_release_times_to_poland(self):
        e=parse_bea(fixture(),NOW)["events"]
        self.assertEqual(len(e),2)
        self.assertEqual(e[0]["release_at_poland"],"2026-12-23T14:30:00+01:00")
    def test_no_inferred_consensus_or_actual(self):
        e=parse_bea(fixture(),NOW)["events"][0]
        self.assertIsNone(e["consensus"])
        self.assertIsNone(e["actual"])
        self.assertIsNone(e["btc_reaction"])
    def test_public_domain_source_only(self):
        self.assertEqual(parse_bea(fixture(),NOW)["events"][0]["source_url"],
                         "https://apps.bea.gov/API/signup/release_dates.json")
    def test_duplicate_source_dates_dedup(self):
        r=fixture()
        r["Gross Domestic Product"]["release_dates"] *=2
        self.assertEqual(len(parse_bea(r,NOW)["events"]),2)
    def test_timezone_required(self):
        with self.assertRaises(ValueError):parse_bea(fixture(),dt.datetime(2026,11,26))
    def test_missing_series_fails_closed(self):
        with self.assertRaises(ValueError):parse_bea({"Gross Domestic Product":{"release_dates":[]}},NOW)
    def test_naive_release_fails_closed(self):
        with self.assertRaises(ValueError):parse_bea(fixture(gdp="2026-12-23T08:30:00"),NOW)
    def test_empty_window_not_no_future_events(self):
        x=parse_bea(fixture(gdp="2028-01-01T13:30:00+00:00",pce="2028-01-01T13:30:00+00:00"),NOW)
        self.assertEqual(x["status"],"no_releases_in_horizon")
    def test_no_trade(self):
        self.assertEqual(parse_bea(fixture(),NOW)["decision"],"NO_TRADE")
if __name__=="__main__":unittest.main()
