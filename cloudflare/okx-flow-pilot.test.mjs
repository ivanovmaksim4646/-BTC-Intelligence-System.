import test from "node:test";
import assert from "node:assert/strict";
import worker,{OkxFlowPilot} from "./okx-flow-pilot.mjs";
const control="test-token-not-a-real-secret";
function mock(){
 const stored=new Map();
 let alarm=null;
 const storage={get:async k=>stored.get(k),put:async(k,v)=>stored.set(k,v),
   setAlarm:async t=>{alarm=t;}};
 const state=new OkxFlowPilot({storage},{FLOW_PILOT_ENABLED:"false"});
 const stub={fetch:(u,opts)=>state.fetch(new Request(u,opts))};
 const env={FLOW_PILOT_CONTROL_TOKEN:control,OKX_FLOW_PILOT:{
   idFromName:()=>({}),get:()=>stub}};
 return {state,stored,env,getAlarm:()=>alarm};
}
test("pilot health is unstarted with null CVD",async()=>{
 const x=mock();
 const r=await worker.fetch(new Request("https://example.test/status"),x.env);
 assert.equal(r.status,200);
 const d=await r.json();
 assert.equal(d.phase,"not_started");
 assert.equal(d.complete_cvd_btc,null);
});
test("pilot control requests need authentication",async()=>{
 const x=mock();
 const r=await worker.fetch(new Request("https://example.test/start",{method:"POST"}),x.env);
 assert.equal(r.status,403);
 assert.equal(x.getAlarm(),null);
});
test("even authorized start cannot enable cost-bearing connection without explicit flag",async()=>{
 const x=mock();
 const r=await worker.fetch(new Request("https://example.test/start",{
  method:"POST",headers:{Authorization:`Bearer ${control}`}}),x.env);
 assert.equal(r.status,403);
 assert.equal((await r.json()).error,"explicit_plan_approval_required");
 assert.equal(x.getAlarm(),null);
});
test("pilot stop is authenticated, even when never started",async()=>{
 const x=mock();
 let r=await worker.fetch(new Request("https://example.test/stop",{method:"POST"}),x.env);
 assert.equal(r.status,403);
 r=await worker.fetch(new Request("https://example.test/stop",{method:"POST",
  headers:{Authorization:`Bearer ${control}`}}),x.env);
 assert.equal(r.status,200);
 const health=await worker.fetch(new Request("https://example.test/status"),x.env);
 assert.equal((await health.json()).complete_cvd_btc,null);
});

test("opt-in pilot subscribes to trades-all, records raw observation and stops at bounded alarm",async()=>{
 const x=mock();
 x.state.env.FLOW_PILOT_ENABLED="true";
 const previousFetch=globalThis.fetch,previousSocket=globalThis.WebSocket;
 let socket;
 class FakeSocket {
   constructor(url){assert.equal(url,"wss://ws.okx.com/ws/v5/business");this.listeners={};this.sent=[];socket=this;}
   addEventListener(name,fn){this.listeners[name]=fn;}
   send(payload){this.sent.push(JSON.parse(payload));}
   close(){this.closed=true;}
   emit(name,arg){this.listeners[name]?.(arg);}
 }
 globalThis.fetch=async()=>Response.json({code:"0",data:[{
   instId:"BTC-USDT-SWAP",ctValCcy:"BTC",ctVal:"0.01"
 }]});
 globalThis.WebSocket=FakeSocket;
 try {
   const started=await worker.fetch(new Request("https://example.test/start",{
     method:"POST",headers:{Authorization:`Bearer ${control}`}}),x.env);
   assert.equal(started.status,200);
   assert.equal((await started.json()).max_duration_seconds,420);
   assert.ok(x.getAlarm()>=Date.now()+410000);
   socket.emit("open");
   assert.equal(socket.sent[0].args[0].channel,"trades-all");
   x.state.onMessage(JSON.stringify({event:"subscribe",arg:{
     channel:"trades-all",instId:"BTC-USDT-SWAP"}}));
   x.state.onMessage(JSON.stringify({arg:{channel:"trades-all",instId:"BTC-USDT-SWAP"},
     data:[{instId:"BTC-USDT-SWAP",tradeId:"919191",px:"60000",
       sz:"2",side:"buy",ts:String(Date.now()-1000)}]}));
   const running=await(await worker.fetch(new Request("https://example.test/status"),x.env)).json();
   assert.equal(running.total_unique_trades,1);
   assert.equal(running.complete_m5_delta_btc,null);
   assert.equal(running.trade_signal,null);
   await x.state.alarm();
   assert.equal(socket.closed,true);
   const completed=await(await worker.fetch(new Request("https://example.test/status"),x.env)).json();
   assert.equal(completed.pilot_completed,true);
   assert.equal(completed.completeness_verified,false);
   assert.equal(completed.complete_cvd_btc,null);
 } finally {
   globalThis.fetch=previousFetch;
   globalThis.WebSocket=previousSocket;
 }
});
