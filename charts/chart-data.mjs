export const TF={ '5m':300,'15m':900,'1h':3600,'4h':14400,'1d':86400 };
export function candles(doc,tf,now=Date.now()/1000){
 if(doc.source!=='OKX BTC-USDT-SWAP'||doc.status!=='verified'||!TF[tf]||doc.timeframes?.[tf]?.status!=='ok')throw Error('Unverified OHLC source');
 const stamp=Date.parse(doc.collected_at_utc)/1000;
 if(!Number.isFinite(stamp)||stamp>now+5||now-stamp>900)throw Error('Stale or future snapshot');
 const bars=doc.timeframes[tf].bars;if(!Array.isArray(bars)||bars.length<3)throw Error('Missing candles');
 let prev=0;return bars.map(b=>{if(![b.t,b.o,b.h,b.l,b.c].every(Number.isFinite)||!Number.isInteger(b.t)||b.t<=prev||b.t+TF[tf]>stamp+5||b.l<=0||b.h<Math.max(b.o,b.c,b.l)||b.l>Math.min(b.o,b.c))throw Error('Invalid OHLC');prev=b.t;return {time:b.t,open:b.o,high:b.h,low:b.l,close:b.c};});
}
export function gaps(bars,tf){const out=[];for(let i=2;i<bars.length;i++){const a=bars[i-2],b=bars[i-1],c=bars[i];if(c.time-b.time!==TF[tf]||b.time-a.time!==TF[tf])continue;if(c.low>a.high)out.push({low:a.high,high:c.low,side:'Bull',time:c.time});else if(c.high<a.low)out.push({low:c.high,high:a.low,side:'Bear',time:c.time});}return out.slice(-3);}

export function alignedContext(doc,ctx,tf,bars,now=Date.now()/1000){
 const c=ctx?.timeframes?.[tf],last=bars.at(-1),stamp=Date.parse(ctx?.generated_at_utc)/1000;
 return ctx?.source===doc.source&&c?.status==='observed'&&last&&c.last_closed_candle_open_s===last.time&&c.last_closed_candle_close_s===last.time+TF[tf]&&c.last_close===last.close&&Number.isFinite(stamp)&&stamp<=now&&now-stamp<=900?c:null;
}
export function annotations(doc,bars,tf,ctx,poi,now=Date.now()/1000){
 const first=bars[0].time,last=bars.at(-1).time,byTime=new Map(bars.map(b=>[b.time,b]));
 const zones=gaps(bars,tf).map(g=>({...g,label:g.side+' FVG',color:g.side==='Bull'?'#36b69a':'#e87979'}));
 const c=alignedContext(doc,ctx,tf,bars,now);
 const stamp=Date.parse(poi?.evaluated_at_utc)/1000;
 const validPoi=poi?.source===doc.source&&poi?.classification==='futures_research_only'&&Number.isFinite(stamp)&&stamp<=now&&now-stamp<=900;
 const validZone=(low,high,t)=>Number.isFinite(low)&&Number.isFinite(high)&&low>0&&high>low&&byTime.has(t)&&t>=first&&t<=last;
 if(validPoi){
   for(const g of (poi.ifvg?.[tf]||[]).filter(g=>g.status==='inverted_observation'&&validZone(g.low,g.high,g.inverted_at)).slice(-2))
      zones.push({low:g.low,high:g.high,time:g.inverted_at,label:'IFVG hist.',color:'#a78bfa'});
   const seen=new Set();
   for(const p of (poi.observations||[]).filter(p=>p.htf===tf&&p.poi_type==='3_candle_fvg'&&p.status==='historical_sequence_observed'&&validZone(p.poi_low,p.poi_high,p.poi_formed_at)).slice(-2)){
      const key=[p.poi_low,p.poi_high,p.poi_formed_at].join(':');if(seen.has(key))continue;seen.add(key);
      zones.push({low:p.poi_low,high:p.poi_high,time:p.poi_formed_at,label:'POI hist.',color:'#61a5fa'});
   }
 }
 const marks=[];if(c){
   const b=c.fresh_bos_or_choch;
   if(b?.source===doc.source&&b.timeframe===tf&&b.event_close_s===last+TF[tf]&&Number.isFinite(b.break_level)&&/^(bullish|bearish)_/.test(b.kind||'')){
     const label=/bos/i.test(b.kind)?'BOS candidate':/shift|choch/i.test(b.kind)?'Shift candidate':null;
     if(label)marks.push({time:last,price:b.break_level,label,color:'#f2c56b'});
   }
   for(const [side,pivots] of [['high',c.confirmed_swing_highs],['low',c.confirmed_swing_lows]]){
     const x=pivots?.at(-1),tail=bars.at(-1);
     if(!x||!Number.isFinite(x.price)||!byTime.has(x.t)||last-x.t<3*TF[tf]||!byTime.has(last-TF[tf]))continue;
     const earlier=bars.filter(b=>b.time>x.t&&b.time<last);
     if(earlier.length!==(last-x.t)/TF[tf]-1)continue;
     const swept=side==='high'?tail.high>x.price&&tail.close<x.price&&earlier.every(b=>b.high<=x.price):tail.low<x.price&&tail.close>x.price&&earlier.every(b=>b.low>=x.price);
     if(swept)marks.push({time:last,price:x.price,label:'Sweep '+side+' candidate',color:'#f2c56b'});
   }
 }
 return {zones,marks,context:c,poiAvailable:validPoi};
}
