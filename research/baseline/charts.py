"""First fill in each base configuration, chronological rather than outcome selection."""
import csv
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as md
from matplotlib.patches import Rectangle
from matplotlib.backends.backend_pdf import PdfPages
import pandas as pd
ROOT=Path(__file__).resolve().parent
PL=ZoneInfo('Europe/Warsaw')
bars=pd.read_csv(ROOT/'bars.csv',header=None,names=['t','o','h','l','c','v','buy'])
report={'QM_M15':'ТС 1 · QM + M15 Shift','OF_M5_base':'ТС 2 · OF + M5 Shift','OF_H1_base':'ТС 2 · OF + H1 Shift + M5','OF_H4_base':'ТС 2 · OF + H4 Shift + M5'}
rows=list(csv.DictReader(open(ROOT/'trades.csv')))
def local(t):return datetime.fromtimestamp(t,timezone.utc).astimezone(PL)
def timestamp(s):return int(datetime.fromisoformat(s).timestamp())
with PdfPages(ROOT/'BTC-entries-365d.pdf') as pdf:
 for k,title in report.items():
  r=next(x for x in rows if x['model']==k)
  side='LONG' if r['d']=='1' else 'SHORT'
  a=timestamp(r['entry_utc']); b=timestamp(r['exit_utc']); s=timestamp(r['setup_utc'])
  window=bars[bars.t.between(min(a-3600,s-1800),b+1200)]
  fig,ax=plt.subplots(figsize=(10.3,5.8));fig.subplots_adjust(left=.105,right=.965,bottom=.19,top=.80)
  fig.text(.105,.945,title,fontsize=19,weight='bold',color='#17354a')
  fig.text(.105,.886,f"{side}   |   {local(a):%d.%m.%Y %H:%M} за Варшавою   |   {float(r['R']):+.2f}R   |   перший вхід за період",fontsize=12)
  ax.axvspan(local(a),local(b),color='#dce9f4',alpha=.33)
  for v in window.itertuples():
   t=md.date2num(local(v.t)); w=3.4/1440; color='#087c70' if v.c>=v.o else '#b1484d'
   ax.vlines(t,v.l,v.h,color,linewidth=.9);ax.add_patch(Rectangle((t-w/2,min(v.o,v.c)),w,max(abs(v.c-v.o),.2),facecolor=color))
  for key,label,color in [('target','Ціль','#16724a'),('entry','Вхід','#245aa5'),('stop','Стоп','#ac373e')]:
   px=float(r[key]);ax.axhline(px,ls='--',c=color,lw=1.2,label=f'{label} {px:,.1f}')
  ax.axvline(local(s),color='#7c6599',lw=1,ls=':',label='Структуру підтверджено')
  ax.scatter(local(a),float(r['entry']),marker='^' if side=='LONG' else 'v',color='#245aa5',s=90,zorder=5)
  ax.scatter(local(b-300),float(r['exit']),marker='X',color='#292d35',s=65,zorder=5)
  ax.set_ylabel('BTCUSDT perpetual · USDT');ax.xaxis_date();ax.xaxis.set_major_formatter(md.DateFormatter('%H:%M',tz=PL))
  ax.legend(loc='best',fontsize=9,framealpha=.88,ncol=2);ax.grid(axis='y',alpha=.17)
  fig.text(.105,.075,'Binance · M5. Трикутник — вхід. Хрест — свічка виходу. Рівні стопа й цілі задані до входу.',fontsize=10)
  fig.text(.105,.035,f"POI {r['poi']} ({int(r['poi_tf'])//3600} год)   |   Ціль: {r['target_type']}   |   Плановий RR {float(r['planned_RR']):.2f}",fontsize=9,color='#445666')
  pdf.savefig(fig);plt.close(fig)
