export const TF={ '5m':300,'15m':900,'1h':3600,'4h':14400,'1d':86400 };
export function candles(doc,tf,now=Date.now()/1000){
 if(doc.source!=='OKX BTC-USDT-SWAP'||doc.status!=='verified'||!TF[tf]||doc.timeframes?.[tf]?.status!=='ok')throw Error('Unverified OHLC source');
 const stamp=Date.parse(doc.collected_at_utc)/1000;
 if(!Number.isFinite(stamp)||stamp>now+5||now-stamp>900)throw Error('Stale or future snapshot');
 const bars=doc.timeframes[tf].bars;if(!Array.isArray(bars)||bars.length<3)throw Error('Missing candles');
 let prev=0;return bars.map(b=>{if(![b.t,b.o,b.h,b.l,b.c].every(Number.isFinite)||!Number.isInteger(b.t)||b.t<=prev||b.t+TF[tf]>stamp+5||b.l<=0||b.h<Math.max(b.o,b.c,b.l)||b.l>Math.min(b.o,b.c))throw Error('Invalid OHLC');prev=b.t;return {time:b.t,open:b.o,high:b.h,low:b.l,close:b.c};});
}
export function gaps(bars,tf){const out=[];for(let i=2;i<bars.length;i++){const a=bars[i-2],b=bars[i-1],c=bars[i];if(c.time-b.time!==TF[tf]||b.time-a.time!==TF[tf])continue;if(c.low>a.high)out.push({low:a.high,high:c.low,side:'Bull',time:c.time});else if(c.high<a.low)out.push({low:c.high,high:a.low,side:'Bear',time:c.time});}return out.slice(-3);}
