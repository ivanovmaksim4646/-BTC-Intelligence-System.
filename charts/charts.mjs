import {candles,annotations,TF} from './chart-data.mjs';
const $=id=>document.getElementById(id);
function tv(){const symbol=$('symbol').value,root=$('tv');root.replaceChildren();const container=document.createElement('div');container.className='tradingview-widget-container';container.style.cssText='height:100%;width:100%';const slot=document.createElement('div');slot.className='tradingview-widget-container__widget';slot.style.cssText='height:calc(100% - 32px);width:100%';const credit=document.createElement('a');credit.href='https://www.tradingview.com/';credit.textContent='Chart by TradingView';credit.target='_blank';credit.rel='noopener';const script=document.createElement('script');script.src='https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';script.async=true;script.textContent=JSON.stringify({autosize:true,symbol,interval:$('tvTf').value,timezone:'Europe/Warsaw',theme:'dark',style:'1',locale:'en',allow_symbol_change:false,hide_side_toolbar:false,support_host:'https://www.tradingview.com'});container.append(slot,credit,script);root.append(container);$('tvLink').href='https://www.tradingview.com/chart/?symbol='+encodeURIComponent(symbol);}
let chart,seq=0,cleanup=()=>{};
const raw='https://raw.githubusercontent.com/ivanovmaksim4646/-BTC-Intelligence-System./main/data/';
async function load(file){const r=await fetch(raw+file+'?t='+Date.now(),{cache:'no-store'});if(!r.ok)throw Error(file+' HTTP '+r.status);return r.json();}
async function render(){const request=++seq,tf=$('tf').value;$('status').textContent='Завантаження…';cleanup();if(chart){chart.remove();chart=null;}try{const doc=await load('BTC-okx-futures-candles.json');const data=candles(doc,tf);const [ctx,poi]=await Promise.all([load('BTC-okx-market-context-v1.json').catch(()=>null),load('BTC-okx-poi-qm-v1.json').catch(()=>null)]);if(request!==seq)return;if(!window.LightweightCharts)throw Error('Chart library unavailable');const L=window.LightweightCharts;chart=L.createChart($('own'),{autoSize:true,layout:{background:{color:'#101722'},textColor:'#cbd5e1',attributionLogo:true},grid:{vertLines:{color:'#263344'},horzLines:{color:'#263344'}},timeScale:{timeVisible:true}});const series=chart.addSeries(L.CandlestickSeries,{upColor:'#26a69a',downColor:'#ef5350',borderVisible:false,wickUpColor:'#26a69a',wickDownColor:'#ef5350'});series.setData(data);const recent=data.slice(-100),min=Math.min(...recent.map(x=>x.low)),max=Math.max(...recent.map(x=>x.high));const line=(price,title,color)=>{if(Number.isFinite(price)&&price>=min&&price<=max)series.createPriceLine({price,title,color,lineWidth:1,lineStyle:2,axisLabelVisible:true});};const a=annotations(doc,data,tf,ctx,poi),c=a.context,aligned=!!c;if(aligned){for(const x of (c.confirmed_swing_highs||[]).slice(-2))line(x.price,'Swing high','#e87979');for(const x of (c.confirmed_swing_lows||[]).slice(-2))line(x.price,'Swing low','#56ba9c');}const activeChart=chart,host=$('own'),svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.style.cssText='position:absolute;inset:0;width:100%;height:100%;pointer-events:none;overflow:hidden';host.append(svg);let raf=0,alive=true;function draw(){if(!alive)return;svg.replaceChildren();const time=activeChart.timeScale(),w=host.clientWidth,h=host.clientHeight,edge=Math.max(0,w-activeChart.priceScale('right').width());const node=(tag,attrs,label)=>{const n=document.createElementNS(svg.namespaceURI,tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,String(v));if(label)n.textContent=label;svg.append(n);};for(const z of a.zones){const x=time.timeToCoordinate(z.time),xEnd=time.timeToCoordinate(data.at(-1).time),y1=series.priceToCoordinate(z.high),y2=series.priceToCoordinate(z.low);if([x,xEnd,y1,y2].some(v=>v==null||!Number.isFinite(v)))continue;const left=Math.max(0,x),right=Math.min(edge,xEnd+5),top=Math.max(0,y1),bottom=Math.min(h-28,y2);if(right<=left||bottom<=top)continue;node('rect',{x:left,y:top,width:right-left,height:bottom-top,fill:z.color,'fill-opacity':.14,stroke:z.color,'stroke-opacity':.7});if(right-left>65)node('text',{x:left+3,y:Math.min(bottom+11,h-29),'font-size':11,fill:z.color},z.label);}for(const m of a.marks){const x=time.timeToCoordinate(m.time),y=series.priceToCoordinate(m.price);if(x==null||y==null||x<0||x>edge||y<0||y>h-28)continue;node('circle',{cx:x,cy:y,r:4,fill:m.color});node('text',{x:Math.max(3,x-135),y:Math.max(12,y-7),'font-size':11,fill:m.color},m.label);}raf=requestAnimationFrame(draw);}raf=requestAnimationFrame(draw);cleanup=()=>{alive=false;cancelAnimationFrame(raf);svg.remove();};chart.timeScale().setVisibleLogicalRange({from:Math.max(0,data.length-100),to:data.length+3});$('status').textContent='OKX BTC-USDT-SWAP · '+tf+' · '+doc.collected_at_utc+' · '+data.length+' закритих свічок. '+(aligned?'Swing контекст узгоджено.':'Swing контекст недоступний або не збігається.')+' IFVG/POI: '+(a.poiAvailable?'історичні спостереження':'недоступно')+'. OB: не підтверджено. BOS/Shift/Sweep: лише наявні кандидати.';}catch(e){if(request===seq)$('status').textContent='Дані недоступні: '+e.message;}}
$('symbol').onchange=tv;$('tvTf').onchange=tv;$('tf').onchange=render;$('refresh').onclick=render;tv();render();setInterval(render,60000);

