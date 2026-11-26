import test from 'node:test';import assert from 'node:assert/strict';import {candles,gaps} from './chart-data.mjs';
const now=1800;const b=(t,o,h,l,c)=>({t,o,h,l,c});const doc={source:'OKX BTC-USDT-SWAP',status:'verified',collected_at_utc:new Date(now*1000).toISOString(),timeframes:{'5m':{status:'ok',bars:[b(300,10,11,9,10),b(600,12,13,11,12),b(900,14,15,13,14)]}}};
test('real OHLC shape and bullish gap',()=>{let x=candles(doc,'5m',now);assert.equal(x.length,3);assert.equal(gaps(x,'5m')[0].low,11);});
test('reject stale, wrong venue, open, duplicate and invalid candles',()=>{assert.throws(()=>candles(doc,'5m',now+901));assert.throws(()=>candles({...doc,source:'Kraken'},'5m',now));for(const bar of [b(1800,10,11,9,10),b(600,10,11,9,10),b(900,10,8,9,10)]){let x=structuredClone(doc);x.timeframes['5m'].bars[2]=bar;assert.throws(()=>candles(x,'5m',now));}});
test('no FVG across missing candles',()=>{let x=candles(doc,'5m',now);x[2].time+=300;assert.deepEqual(gaps(x,'5m'),[]);});
