"""Retrieve actual BTCUSDT perpetual funding settlements for the evaluation period."""
import json
from urllib.parse import urlencode
from dataset import ROOT, START, END, get, stamp
def main():
 start=stamp(START)*1000;end=stamp(END)*1000; data={}
 while start<end:
  batch=json.loads(get('https://fapi.binance.com/fapi/v1/fundingRate?'+urlencode(dict(symbol='BTCUSDT',startTime=start,endTime=end-1,limit=1000))))
  if not batch:break
  for r in batch:
   t=int(r['fundingTime']);assert start<=t<end and r['symbol']=='BTCUSDT' and float(r['markPrice'])>0
   data[t]=[float(r['fundingRate']),float(r['markPrice'])]
  start=max(int(r['fundingTime']) for r in batch)+1
 expected=list(range(stamp(START),stamp(END),8*3600))
 slots=[(x+500)//1000 for x in sorted(data)]
 assert slots==expected, (len(slots),len(expected),slots[:3],slots[-3:])
 (ROOT/'funding.json').write_text(json.dumps(dict(zip(slots,(data[x] for x in sorted(data))))))
 print('verified funding settlements',len(slots))
if __name__=='__main__':main()
