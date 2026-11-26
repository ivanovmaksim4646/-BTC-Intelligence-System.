import test from "node:test";
import assert from "node:assert/strict";
import { parseTrade, eventType, normalizeMetadata } from "./okx-trade-utils.mjs";
import { OkxCanary } from "./okx-ws-canary.mjs";

const okTrade={instId:"BTC-USDT-SWAP",tradeId:"123456789012345",ts:"1795693400000",
               px:"60650",sz:"10",side:"buy"};
test("contract unit normalization is never assumed",()=>{
  assert.equal(normalizeMetadata([{instId:"BTC-USDT-SWAP",ctValCcy:"BTC",ctVal:"0.01"}]),0.01);
  assert.equal(normalizeMetadata([{instId:"BTC-USDT-SWAP",ctValCcy:"USDT",ctVal:"100"}]),null);
  assert.equal(normalizeMetadata([]),null);
});
test("aggressor side normalization, no fake CVD",()=>{
  assert.equal(parseTrade(okTrade,0.01).signedBTC,0.1);
  assert.equal(parseTrade({...okTrade,side:"sell"},0.01).signedBTC,-0.1);
  assert.equal(parseTrade({...okTrade,side:"unknown"},0.01),null);
  assert.equal(parseTrade({...okTrade,instId:"BTC-USDT"},0.01),null);
  assert.equal(parseTrade({...okTrade,sz:"NaN"},0.01),null);
  assert.equal(parseTrade(okTrade,null),null);
});
test("only subscribed public trade events are accepted",()=>{
  assert.equal(eventType({event:"subscribe",arg:{channel:"trades",instId:"BTC-USDT-SWAP"}}),"subscribed");
  assert.equal(eventType({event:"error",msg:"invalid"}),"error");
  assert.equal(eventType({arg:{channel:"trades",instId:"BTC-USDT-SWAP"},data:[okTrade]}),"trades");
  assert.equal(eventType({arg:{channel:"trades",instId:"BTC-USDT"},data:[okTrade]}),"unrelated");
});
test("DO canary closes after alarm and never certifies M5",async()=>{
  const saved=new Map();
  const storage={
    get:async k=>saved.get(k),
    put:async(k,v)=>saved.set(k,v),
    setAlarm:async t=>saved.set("alarm",t)
  };
  const ctx={storage};
  const api=new OkxCanary(ctx,{});
  const oldFetch=globalThis.fetch;
  const oldWS=globalThis.WebSocket;
  class Socket {
    constructor(url){this.url=url;this.events={};this.sent=[];}
    addEventListener(name,handler){this.events[name]=handler;}
    send(v){this.sent.push(v);}
    close(){this.closed=true;}
  }
  globalThis.fetch=async()=>({ok:true,json:async()=>({code:"0",data:[
    {instId:"BTC-USDT-SWAP",ctValCcy:"BTC",ctVal:"0.01"}]})});
  globalThis.WebSocket=Socket;
  try {
    let resp=await api.fetch(new Request("https://internal/start",{method:"POST"}));
    assert.equal(resp.status,200);
    assert.ok(saved.get("alarm"));
    api.ws.events.open();
    assert.match(api.ws.sent[0],/"trades"/);
    api.ws.events.message({data:JSON.stringify({event:"subscribe",arg:{channel:"trades",instId:"BTC-USDT-SWAP"}})});
    const trade={...okTrade,ts:String(Date.now())};
    api.ws.events.message({data:JSON.stringify({arg:{channel:"trades",instId:"BTC-USDT-SWAP"},data:[trade,trade]})});
    await api.alarm();
    const status=saved.get("summary");
    assert.equal(status.subscribed,true);
    assert.equal(status.trade_count,1);
    assert.equal(status.complete_m5,false);
    assert.equal(status.m5_cvd,null);
    assert.equal(status.trade_signal,null);
    assert.equal(status.canary_complete,true);
    resp=await api.fetch(new Request("https://internal/start",{method:"POST"}));
    assert.equal((await resp.json()).status,"already_started");
  } finally {globalThis.fetch=oldFetch;globalThis.WebSocket=oldWS;}
});
