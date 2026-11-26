import test from "node:test";
import assert from "node:assert/strict";
import { TradingViewInbox } from "./tradingview-inbox.mjs";
import main from "../worker.js";

function event() {
 return {source:"btc-intelligence-tv-v2",event:"m5_bearish_shift",
  symbol:"BINGX:BTCUSDT.P",timeframe:"5",time_ms:Date.now(),
  price:60500,level:60510,level_kind:"pivot_low",volume:42};
}
function fixture(token="valid-test-only") {
 const values=new Map();let alarm=null;
 const storage={
   async get(k){return values.get(k);},
   async put(k,v){values.set(k,structuredClone(v));},
   async setAlarm(t){alarm=t;},
   async getAlarm(){return alarm;},
 };
 const inbox=new TradingViewInbox({storage},{GITHUB_DISPATCH_TOKEN:token});
 const stub={fetch:(url,opts)=>inbox.fetch(new Request(url,opts))};
 const env={GITHUB_DISPATCH_TOKEN:token,TV_INBOX:{
   idFromName:()=>({}),get:()=>stub
 }};
 return {inbox,stub,env,values,storage,alarm:()=>alarm};
}
async function enqueue(stub,item){return stub.fetch("https://internal/enqueue",{
 method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(item)})}
test("202 only after durable write, with separate alarm delivery",async()=>{
 const x=fixture();const alert=event();
 const original=globalThis.fetch;let calls=0;
 globalThis.fetch=async (url,options)=>{
  calls++;assert.match(String(url),/tradingview-intelligence.yml/);
  const payload=JSON.parse(options.body);assert.deepEqual(JSON.parse(payload.inputs.tv_payload),alert);
  return new Response(null,{status:204});
 };
 try {
  const response=await enqueue(x.stub,alert);
  assert.equal(response.status,202);
  assert.equal((await response.json()).queued,true);
  assert.equal(calls,0,"GitHub must not be called in TradingView HTTP path");
  assert.ok(x.alarm());
  await x.inbox.alarm();
  assert.equal(calls,1);
  const health=await(await x.stub.fetch("https://internal/status")).json();
  assert.equal(health.pending,0);
  assert.equal(health.accepted_dispatched,1);
  assert.equal(health.trade_signal,null);
 } finally {globalThis.fetch=original;}
});
test("duplicate event accepted once, dispatched once",async()=>{
 const x=fixture();const e=event();const original=globalThis.fetch;
 globalThis.fetch=async()=>new Response(null,{status:204});
 try{
  assert.equal((await enqueue(x.stub,e)).status,202);
  const duplicate=await (await enqueue(x.stub,e)).json();
  assert.equal(duplicate.duplicate,true);
  await x.inbox.alarm();
  const health=await(await x.stub.fetch("https://internal/status")).json();
  assert.equal(health.accepted_dispatched,1);
 } finally {globalThis.fetch=original;}
});
test("GitHub 503 gets bounded retry and never loses queued event",async()=>{
 const x=fixture();const e=event();const original=globalThis.fetch;
 globalThis.fetch=async()=>new Response("unavailable",{status:503});
 try{
  await enqueue(x.stub,e);
  await x.inbox.alarm();
  let health=await(await x.stub.fetch("https://internal/status")).json();
  assert.equal(health.pending,1);
  assert.equal(health.last_error,"github_http_503");
  assert.equal(health.accepted_dispatched,0);
  assert.equal(health.dead_letters,0);
  const state=x.values.get("inbox_v1");
  assert.equal(state.pending[0].attempts,1);
  assert.ok(state.pending[0].notBefore>Date.now());
 }finally{globalThis.fetch=original;}
});
test("missing token returns 503 and does not promise delivery",async()=>{
 const x=fixture("");
 const r=await enqueue(x.stub,event());
 assert.equal(r.status,503);
 assert.equal(x.values.has("inbox_v1"),false);
});
test("storage failure does not return 202",async()=>{
 const x=fixture();x.storage.put=async()=>{throw new Error("storage_failed")};
 const request=new Request("https://btc-intelligence-scheduler.workers.dev/tv-webhook",{
   method:"POST",headers:{"CF-Connecting-IP":"52.89.214.238"},body:JSON.stringify(event())});
 const response=await main.fetch(request,x.env);
 assert.equal(response.status,503);
});
test("TradingView HTTP succeeds without waiting for GitHub",async()=>{
 const x=fixture();const original=globalThis.fetch;let calls=0;
 globalThis.fetch=async()=>{calls++;throw Error("GitHub unreachable")};
 try{
  const req=new Request("https://btc-intelligence-scheduler.workers.dev/tv-webhook",{
   method:"POST",headers:{"CF-Connecting-IP":"52.89.214.238"},body:JSON.stringify(event())});
  const response=await main.fetch(req,x.env);
  assert.equal(response.status,202);
  assert.equal(calls,0);
  const health=await main.fetch(new Request("https://btc-intelligence-scheduler.workers.dev/tv-queue-health"),x.env);
  assert.equal(health.status,200);
  assert.equal((await health.json()).pending,1);
 }finally{globalThis.fetch=original;}
});
test("TradingView unknown IP remains rejected",async()=>{
 const x=fixture();
 const req=new Request("https://example.test/tv-webhook",{method:"POST",
  headers:{"CF-Connecting-IP":"192.0.2.1"},body:JSON.stringify(event())});
 assert.equal((await main.fetch(req,x.env)).status,403);
 assert.equal(x.values.has("inbox_v1"),false);
});
