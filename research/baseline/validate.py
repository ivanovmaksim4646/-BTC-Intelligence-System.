import csv,json
from bisect import bisect_left
from datetime import timedelta
from replay import Bar,backtest,stamp_start,stamp_end,utc,ROOT
from original_annual import download
rows=[Bar(int(r[0]),*map(float,r[1:])) for r in csv.reader(open(ROOT/'bars.csv'))]
timestamps=[b.t for b in rows]
def archive_page(tf,cursor):
 idx=bisect_left(timestamps,cursor//1000)
 return [[b.t*1000,b.o,b.h,b.l,b.c,None,None,None,"1"] for b in reversed(rows[max(0,idx-100):idx])]
baseline=download('5m',stamp_start,stamp_end,archive_page)
assert len(baseline)==105120
funding={int(k):v for k,v in json.loads((ROOT/'funding.json').read_text()).items()}
cut=stamp_start+125*86400
prefix=backtest(rows[:bisect_left(timestamps,cut)],funding,125*288)
full=list(csv.DictReader(open(ROOT/'trades.csv')))
tested=0
for name,v in prefix.items():
 a=[(x['entry_utc'],x['exit_utc'],x['outcome'],x['R']) for x in v.rows]
 b=[(x['entry_utc'],x['exit_utc'],x['outcome'],float(x['R'])) for x in full if x['model']==name and x['exit_utc']<=utc(cut)]
 assert a==b,(name,len(a),len(b))
 tested+=len(a)
for x in full:
 assert float(x['planned_RR'])>=2 and x['setup_utc']<x['entry_utc']<x['exit_utc']
print('Original GitHub annual coverage validator:',len(baseline),'M5. Prefix equivalence, 125 days:',tested,'closed positions. RR checks:',len(full))
