import { TradingViewInbox } from "./cloudflare/tradingview-inbox.mjs";
export { TradingViewInbox };
// Cloudflare Cron -> Durable Object -> GitHub Actions workflow_dispatch.
// Never store credentials in source control. Set GITHUB_DISPATCH_TOKEN with Wrangler secret.
// Deployment uses the CLOUDFLARE_API_TOKEN repository secret; rotating it requires a new deployment to verify access.
const GITHUB_OWNER = "ivanovmaksim4646";
const GITHUB_REPO = "-BTC-Intelligence-System.";
const WORKFLOW = "btc-intelligence.yml";
const MAX_SLOT_AGE_MS = 15 * 60 * 1000;

export class DispatchLock {
  constructor(ctx, env) {
    this.ctx = ctx;
    this.env = env;
    this.inFlight = false;
  }
  async fetch(request) {
    if (request.method !== "POST") return new Response("Method not allowed", { status: 405 });
    if (this.inFlight) return Response.json({ status: "in_flight" }, { status: 409 });
    this.inFlight = true;
    try {
      const { slot } = await request.json();
      if (!Number.isInteger(slot) || slot % 300000 !== 0 || Math.abs(Date.now() - slot) > MAX_SLOT_AGE_MS) {
        return Response.json({ error: "invalid_or_stale_slot" }, { status: 400 });
      }
      const lastSlot = await this.ctx.storage.get("last_success_slot");
      if (typeof lastSlot === "number" && slot <= lastSlot) {
        return Response.json({ status: "already_dispatched", slot });
      }
      const token = this.env.GITHUB_DISPATCH_TOKEN;
      if (!token) return Response.json({ error: "dispatch_token_not_configured" }, { status: 503 });
      const url = `https://api.github.com/repos/${encodeURIComponent(GITHUB_OWNER)}/${encodeURIComponent(GITHUB_REPO)}/actions/workflows/${encodeURIComponent(WORKFLOW)}/dispatches`;
      const response = await fetch(url, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "User-Agent": "btc-intelligence-cloudflare-scheduler"
        },
        body: JSON.stringify({ ref: "main", inputs: { slot: new Date(slot).toISOString(), source: "cloudflare" } })
      });
      if (!response.ok) {
        console.error("GitHub dispatch failed", response.status);
        return Response.json({ error: "github_dispatch_failed", http_status: response.status }, { status: 502 });
      }
      await this.ctx.storage.put("last_success_slot", slot);
      console.log("Dispatched workflow", new Date(slot).toISOString());
      return Response.json({ status: "dispatched", slot });
    } finally {
      this.inFlight = false;
    }
  }
}

// TradingView alert receiver. Only official webhook origin IPs may submit data.
// Read-only market intelligence: NEVER executes trades.
const TV_ALLOWED_IPS = new Set([
  "52.89.214.238", "34.212.75.30", "54.218.53.128", "52.32.178.7"
]);
const TV_EVENTS_V1 = new Set([
  "h1_inside_bar", "h1_sweep_high_reject", "h1_sweep_low_reclaim"
]);
const TV_LEVEL_KINDS_V2 = Object.freeze({
  m5_bullish_bos: "pivot_high",
  m5_bearish_bos: "pivot_low",
  m5_bullish_shift: "pivot_high",
  m5_bearish_shift: "pivot_low",
  m5_bullish_fvg: "fvg_upper",
  m5_bearish_fvg: "fvg_lower",
  m5_sweep_pdh: "pdh",
  m5_sweep_pdl: "pdl"
});
function btcPrice(value) {
  return typeof value === "number" && Number.isFinite(value) && value > 0 && value < 1e8;
}
function validateTradingViewAlert(alert) {
  if (!alert || typeof alert !== "object" || Array.isArray(alert) ||
      typeof alert.symbol !== "string" ||
      !/^(?:[A-Z0-9_]+:)?(?:BTC|XBT)[A-Z0-9_.]*$/i.test(alert.symbol) ||
      String(alert.timeframe) !== "5" ||
      !Number.isSafeInteger(alert.time_ms) ||
      Math.abs(Date.now() - alert.time_ms) > 15 * 60 * 1000 ||
      !btcPrice(alert.price)) return false;
  const base = ["source", "event", "symbol", "timeframe", "time_ms", "price"];
  let fields;
  if (alert.source === "btc-intelligence-tv-v1" && TV_EVENTS_V1.has(alert.event)) {
    fields = [...base, "mother_high", "mother_low", "inside_high", "inside_low"];
    if (![alert.mother_high, alert.mother_low, alert.inside_high, alert.inside_low].every(btcPrice) ||
        !(alert.mother_low < alert.inside_low && alert.inside_low < alert.inside_high &&
          alert.inside_high < alert.mother_high)) return false;
  } else if (alert.source === "btc-intelligence-tv-v2" &&
             Object.hasOwn(TV_LEVEL_KINDS_V2, alert.event)) {
    fields = [...base, "level", "level_kind", "volume"];
    if (!btcPrice(alert.level) || alert.level_kind !== TV_LEVEL_KINDS_V2[alert.event] ||
        typeof alert.volume !== "number" || !Number.isFinite(alert.volume) ||
        alert.volume < 0) return false;
  } else return false;
  return Object.keys(alert).length === fields.length &&
         fields.every(key => Object.hasOwn(alert, key));
}

