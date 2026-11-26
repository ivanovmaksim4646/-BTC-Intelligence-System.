// Pure OKX BTC-USDT-SWAP streaming bucket accumulator.
// IMPORTANT: uninterrupted socket observation is not proof of every exchange
// trade (OKX trades channel has no independently verified gap-free sequence).
// Never label these buckets as certified complete CVD/Delta.
import { parseTrade, INSTRUMENT } from "./okx-trade-utils.mjs";

export const M5_MS=300000;
export const MAX_IDS=60000;
export const MAX_BUCKETS=52; // ~4h20m of 5-minute market observations
export const GRACE_MS=5000;
export const MAX_CLOCK_DRIFT_MS=10000;

function emptyBucket(start) {
  return {start_ms:start,end_ms:start+M5_MS,trades:0,buy_btc:0,sell_btc:0,
    signed_btc:0,volume_btc:0,notional_usdt:0,
    validity:"observed_only_not_certified_complete"};
}
function rounded(x){return Math.round(x*1e8)/1e8;}
export function makeState(startedAtMs) {
  if(!Number.isSafeInteger(startedAtMs)||startedAtMs<0)throw Error("bad_start");
  return {source:INSTRUMENT,started_ms:startedAtMs,phase:"not_subscribed",
    connection_started_ms:null,last_message_ms:null,last_trade_ms:null,
    last_id:null,processed:0,duplicates:0,invalid:0,overflow:false,
    interruptions:[],buckets:[],ids:[],status:"unverified",
    complete_m5_delta_btc:null,complete_cvd_btc:null};
}
export function markSubscribed(state,atMs) {
  if(!Number.isSafeInteger(atMs)||atMs<state.started_ms)throw Error("bad_subscribe_time");
  if(state.phase==="subscribed")return state;
  state.phase="subscribed";
  state.connection_started_ms=atMs;
  state.last_message_ms=atMs;
  return state;
}
export function markInterrupted(state,atMs,reason) {
  if(!Number.isSafeInteger(atMs))throw Error("bad_interrupt");
  state.phase="disconnected";
  state.interruptions.push({at_ms:atMs,reason:String(reason).slice(0,100)});
  state.interruptions=state.interruptions.slice(-100);
  state.status="gap_known";
  return state;
}
export function acceptTrades(state,rawTrades,multiplierBTC,nowMs) {
  if(!Array.isArray(rawTrades))throw Error("expected_trades");
  if(!Number.isSafeInteger(nowMs))throw Error("bad_time");
  if(state.phase!=="subscribed")return state;
  const seen=new Set(state.ids);
  for(const item of rawTrades){
    const t=parseTrade(item,multiplierBTC);
    if(!t || t.ts>nowMs+MAX_CLOCK_DRIFT_MS || nowMs-t.ts>120000) {
      state.invalid++;continue;
    }
    if(seen.has(t.id)){state.duplicates++;continue;}
    if(seen.size>=MAX_IDS){
      state.overflow=true;markInterrupted(state,nowMs,"dedupe_capacity_exceeded");break;
    }
    seen.add(t.id);state.ids.push(t.id);
    const start=Math.floor(t.ts/M5_MS)*M5_MS;
    let b=state.buckets.find(x=>x.start_ms===start);
    if(!b) {
      b=emptyBucket(start);state.buckets.push(b);
      state.buckets.sort((a,b)=>a.start_ms-b.start_ms);
      if(state.buckets.length>MAX_BUCKETS)state.buckets.shift();
    }
    b.trades++;
    const btc=Math.abs(t.signedBTC);
    if(t.signedBTC>0)b.buy_btc+=btc;else b.sell_btc+=btc;
    b.volume_btc+=btc;
    b.signed_btc+=t.signedBTC;
    b.notional_usdt+=t.notionalUSDT;
    state.last_trade_ms=Math.max(state.last_trade_ms??0,t.ts);
    state.last_id=t.id;
    state.processed++;
  }
  state.last_message_ms=nowMs;
  return state;
}
export function snapshot(state,nowMs) {
  if(!Number.isSafeInteger(nowMs))throw Error("bad_time");
  const clean=state.buckets.map(b=>{
    // A session must predate the bar and survive past its close; however,
    // a stable socket does not prove upstream exchange data completeness.
    const connection_observed=state.connection_started_ms!==null
      && state.connection_started_ms<=b.start_ms
      && state.phase==="subscribed"
      && state.last_message_ms!==null
      && state.last_message_ms>=b.end_ms
      && state.interruptions.every(g=>g.at_ms>b.end_ms||g.at_ms<b.start_ms)
      && !state.overflow && state.invalid===0;
    const past=nowMs>=b.end_ms+GRACE_MS;
    return {start_ms:b.start_ms,end_ms:b.end_ms,
      trades:b.trades,buy_btc:rounded(b.buy_btc),
      sell_btc:rounded(b.sell_btc),volume_btc:rounded(b.volume_btc),
      delta_btc_observed:rounded(b.signed_btc),
      notional_usdt_observed:Math.round(b.notional_usdt*100)/100,
      closed:past,
      connection_window_observed:past&&connection_observed,
      coverage:"websocket_observation_not_exchange_sequence_verified",
      complete_delta_btc:null,complete_cvd_btc:null};
  });
  return {schema_version:"1.0",source:"OKX BTC-USDT-SWAP",
    instrument:INSTRUMENT,classification:"uncertified_websocket_market_observations",
    generated_ms:nowMs,phase:state.phase,
    total_unique_trades:state.processed,
    duplicate_trades:state.duplicates,invalid_trades:state.invalid,
    dedupe_overflow:state.overflow,
    interruptions:state.interruptions,
    observed_m5:clean,
    completeness_verified:false,
    complete_m5_delta_btc:null,complete_cvd_btc:null,
    delta_m15_btc:null,delta_h1_btc:null,delta_h4_btc:null,
    trade_signal:null,entry_signal:false};
}
