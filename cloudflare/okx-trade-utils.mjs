// Pure validation helpers for OKX WebSocket feed; no market orders.
export const INSTRUMENT = "BTC-USDT-SWAP";
export function parseTrade(item, multiplierBTC) {
  if (!item || item.instId !== INSTRUMENT || !["buy","sell"].includes(item.side)) return null;
  if (typeof item.tradeId !== "string" || !/^\d+$/.test(item.tradeId)) return null;
  const ts=Number(item.ts), sz=Number(item.sz), px=Number(item.px);
  if (!Number.isSafeInteger(ts) || ts<=0 ||
      !Number.isFinite(sz) || sz<=0 || !Number.isFinite(px) || px<=0 ||
      !Number.isFinite(multiplierBTC) || multiplierBTC<=0) return null;
  return {id:item.tradeId, ts, signedBTC:(item.side==="buy"?1:-1)*sz*multiplierBTC,
          notionalUSDT:sz*multiplierBTC*px};
}
export function eventType(payload) {
  if (!payload || typeof payload!=="object") return "invalid";
  if (payload.event==="subscribe" && payload.arg?.channel==="trades" &&
      payload.arg?.instId===INSTRUMENT) return "subscribed";
  if (payload.event==="error") return "error";
  if (payload.arg?.channel==="trades" && payload.arg?.instId===INSTRUMENT &&
      Array.isArray(payload.data)) return "trades";
  return "unrelated";
}
export function normalizeMetadata(rows) {
  if (!Array.isArray(rows)) return null;
  const eligible=rows.filter(x=>x?.instId===INSTRUMENT && x.ctValCcy==="BTC");
  if (eligible.length!==1) return null;
  const v=Number(eligible[0].ctVal);
  return Number.isFinite(v) && v>0 ? v : null;
}
