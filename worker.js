// Cloudflare Cron -> Durable Object -> GitHub Actions workflow_dispatch.
// Never store credentials in source control. Set GITHUB_DISPATCH_TOKEN with Wrangler secret.
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
  async fetch() {
    return new Response("BTC Intelligence scheduler: use Cron Trigger", { status: 200 });
  }
};
