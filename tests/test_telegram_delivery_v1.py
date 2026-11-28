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
        self.assertTrue(candidate(doc,now)["text"].startswith("📊 АНАЛІТИКА"))
        self.assertNotIn("ТОРГОВИЙ СИГНАЛ",candidate(doc,now)["text"])
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


    def test_paper_only_admitted_and_net_rr(self):
        from src.telegram_delivery_v1 import paper_candidate
        now,_=self.fixture()
        start=int(now.timestamp())+300
        row={"source":"OKX BTC-USDT-SWAP","paper_only":True,"status":"pending",
             "direction":"long","id":"a"*24,"issued_at_utc":now.isoformat(),
             "eligible_from":start,"expires_at":start+900,"entry":60000,
             "stop_loss":59400,"take_profit":61800,"cost_bps":14}
        msg=paper_candidate(row,now)["text"]
        self.assertTrue(msg.startswith("🚨 ТОРГОВИЙ СИГНАЛ 🚨\n🟢 BTC PAPER LONG"))
        self.assertIn("Entry:",msg)
        self.assertIn("SL:",msg)
        self.assertIn("TP:",msg)
        short=dict(row,direction="short",stop_loss=60600,take_profit=58200)
        self.assertTrue(paper_candidate(short,now)["text"].startswith("🚨 ТОРГОВИЙ СИГНАЛ 🚨\n🔴 BTC PAPER SHORT"))
        self.assertIsNone(paper_candidate(dict(row,status="expired"),now))
        self.assertIsNone(paper_candidate(dict(row,paper_only=False),now))
        self.assertIsNone(paper_candidate(dict(row,take_profit=60600),now))
        self.assertIsNone(paper_candidate(row,now+dt.timedelta(minutes=8)))
