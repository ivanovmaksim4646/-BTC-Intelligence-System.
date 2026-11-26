// Standalone OKX outbound WebSocket canary. NEVER places trades.
// Can connect for one short trial only, then persists canary_complete=true.
// Uses separate Worker/DO from the production GitHub scheduler + TradingView.
import { INSTRUMENT, eventType, normalizeMetadata, parseTrade } from "./okx-trade-utils.mjs";

const URL = "wss://ws.okx.com/ws/v5/public"; // port 443, 8443 retired in 2026
const START_MS = 35_000;
const LIMIT_MESSAGES = 5000;
const SUMMARY_KEY = "summary";

export class OkxCanary {
  constructor(ctx, env) {
    this.ctx=ctx;this.env=env;this.ws=null;this.seen=new Set();
    this.trades=0;this.signed=0;this.notional=0;this.bad=0;
    this.subscribed=false;this.startedAt=null;this.lastTrade=null;
    this.multiplier=null;this.messages=0;this.closed=false;
  }
  async fetch(req) {
    const p=new URL(req.url).pathname;
    if (p==="/status") {
      const status=await this.ctx.storage.get(SUMMARY_KEY);
      return Response.json(status ?? {phase:"not_started",live_data_verified:false,complete_m5:false});
    }
    if (p!=="/start" || req.method!=="POST") return new Response("Not found",{status:404});
    const old=await this.ctx.storage.get(SUMMARY_KEY);
    if (old?.canary_complete || old?.phase==="running" || this.ws) {
      return Response.json({status:"already_started",phase:old?.phase??"running"});
    }
    // Fail-closed when instrument metadata cannot be verified.
    let metadata;
    try {
      const resp=await fetch("https://www.okx.com/api/v5/public/instruments?instType=SWAP&instId=BTC-USDT-SWAP");
      if (!resp.ok) throw new Error("metadata_http");
      const data=await resp.json();
      if (String(data.code)!=="0") throw new Error("metadata_code");
      metadata=normalizeMetadata(data.data);
    } catch { metadata=null; }
    if (!metadata) {
      await this.ctx.storage.put(SUMMARY_KEY,{phase:"metadata_unavailable",canary_complete:true,
        complete_m5:false,trade_signal:null,source:INSTRUMENT});
      return Response.json({status:"metadata_unavailable"}, {status:503});
    }
    this.multiplier=metadata;
    this.startedAt=Date.now();
    const status={phase:"connecting",source:INSTRUMENT,venue:"OKX",started_at_utc:new Date(this.startedAt).toISOString(),
      canary_complete:false,complete_m5:false,trade_signal:null};
    await this.ctx.storage.put(SUMMARY_KEY,status);
    // Alarm ensures the trial is bounded even when the WS goes silent.
    await this.ctx.storage.setAlarm(Date.now()+START_MS);
    try {
      this.ws=new WebSocket(URL);
      this.ws.addEventListener("open",()=>{
        this.ws.send(JSON.stringify({op:"subscribe",args:[{channel:"trades",instId:INSTRUMENT}]}));
      });
      this.ws.addEventListener("message",e=>this.onMessage(e.data));
      this.ws.addEventListener("error",()=>{ void this.finalize("socket_error"); });
      this.ws.addEventListener("close",()=>{ void this.finalize("socket_closed"); });
    } catch {
      await this.finalize("socket_setup_failed");
      return Response.json({status:"socket_setup_failed"},{status:502});
    }
    return Response.json({status:"canary_started",deadline_seconds:35,complete_m5:false});
  }
  onMessage(raw) {
    if (this.closed) return;
    if (raw==="pong") return;
    this.messages++;
    if (this.messages>LIMIT_MESSAGES) {void this.finalize("message_limit");return;}
    let payload;
    try {payload=JSON.parse(raw);} catch {this.bad++;return;}
    const kind=eventType(payload);
    if (kind==="subscribed") {this.subscribed=true;return;}
    if (kind==="error") {void this.finalize("subscription_error");return;}
    if (kind!=="trades") return;
    const now=Date.now();
    for (const item of payload.data) {
      const tr=parseTrade(item,this.multiplier);
      if (!tr || tr.ts>now+3000 || now-tr.ts>120000) {this.bad++;continue;}
      // Deduplication is limited to this session (not a guaranteed full trade feed).
      if (this.seen.has(tr.id)) continue;
      this.seen.add(tr.id);
      if (this.seen.size>20000) {void this.finalize("dedupe_capacity");return;}
      this.trades++;
      this.signed+=tr.signedBTC;
      this.notional+=tr.notionalUSDT;
      this.lastTrade=tr.ts;
    }
  }
  async alarm() {await this.finalize("trial_window_elapsed");}
  async finalize(reason) {
    if (this.closed) return;
    this.closed=true;
    try {this.ws?.close(1000,"canary complete");} catch {}
    const summary={phase:"completed",completion_reason:reason,source:INSTRUMENT,venue:"OKX",
      canary_complete:true,subscribed:this.subscribed,message_count:this.messages,trade_count:this.trades,
      invalid_trade_count:this.bad,last_trade_ms:this.lastTrade,
      contract_btc:this.multiplier,
      page_delta_btc_estimate:Number(this.signed.toFixed(8)),
      observed_notional_usdt:Number(this.notional.toFixed(2)),
      coverage:"partial_35_second_canary_not_full_5m",
      complete_m5:false,m5_delta_btc:null,m5_cvd:null,trade_signal:null,entry_signal:false,
      started_at_utc:this.startedAt?new Date(this.startedAt).toISOString():null,
      ended_at_utc:new Date().toISOString()};
    await this.ctx.storage.put(SUMMARY_KEY,summary);
  }
}

export default {
  async scheduled(_controller,env,ctx) {
    const id=env.OKX_CANARY.idFromName("btc-okx-ws-canary-v1");
    const stub=env.OKX_CANARY.get(id);
    ctx.waitUntil(stub.fetch("https://internal/start",{method:"POST"}));
  },
  async fetch(req,env) {
    if (new URL(req.url).pathname!=="/status" || req.method!=="GET") {
      return new Response("Not found",{status:404});
    }
    const id=env.OKX_CANARY.idFromName("btc-okx-ws-canary-v1");
    return env.OKX_CANARY.get(id).fetch("https://internal/status");
  }
};
