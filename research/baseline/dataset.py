from datetime import date, timedelta, datetime, timezone
import urllib.request as u, concurrent.futures, zipfile, io, csv, time, hashlib, json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
D=ROOT/'archive'
D.mkdir(exist_ok=True)
START=date(2025,11,27)
END=date(2026,11,27)
WARM=START-timedelta(days=30)
def stamp(d):return int(datetime.combine(d,datetime.min.time(),timezone.utc).timestamp())
def get(url):
 for i in range(3):
  try:
   with u.urlopen(url,timeout=16) as r:return r.read()
  except OSError:
   if i==2:raise
def part(key):
 name='BTCUSDT-5m-'+key+'.zip'
 url='https://data.binance.vision/data/futures/um/'+('monthly' if len(key)==7 else 'daily')+'/klines/BTCUSDT/5m/'+name
 file=D/name
 b=file.read_bytes() if file.exists() else get(url)
 digest=get(url+'.CHECKSUM').decode().split()[0]
 assert hashlib.sha256(b).hexdigest()==digest
 file.write_bytes(b)
 with zipfile.ZipFile(io.BytesIO(b)) as z:
  rows=list(csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]))))
 out=[]
 for r in rows:
  if not r[0].isdigit(): continue
  t=int(r[0])//1000
  if not stamp(WARM)<=t<stamp(END):continue
  o,h,l,c,v,buy=map(float,(r[1],r[2],r[3],r[4],r[5],r[9]))
  assert 0<l<=min(o,c)<=max(o,c)<=h and 0<=buy<=v and int(r[6])==t*1000+299999
  out.append((t,o,h,l,c,v,buy))
 return key,digest,out
def main():
 keys=['2025-10','2025-11','2025-12']+[f'2026-{i:02d}' for i in range(1,11)]+[f'2026-11-{i:02d}' for i in range(1,27)]
 with concurrent.futures.ThreadPoolExecutor(8) as ex: parts=list(ex.map(part,keys))
 rows=sorted(row for _,_,rs in parts for row in rs)
 assert [r[0] for r in rows]==list(range(stamp(WARM),stamp(END),300))
 with open(ROOT/'bars.csv','w') as f:csv.writer(f).writerows(rows)
 (ROOT/'checksums.json').write_text(json.dumps({k:h for k,h,_ in parts},indent=2))
 print('verified',len(rows))
if __name__=='__main__':main()
