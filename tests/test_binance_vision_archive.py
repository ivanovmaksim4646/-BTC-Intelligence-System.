import csv
import datetime as dt
import io
import unittest
import zipfile
from src.binance_vision_archive import parse_archive, probe, url_for

DAY=dt.date(2026,11,20)

def archive(tf="5m",bad_header=False,gap=False):
    rows=[]
    count=4
    start=int(dt.datetime(2026,11,20,tzinfo=dt.timezone.utc).timestamp()*1000)
    for i in range(count):
        if gap and i==2:continue
        ms=start+i*300000
        rows.append([ms,100,105,95,102,12,ms+299999,0,0,0,0,0])
    filename=f"BTCUSDT-{tf}-{DAY.isoformat()}.csv"
    if bad_header:filename="unexpected.csv"
    content=io.StringIO()
    w=csv.writer(content);w.writerows(rows)
    mem=io.BytesIO()
    with zipfile.ZipFile(mem,"w",zipfile.ZIP_DEFLATED) as z:
        z.writestr(filename,content.getvalue())
    return mem.getvalue()

class VisionArchiveTests(unittest.TestCase):
    def test_expected_binance_vision_path(self):
        self.assertIn("/futures/um/daily/klines/BTCUSDT/5m/",url_for("5m",DAY))
    def test_four_valid_candles(self):
        self.assertEqual(len(parse_archive(archive(),"5m",DAY)),4)
    def test_missing_candle_rejected(self):
        with self.assertRaises(ValueError):
            parse_archive(archive(gap=True),"5m",DAY)
    def test_unexpected_zip_member_rejected(self):
        with self.assertRaises(ValueError):
            parse_archive(archive(bad_header=True),"5m",DAY)
    def test_weekly_rejected_as_incomplete_daily(self):
        with self.assertRaises(ValueError):
            parse_archive(archive("1w"),"1w",DAY)
    def test_no_live_signal_from_historical_archive(self):
        out=probe(DAY,("5m",),downloader=lambda _:archive())
        self.assertEqual(out["status"],"verified_historical")
        self.assertTrue(out["not_live_data"])
        self.assertIsNone(out["trade_signal"])
    def test_failure_is_partial(self):
        out=probe(DAY,("5m",),downloader=lambda _:b"bad zip")
        self.assertEqual(out["status"],"partial")
        self.assertEqual(out["errors"]["5m"],"BadZipFile")

if __name__=="__main__":
    unittest.main()
