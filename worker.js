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
const TV_EVENTS = new Set([
  "h1_inside_bar", "h1_sweep_high_reject", "h1_sweep_low_reclaim"
]);

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
  if (!alert || alert.source !== "btc-intelligence-tv-v1" ||
      !TV_EVENTS.has(alert.event) ||
      typeof alert.symbol !== "string" ||
      !/^(?:[A-Z0-9_]+:)?(?:BTC|XBT)[A-Z0-9_.]*$/i.test(alert.symbol) ||
      String(alert.timeframe) !== "5" ||
      !Number.isSafeInteger(alert.time_ms) ||
      Math.abs(Date.now() - alert.time_ms) > 15 * 60 * 1000 ||
      ![alert.price, alert.mother_high, alert.mother_low, alert.inside_high, alert.inside_low].every(
        x => typeof x === "number" && Number.isFinite(x) && x > 0
      ) ||
      alert.mother_high <= alert.mother_low ||
      alert.inside_high >= alert.mother_high ||
      alert.inside_low <= alert.mother_low ||
      alert.inside_high <= alert.inside_low) {
    return new Response("Invalid alert", { status: 400 });
  }
  const token = env.GITHUB_DISPATCH_TOKEN;
  if (!token) return new Response("Dispatcher not configured", { status: 503 });
  const payload = {
    source: alert.source, event: alert.event, symbol: alert.symbol,
    timeframe: "5", time_ms: alert.time_ms, price: alert.price,
    mother_high: alert.mother_high, mother_low: alert.mother_low,
    inside_high: alert.inside_high, inside_low: alert.inside_low
  };
  const url = `https://api.github.com/repos/${encodeURIComponent(GITHUB_OWNER)}/${encodeURIComponent(GITHUB_REPO)}/actions/workflows/tradingview-intelligence.yml/dispatches`;
  const response = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "btc-intelligence-tv-webhook"
    },
    body: JSON.stringify({ ref: "main", inputs: { tv_payload: JSON.stringify(payload) } })
  });
  if (!response.ok) {
    // GitHub error bodies may contain sensitive diagnostics; never echo them.
    const category = response.status === 401 ? "invalid_dispatch_token"
      : response.status === 403 ? "dispatch_permission_denied"
      : response.status === 404 ? "repository_or_workflow_not_found"
      : response.status === 422 ? "invalid_dispatch_request"
      : response.status === 429 ? "github_rate_limit"
      : "github_dispatch_error";
    console.error("TradingView webhook: GitHub rejected dispatch", {
      status: response.status, category, workflow: "tradingview-intelligence.yml"
    });
    return Response.json({ error: category, upstream_http_status: response.status },
      { status: 502, headers: { "Cache-Control": "no-store" } });
  }
  console.log("TradingView webhook accepted", payload.event, payload.symbol, payload.time_ms);
  return Response.json({accepted: true}, { status: 202 });
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
    return new Response("BTC Intelligence scheduler: use Cron Trigger", { status: 200 });
  }
};
