// Durable TradingView -> GitHub inbox. No external incoming URL and no trading.
// A 202 means the event was durably queued, NOT that GitHub has processed it.
// GitHub dispatch happens from Durable Object alarms with bounded retries.
const OWNER="ivanovmaksim4646";
const REPO="-BTC-Intelligence-System.";
const WORKFLOW="tradingview-intelligence.yml";
const URL=`https://api.github.com/repos/${encodeURIComponent(OWNER)}/${encodeURIComponent(REPO)}/actions/workflows/${WORKFLOW}/dispatches`;
const MAX_PENDING=200;
const MAX_ATTEMPTS=8;
const RETENTION_MS=24*60*60*1000;
const MAX_DEAD=30;
const MAX_BATCH=8;

function keyFor(alert) {
  // All fields already strictly checked at the HTTP edge; key intentionally
  // excludes optional prices/volume, as duplicates can be sent with jitter.
  return [alert.source,alert.event,alert.symbol,alert.timeframe,alert.time_ms].join("|");
}
function blank() {
  return {pending:[],seen:{},dead:[],dispatched:0,lastDispatchAt:null,lastError:null};
}
export class TradingViewInbox {
  constructor(ctx,env) {this.ctx=ctx;this.env=env;}
  async load() {
    const data=await this.ctx.storage.get("inbox_v1");
    return data && Array.isArray(data.pending) && data.seen && typeof data.seen==="object" ? data : blank();
  }
  async fetch(request) {
    const path=new URL(request.url).pathname;
    if(path==="/status" && request.method==="GET") {
      const state=await this.load();
      return Response.json({status:"ok",pending:state.pending.length,
        dead_letters:state.dead.length,accepted_dispatched:state.dispatched,
        last_dispatch_utc:state.lastDispatchAt,last_error:state.lastError,
        guarantee:"durable_acceptance_not_GitHub_completion",
        trade_signal:null},{headers:{"Cache-Control":"no-store"}});
    }
    if(path!=="/enqueue" || request.method!=="POST")return new Response("Not found",{status:404});
    let event;
    try{event=await request.json();}catch{return Response.json({error:"invalid_json"},{status:400});}
    if (!event || !["btc-intelligence-tv-v1","btc-intelligence-tv-v2"].includes(event.source) ||
        typeof event.event!=="string" || typeof event.symbol!=="string" ||
        !Number.isSafeInteger(event.time_ms)) {
      return Response.json({error:"invalid_event"},{status:400});
    }
    const token=this.env.GITHUB_DISPATCH_TOKEN;
    // Do not accept an event we cannot even attempt to dispatch.
    if(!token) return Response.json({error:"missing_dispatch_token"},{status:503});
    const key=keyFor(event),now=Date.now();
    const state=await this.load();
    for(const [id,timestamp] of Object.entries(state.seen)) {
      if(now-timestamp>RETENTION_MS)delete state.seen[id];
    }
    if(Object.hasOwn(state.seen,key)) {
      // Re-arm alarm if a previous enqueue transaction partially succeeded.
      if(state.pending.length && (await this.ctx.storage.getAlarm())===null)
        await this.ctx.storage.setAlarm(now+100);
      return Response.json({accepted:true,duplicate:true,queued:true},{status:202});
    }
    if(state.pending.length>=MAX_PENDING)
      return Response.json({error:"durable_inbox_full"},{status:503});
    state.pending.push({key,event,attempts:0,notBefore:now,acceptedAt:now});
    state.seen[key]=now;
    // Return 202 only AFTER durable write and alarm have succeeded.
    await this.ctx.storage.put("inbox_v1",state);
    if((await this.ctx.storage.getAlarm())===null)
      await this.ctx.storage.setAlarm(now+100);
    return Response.json({accepted:true,duplicate:false,queued:true},{status:202});
  }
  async alarm() {
    const state=await this.load();
    const now=Date.now();
    let processed=0;
    while(state.pending.length && processed<MAX_BATCH) {
      // Unlike a single blocked head, retryable failures rotate to tail.
      const readyIndex=state.pending.findIndex(x=>x.notBefore<=Date.now());
      if(readyIndex===-1)break;
      const [item]=state.pending.splice(readyIndex,1);
      const token=this.env.GITHUB_DISPATCH_TOKEN;
      let status=0;
      try{
        if(!token)throw new Error("dispatch_token_missing");
        const resp=await fetch(URL,{method:"POST",headers:{
          Authorization:`Bearer ${token}`,
          Accept:"application/vnd.github+json",
          "X-GitHub-Api-Version":"2022-11-28",
          "User-Agent":"btc-intelligence-tv-durable-inbox"
        },body:JSON.stringify({ref:"main",inputs:{tv_payload:JSON.stringify(item.event)}}),
          signal:AbortSignal.timeout(15000)});
        status=resp.status;
        if(!resp.ok)throw new Error("github_dispatch_http_"+status);
        state.dispatched++;
        state.lastDispatchAt=new Date().toISOString();
        state.lastError=null;
      }catch(ex){
        item.attempts++;
        const category=status?"github_http_"+status:
          ex?.name==="TimeoutError"?"github_timeout":"github_network_or_token";
        state.lastError=category;
        if(item.attempts>=MAX_ATTEMPTS){
          state.dead.push({key:item.key,acceptedAt:item.acceptedAt,
            failure:category,attempts:item.attempts});
          state.dead=state.dead.slice(-MAX_DEAD);
          // Retain seen key so TradingView's retries cannot create an endless loop.
        }else{
          const pause=Math.min(15*60*1000,2000*2**(item.attempts-1));
          item.notBefore=Date.now()+pause;
          state.pending.push(item);
        }
      }
      processed++;
      // Commit each dispatch result to avoid repeating an entire batch on a
      // later failure. GitHub workflow itself deduplicates by event identity.
      await this.ctx.storage.put("inbox_v1",state);
    }
    if(state.pending.length){
      const earliest=Math.min(...state.pending.map(x=>x.notBefore));
      await this.ctx.storage.setAlarm(Math.max(Date.now()+150,earliest));
    }
  }
}
