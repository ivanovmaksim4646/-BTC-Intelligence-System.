import datetime as dt
import io
import json
import unittest
from src.telegram_delivery_v1 import candidate,send

class TelegramDeliveryTests(unittest.TestCase):
    def fixture(self):
        now=dt.datetime(2026,11,28,15,35,tzinfo=dt.timezone.utc)
        end=int(now.timestamp()*1000)
        return now,{"generated_at_utc":now.isoformat(),"okx_spot_persistence":{
            "source":"OKX BTC-USDT","status":"observed","coverage":"volume_reconciled_not_sequence_certified",
            "direction":"WATCH LONG","end_ms":end,"blocks":[
                {"end_ms":end-(3-i)*900000,"pressure":.2,"delta_btc":2,"price_return":.001}
                for i in range(4)]}}
    def test_candidate(self):
        now,doc=self.fixture()
        self.assertIn("WATCH LONG",candidate(doc,now)["text"])
        self.assertIsNone(candidate(doc,now+dt.timedelta(minutes=8)))
    def test_missing_block(self):
        now,doc=self.fixture()
        doc["okx_spot_persistence"]["blocks"].pop()
        self.assertIsNone(candidate(doc,now))
    def test_send_mock(self):
        def fake(req,timeout):
            self.assertEqual(json.loads(req.data)["chat_id"],"123")
            self.assertEqual(timeout,10)
            return io.BytesIO(b'{"ok":true,"result":{"message_id":42}}')
        self.assertEqual(send("123:dummy","123","TEST",fake),42)
    def test_bad_provider_response(self):
        with self.assertRaises(ValueError):
            send("123:dummy","123","TEST",lambda *a,**k:io.BytesIO(b'{"ok":false}'))
