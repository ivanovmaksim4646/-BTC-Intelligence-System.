"""Bounded public OKX trades-all smoke test; observations only, never signals."""
import asyncio,json,time
from decimal import Decimal
from pathlib import Path
import websockets
from src.okx_rest_pagination_probe import request
from src.okx_flow_reconcile import reconcile
INST=("BTC-USDT","BTC-USDT-SWAP")
M5=300000
class Buckets:
    def __init__(self,start,end):
        self.start,self.end=start,end
        self.ids={i:set() for i in INST}
        self.totals={i:{"buy":Decimal(0),"sell":Decimal(0)} for i in INST}
        self.before=set();self.after=set()
    def add(self,r):
        i=r["instId"];t=int(r["ts"]);s=r["side"];n=Decimal(r["sz"]);tid=str(r["tradeId"])
        if i not in INST or s not in ("buy","sell") or not n.is_finite() or n<=0:raise ValueError("invalid trade")
        if t<self.start:self.before.add(i)
        if t>=self.end:self.after.add(i)
        if not self.start<=t<self.end:return
        if tid in self.ids[i]:return
        self.ids[i].add(tid);self.totals[i][s]+=n
    def observations(self):
        for i in INST:
            a=self.totals[i]
            yield {"instrument":i,"start_ms":self.start,"end_ms":self.end,"records":len(self.ids[i]),"both_time_boundaries_observed":i in self.before and i in self.after,"observed_buy_native":str(a["buy"]),"observed_sell_native":str(a["sell"]),"observed_delta_native":str(a["buy"]-a["sell"]),"unit":"BTC" if i=="BTC-USDT" else "contracts","complete_delta_btc":None,"complete_cvd_btc":None,"completeness_verified":False}
async def capture():
    # Wait for the NEXT complete M5 interval after subscribing.
    start=(int(time.time()*1000)//M5+1)*M5
    if start-int(time.time()*1000)<15000:start+=M5
    end=start+M5; b=Buckets(start,end); ack=set()
    async with websockets.connect("wss://ws.okx.com:443/ws/v5/business",open_timeout=20,max_size=2**22) as ws:
        await ws.send(json.dumps({"op":"subscribe","args":[{"channel":"trades-all","instId":i} for i in INST]}))
        while time.time()*1000<end+20000:
            try: raw=await asyncio.wait_for(ws.recv(),timeout=15)
            except asyncio.TimeoutError:
                await ws.send("ping");continue
            if raw=="pong":continue
            m=json.loads(raw)
            if m.get("event")=="error":raise RuntimeError(str(m))
            if m.get("event")=="subscribe":
                if time.time()*1000>=start:raise RuntimeError("late subscription")
                ack.add(m["arg"]["instId"]);continue
            if m.get("event")=="notice":raise RuntimeError("connection notice")
            if m.get("arg",{}).get("channel")=="trades-all":
                for r in m.get("data",[]):b.add(r)
        if ack!=set(INST):raise RuntimeError("missing subscription ack")
    results=[]
    for r in b.observations():
        i=r["instrument"]; candles=request("market/candles",{"instId":i,"bar":"5m","limit":"10"})
        meta=request("public/instruments",{"instType":"SWAP","instId":i}) if i.endswith("SWAP") else []
        results.append(reconcile(r,candles,meta))
    out={"classification":"websocket_smoke_research_only","results":results,"start_ms":start,"end_ms":end,"trade_signal":None}
    Path("data").mkdir(exist_ok=True)
    Path("data/BTC-okx-ws-smoke.json").write_text(json.dumps(out,indent=2))
    print(json.dumps(out),flush=True)
    if not all(r.get("volume_reconciled") is True for r in results):raise RuntimeError("volume reconciliation failed")
if __name__=="__main__":asyncio.run(capture())
