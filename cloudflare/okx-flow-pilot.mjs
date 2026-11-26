// Explicitly opt-in, BOUNDED 7-minute OKX trades-all WebSocket pilot.
// Not auto-deployed or scheduled. An outbound WebSocket keeps DO active and
// may consume Cloudflare billable duration. This Worker must not be deployed
// until Cloudflare plan and spending guard are verified by the account owner.
import { INSTRUMENT, normalizeMetadata } from "./okx-trade-utils.mjs";
import { makeState, markSubscribed, markInterrupted,
         acceptTrades, snapshot } from "./okx-flow-bucket-engine.mjs";
const WS="wss://ws.okx.com/ws/v5/business";
const MAX_PILOT_MS=7*60*1000;
const SUMMARY_KEY="okx_ws_flow_pilot_v1";
const MAX_MESSAGES=100000;
export class OkxFlowPilot {
  constructor(ctx,env) {
    this.ctx=ctx;this.env=env;this.ws=null;this.state=null;
    this.deadline=null;this.done=false;this.messages=0;this.multiplier=null;
  }
  async fetch(req) {
    const path=new URL(req.url).pathname;
    if(path==="/status" && req.method==="GET") {
      const prev=await this.ctx.storage.get(SUMMARY_KEY);
      return Response.json(this.state && !this.done?{
        ...snapshot(this.state,Date.now()),phase:this.done?"complete":"active",
        messages:this.messages,bounded_seconds:420,pilot:true
      }:(prev??{phase:"not_started",pilot:true,completeness_verified:false,
           complete_cvd_btc:null,trade_signal:null}),
      {headers:{"Cache-Control":"no-store"}});
    }
    if(path==="/stop" && req.method==="POST") {
      await this.end("operator_stop");
      return Response.json({status:"stopped"});
    }
    if(path!=="/start" || req.method!=="POST")return new Response("Not found",{status:404});
    const old=await this.ctx.storage.get(SUMMARY_KEY);
    if(this.state||old?.pilot_completed) {
      return Response.json({error:"already_started_or_complete"},{status:409});
    }
    if(this.env.FLOW_PILOT_ENABLED!=="true")
      return Response.json({error:"explicit_plan_approval_required"},{status:403});
    let ct;
    try {
      const resp=await fetch("https://www.okx.com/api/v5/public/instruments?instType=SWAP&instId="+INSTRUMENT);
      if(!resp.ok)throw Error("metadata_http");
      const data=await resp.json();
      if(String(data.code)!=="0")throw Error("metadata_code");
      ct=normalizeMetadata(data.data);
    }catch{ct=null;}
    if(!ct)return Response.json({error:"instrument_metadata_unverified"},{status:503});
    this.multiplier=ct;
    const start=Date.now();this.state=makeState(start);
    this.deadline=start+MAX_PILOT_MS;
    await this.ctx.storage.put(SUMMARY_KEY,{phase:"starting",pilot:true,started_ms:start,
      pilot_completed:false,complete_cvd_btc:null,trade_signal:null});
    await this.ctx.storage.setAlarm(this.deadline);
    try {
      this.ws=new WebSocket(WS);
      this.ws.addEventListener("open",()=>{
        this.ws.send(JSON.stringify({op:"subscribe",args:[{
          channel:"trades-all",instId:INSTRUMENT}]}));
      });
      this.ws.addEventListener("message",e=>this.onMessage(e.data));
      this.ws.addEventListener("close",()=>{void this.end("socket_closed");});
      this.ws.addEventListener("error",()=>{void this.end("socket_error");});
    }catch {
      await this.end("socket_setup_failed");
      return Response.json({error:"socket_setup_failed"},{status:502});
    }
    return Response.json({status:"pilot_started",max_duration_seconds:420,
      complete_cvd_btc:null,trade_signal:null});
  }
  onMessage(raw) {
    if(this.done||!this.state)return;
    const now=Date.now();
    if(now>=this.deadline){void this.end("hard_deadline");return;}
    if(raw==="pong")return;
    if(++this.messages>MAX_MESSAGES){void this.end("message_capacity");return;}
    let packet;
    try{packet=JSON.parse(raw);}catch{
      markInterrupted(this.state,now,"malformed_json");
      void this.end("malformed_json");return;
    }
    if(packet?.event==="subscribe" && packet?.arg?.channel==="trades-all"
        && packet?.arg?.instId===INSTRUMENT) {
      markSubscribed(this.state,now);return;
    }
    if(packet?.event==="error" || packet?.event==="notice"){
      markInterrupted(this.state,now,"okx_error_or_notice");
      void this.end("subscription_error_or_notice");return;
    }
    if(packet?.arg?.channel!=="trades-all"||packet?.arg?.instId!==INSTRUMENT
        ||!Array.isArray(packet?.data))return;
    acceptTrades(this.state,packet.data,this.multiplier,now);
    if(this.state.overflow)void this.end("dedupe_capacity");
  }
  async alarm(){await this.end("bounded_pilot_complete");}
  async end(reason) {
    if(this.done)return;
    this.done=true;
    if(this.state)markInterrupted(this.state,Date.now(),reason);
    try{this.ws?.close(1000,"pilot done");}catch{}
    const summary=this.state? snapshot(this.state,Date.now()):{
      source:"OKX BTC-USDT-SWAP",completeness_verified:false,
      complete_cvd_btc:null,trade_signal:null};
    await this.ctx.storage.put(SUMMARY_KEY,{...summary,pilot_completed:true,
      completion_reason:reason,pilot:true,messages:this.messages,
      contract_btc:this.multiplier,
      note:"No claim of complete CVD; trades-all stream tested only within bounded pilot."});
  }
}
function allowed(req,env) {
  const credential=env.FLOW_PILOT_CONTROL_TOKEN;
  return !!credential && req.headers.get("Authorization")===`Bearer ${credential}`;
}
export default {
  async fetch(req,env) {
    const path=new URL(req.url).pathname;
    if(path!=="/status" && !allowed(req,env))
      return new Response("Forbidden",{status:403});
    const id=env.OKX_FLOW_PILOT.idFromName("btc-okx-flow-pilot-v1");
    return env.OKX_FLOW_PILOT.get(id).fetch("https://pilot.internal"+path,{
      method:req.method});
  }
};