async function receiveTradingView(request, env) {
  if (request.method !== "POST") return new Response("Method not allowed", { status: 405 });
  const ip = request.headers.get("CF-Connecting-IP");
  if (!TV_ALLOWED_IPS.has(ip)) return new Response("Forbidden", { status: 403 });
  if (Number(request.headers.get("content-length") || 0) > 2048) {
    return new Response("Payload too large", { status: 413 });
  }
  let alert;
  try {
    const raw = await request.text();
    if (raw.length > 2048) return new Response("Payload too large", { status: 413 });
    alert = JSON.parse(raw);
  } catch {
    return new Response("Invalid JSON", { status: 400 });
  }
  if (!validateTradingViewAlert(alert)) {
    return new Response("Invalid alert", { status: 400 });
  }
  const id=env.TV_INBOX.idFromName("btc-tradingview-alerts-v1");
  const stub=env.TV_INBOX.get(id);
  // TradingView has a 3-second deadline. Persist to DO and return immediately
  // instead of waiting for GitHub Actions / external network.
  try {
    const response=await stub.fetch("https://tv-inbox.internal/enqueue",{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify(alert)
    });
    if(!response.ok){
      console.error("TradingView durable inbox unavailable",response.status);
      return Response.json({error:"inbox_unavailable"},{status:503,headers:{"Cache-Control":"no-store"}});
    }
    const accepted=await response.json();
    return Response.json(accepted,{status:202,headers:{"Cache-Control":"no-store"}});
  }catch(ex){
    console.error("TradingView inbox request failed",ex?.name||"error");
    return Response.json({error:"inbox_unavailable"},{status:503,headers:{"Cache-Control":"no-store"}});
  }
}

export default {
  async scheduled(controller, env, ctx) {
    const slot = Math.floor(controller.scheduledTime / 300000) * 300000;
    const id = env.DISPATCH_LOCK.idFromName("btc-intelligence");
    const stub = env.DISPATCH_LOCK.get(id);
    ctx.waitUntil((async () => {
      const result = await stub.fetch("https://dispatch.internal/dispatch", {
        method: "POST",
        body: JSON.stringify({ slot }),
        headers: { "content-type": "application/json" }
      });
      if (!result.ok) throw new Error(`BTC dispatch failed: HTTP ${result.status}`);
    })());
  },
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/tv-webhook") return receiveTradingView(request, env);
    if (url.pathname === "/tv-queue-health" && request.method === "GET") {
      const id=env.TV_INBOX.idFromName("btc-tradingview-alerts-v1");
      try {
        return await env.TV_INBOX.get(id).fetch("https://tv-inbox.internal/status");
      }catch{
        return Response.json({status:"unavailable"},{status:503});
      }
    }
    return new Response("BTC Intelligence scheduler: use Cron Trigger", { status: 200 });
  }
};