async function health() {
  const summary = $('health-age');
  const panel = $('components');
  panel.replaceChildren();
  try {
    const doc = await load('BTC-system-health.json');
    const age = Math.floor((Date.now() - Date.parse(doc.checked_at_utc)) / 1000);
    const fresh = Number.isFinite(age) && age >= 0 && age <= 600;
    summary.textContent = (fresh ? 'Останній знімок' : 'Застарілий або невідомий знімок') + ' · ' + doc.checked_at_utc;
    for (const [key, item] of Object.entries(doc.components)) {
      const row = document.createElement('p');
      const detail = [key, item.status];
      if (Number.isFinite(item.age_seconds)) detail.push('затримка на момент знімка ' + item.age_seconds + ' с');
      if (item.h4_required) detail.push('H4 ' + (item.h4_buckets ?? '—') + '/' + item.h4_required);
      if (item.last_event_received_at_utc) detail.push(item.last_event_received_at_utc);
      if (item.backfill_error) detail.push(item.backfill_error);
      row.textContent = detail.join(' · ');
      panel.append(row);
    }
  } catch (error) { summary.textContent = 'Знімок недоступний · ' + error.message; }
  const link = $('latest-run');
  try {
    const url = 'https://api.github.com/repos/ivanovmaksim4646/-BTC-Intelligence-System./actions/workflows/btc-intelligence.yml/runs?branch=main&status=success&per_page=1';
    const response = await fetch(url);
    if (!response.ok) throw Error('HTTP ' + response.status);
    const run = (await response.json()).workflow_runs[0];
    if (!run) throw Error('відсутній');
    link.href = run.html_url; link.textContent = 'Останній успішний workflow · ' + run.updated_at + ' UTC';
  } catch (error) {link.removeAttribute('href'); link.textContent = 'Статус запуску недоступний · ' + error.message;}
}
health(); setInterval(health, 300000);
