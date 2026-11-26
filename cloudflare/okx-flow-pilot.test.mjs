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
