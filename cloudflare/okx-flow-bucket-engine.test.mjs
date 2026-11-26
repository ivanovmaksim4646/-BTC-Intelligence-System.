import test from "node:test";
import assert from "node:assert/strict";
import {makeState,markSubscribed,markInterrupted,acceptTrades,snapshot,M5_MS,MAX_IDS} from "./okx-flow-bucket-engine.mjs";
const barStart=1800000000000;
const trade=(id,ts,side,sz="2")=>({instId:"BTC-USDT-SWAP",tradeId:String(id),
  ts:String(ts),side,sz,px:"60000"});
test("signed aggressor buy/sell observed BTC and notional",()=>{
 const s=markSubscribed(makeState(barStart-1000),barStart-1000);
 acceptTrades(s,[trade(1,barStart+10,"buy"),trade(2,barStart+20,"sell","1")],0.01,barStart+1000);
 const d=snapshot(s,barStart+M5_MS+6000);
 assert.equal(d.observed_m5[0].delta_btc_observed,0.01);
 assert.equal(d.observed_m5[0].buy_btc,0.02);
 assert.equal(d.observed_m5[0].sell_btc,0.01);
 assert.equal(d.observed_m5[0].volume_btc,0.03);
 assert.equal(d.observed_m5[0].notional_usdt_observed,1800);
 assert.equal(d.observed_m5[0].complete_delta_btc,null);
 assert.equal(d.complete_cvd_btc,null);
 assert.equal(d.trade_signal,null);
});
test("duplicate tradeId never double counted across batches",()=>{
 const s=markSubscribed(makeState(barStart-1000),barStart-1000);
 acceptTrades(s,[trade(17,barStart+100,"buy")],0.01,barStart+500);
 acceptTrades(s,[trade(17,barStart+100,"buy")],0.01,barStart+1000);
 assert.equal(s.processed,1);
 assert.equal(s.duplicates,1);
});
test("session starting midbar cannot be continuous coverage",()=>{
 const s=markSubscribed(makeState(barStart+60000),barStart+60000);
 acceptTrades(s,[trade(1,barStart+70000,"buy")],0.01,barStart+70010);
 s.last_message_ms=barStart+M5_MS+100;
 const d=snapshot(s,barStart+M5_MS+6000);
 assert.equal(d.observed_m5[0].connection_window_observed,false);
});
test("a full observed session does NOT certify complete CVD",()=>{
 const s=markSubscribed(makeState(barStart-3000),barStart-3000);
 acceptTrades(s,[trade(1,barStart+1000,"buy"),trade(2,barStart+M5_MS-1000,"sell")],
  0.01,barStart+M5_MS+1000);
 const d=snapshot(s,barStart+M5_MS+6000);
 assert.equal(d.observed_m5[0].connection_window_observed,true);
 assert.equal(d.completeness_verified,false);
 assert.equal(d.observed_m5[0].complete_delta_btc,null);
 assert.equal(d.delta_m15_btc,null);
});
test("known reconnect gap prevents continuity label",()=>{
 const s=markSubscribed(makeState(barStart-1000),barStart-1000);
 acceptTrades(s,[trade(1,barStart+500,"buy")],0.01,barStart+1000);
 markInterrupted(s,barStart+90000,"websocket_closed");
 markSubscribed(s,barStart+120000);
 acceptTrades(s,[trade(2,barStart+M5_MS-1000,"sell")],0.01,barStart+M5_MS+1000);
 const d=snapshot(s,barStart+M5_MS+6000);
 assert.equal(d.observed_m5[0].connection_window_observed,false);
 assert.equal(d.interruptions.length,1);
});
test("invalid size, cross venue and impossible timestamps never aggregate",()=>{
 const s=markSubscribed(makeState(barStart-1000),barStart-1000);
 const bad=[trade(1,barStart+100,"buy","0"),
  {...trade(2,barStart+200,"buy"),instId:"BingX"},
  trade(3,barStart+150000,"buy")];
 acceptTrades(s,bad,0.01,barStart+1000);
 assert.equal(s.processed,0);assert.equal(s.invalid,3);
 assert.equal(snapshot(s,barStart+M5_MS+5000).observed_m5.length,0);
});
test("5m boundaries strictly bucket by exchange trade timestamps",()=>{
 const s=markSubscribed(makeState(barStart-1000),barStart-1000);
 acceptTrades(s,[trade(1,barStart+M5_MS-1,"buy"),trade(2,barStart+M5_MS,"sell")],
  0.01,barStart+M5_MS+100);
 assert.equal(s.buckets.length,2);
 assert.equal(s.buckets[0].start_ms,barStart);
 assert.equal(s.buckets[1].start_ms,barStart+M5_MS);
});
test("pre-subscribe trades are ignored",()=>{
 const s=makeState(barStart-1000);
 acceptTrades(s,[trade(1,barStart+100,"buy")],0.01,barStart+300);
 assert.equal(s.processed,0);
 assert.equal(s.buckets.length,0);
});
test("invalid clock not accepted",()=>{
 const s=makeState(barStart-1000);
 assert.throws(()=>markSubscribed(s,barStart-2000));
 assert.throws(()=>snapshot(s,NaN));
});
