"""Optional Telegram delivery adapter. No trading, no credentials in files."""
from __future__ import annotations
import datetime as dt
import json
import os
import re
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
STATE = ROOT / "state" / "telegram-delivery-v1.json"
MAX_AGE = 900

def stamp(value):
    try:
        x = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return x if x.utcoffset() is not None else None
    except (AttributeError, TypeError, ValueError):
        return None

def candidate(feed, now):
    """Emit fresh experimental observations, never a paper entry."""
    if not isinstance(feed, dict):
        return None
    generated = stamp(feed.get("generated_at_utc"))
    if not generated or not 0 <= (now-generated).total_seconds() <= MAX_AGE:
        return None
    okx = feed.get("okx_spot_persistence") or {}
    end = okx.get("end_ms")
    direction = okx.get("direction")
    blocks = okx.get("blocks")
    if (okx.get("source") == "OKX BTC-USDT" and okx.get("status") == "observed"
        and okx.get("coverage") == "volume_reconciled_not_sequence_certified"
        and direction in ("WATCH LONG", "WATCH SHORT") and type(end) is int
        and end % 300000 == 0 and 0 <= now.timestamp()*1000-end <= 420000
        and isinstance(blocks, list) and len(blocks) == 4):
        sign = 1 if direction == "WATCH LONG" else -1
        import math
        for i, block in enumerate(blocks):
            if (not isinstance(block,dict) or block.get("end_ms") != end-(3-i)*900000
                or any(type(block.get(k)) not in (int,float) or not math.isfinite(block[k])
                       for k in ("pressure","delta_btc","price_return"))
                or abs(block["pressure"])>1):
                return None
        if not all(sign*b["pressure"]>0.1 for b in blocks[-2:]):
            return None
        aligned = all(sign*b["price_return"]>0 for b in blocks[-2:])
        local = dt.datetime.fromtimestamp(end/1000,dt.timezone.utc)
        from zoneinfo import ZoneInfo
        clock = local.astimezone(ZoneInfo("Europe/Warsaw")).strftime("%d.%m %H:%M")
        return {"source":"OKX Spot","direction":direction,"end_ms":end,
                "text":f"BTC {direction} | {clock} PL\nOKX Spot: Delta M15 {blocks[-1]['delta_btc']:+.2f} BTC; тиск 2×M15.\nЦіна: {'підтверджує напрям' if aligned else 'реакція неоднозначна'}. WATCH, не вхід."}
    return None

def load(path):
    return json.loads(path.read_text(encoding="utf-8"))

def save(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp=path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    tmp.replace(path)

def send(token, chat_id, message, opener=urlopen):
    if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+",token) or not re.fullmatch(r"-?[0-9]+",chat_id):
        raise ValueError("invalid_credentials_format")
    req=Request("https://api.telegram.org/bot"+token+"/sendMessage",
                data=json.dumps({"chat_id":chat_id,"text":message}).encode(),
                headers={"Content-Type":"application/json"},method="POST")
    with opener(req,timeout=10) as response:
        payload=json.load(response)
    if payload.get("ok") is not True or type((payload.get("result") or {}).get("message_id")) is not int:
        raise ValueError("provider_not_confirmed")
    return payload["result"]["message_id"]

def main():
    if os.environ.get("BTC_TELEGRAM_ENABLED")!="1":
        print("Telegram disabled; no request")
        return
    token=os.environ.get("BTC_TELEGRAM_BOT_TOKEN","")
    chat=os.environ.get("BTC_TELEGRAM_CHAT_ID","")
    if not token or not chat:
        print("Telegram not configured; no request")
        return
    now=dt.datetime.now(dt.timezone.utc)
    try:
        previous=load(STATE) if STATE.exists() else {}
        item=candidate(load(DATA/"BTC-report-feed.json"),now)
        if item is None:
            print("No fresh validated WATCH")
            return
        if not isinstance(previous,dict):
            raise ValueError("invalid_state")
        if previous.get("source")==item["source"] and previous.get("direction")==item["direction"]:
            print("Unchanged WATCH suppressed")
            return
        if item["end_ms"]<=previous.get("end_ms",0):
            print("Old observation suppressed")
            return
        message_id=send(token,chat,item["text"])
        save(STATE,{"source":item["source"],"direction":item["direction"],"end_ms":item["end_ms"],
                    "provider_message_id":message_id,"accepted_at_utc":now.isoformat()})
        print("Telegram API accepted message; handset receipt unverified")
    except Exception as exc:
        # Never log exception strings: HTTP errors may contain credential URLs.
        print("Telegram adapter failed:",type(exc).__name__)
        raise SystemExit(1) from None

if __name__=="__main__":
    main()
