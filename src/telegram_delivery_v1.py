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

def paper_candidate(row, now):
    """Only prospectively admitted, unexpired pending simulations."""
    import math
    if not isinstance(row,dict) or row.get("source")!="OKX BTC-USDT-SWAP" or row.get("paper_only") is not True or row.get("status")!="pending":
        return None
    d=row.get("direction"); ident=row.get("id")
    issued=stamp(row.get("issued_at_utc"))
    if d not in ("long","short") or not isinstance(ident,str) or not re.fullmatch(r"[a-f0-9]{24}",ident) or not issued or not 0<=(now-issued).total_seconds()<=420:
        return None
    expiry=row.get("expires_at"); start=row.get("eligible_from")
    if type(expiry) is not int or type(start) is not int or expiry!=start+900 or not now.timestamp()<expiry:
        return None
    e,s,t,c=(row.get(k) for k in ("entry","stop_loss","take_profit","cost_bps"))
    if not all(type(v) in (int,float) and math.isfinite(v) and v>0 for v in (e,s,t,c)):
        return None
    if not (s<e<t if d=="long" else t<e<s):
        return None
    cost=e*c/10000
    rr=(abs(t-e)-cost)/(abs(e-s)+cost)
    if rr<2:
        return None
    from zoneinfo import ZoneInfo
    clock=dt.datetime.fromtimestamp(expiry,dt.timezone.utc).astimezone(ZoneInfo("Europe/Warsaw")).strftime("%H:%M")
    return {"id":ident,"text":f"BTC PAPER {d.upper()} | симуляція, не реальна угода\nEntry: {e:.2f} | SL: {s:.2f} | TP: {t:.2f}\nRR після витрат 1:{rr:.2f} | ліміт до {clock} PL."}


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
        if not isinstance(previous,dict):
            raise ValueError("invalid_state")
        paper_ids=previous.setdefault("paper_ids",[])
        if not isinstance(paper_ids,list):
            raise ValueError("invalid_state")
        if os.environ.get("BTC_TELEGRAM_PAPER_READY")=="1":
            rows=load(DATA/"BTC-forward-paper-journal-v1.json")
            if not isinstance(rows,list):
                raise ValueError("invalid_journal")
            for row in rows:
                paper=paper_candidate(row,now)
                if paper and paper["id"] not in paper_ids:
                    message_id=send(token,chat,paper["text"])
                    paper_ids.append(paper["id"])
                    previous["last_paper_message_id"]=message_id
                    previous["accepted_at_utc"]=now.isoformat()
                    save(STATE,previous)
                    print("Telegram API accepted PAPER message; handset receipt unverified")
        if os.environ.get("BTC_TELEGRAM_WATCH_READY")!="1":
            return
        feed=load(DATA/"BTC-report-feed.json")
        item=candidate(feed,now)
        if item is None:
            # Only a fresh, explicit neutral observation resets the episode.
            o=feed.get("okx_spot_persistence") or {}
            end=o.get("end_ms")
            if (o.get("source")=="OKX BTC-USDT" and o.get("status")=="observed"
                and o.get("direction") is None and type(end) is int
                and 0<=now.timestamp()*1000-end<=420000 and end>previous.get("end_ms",0)):
                previous.update(direction=None,end_ms=end)
                save(STATE,previous)
            print("No fresh validated WATCH")
            return
        if previous.get("source")==item["source"] and previous.get("direction")==item["direction"]:
            print("Unchanged WATCH suppressed")
            return
        if item["end_ms"]<=previous.get("end_ms",0):
            print("Old observation suppressed")
            return
        message_id=send(token,chat,item["text"])
        previous.update(source=item["source"],direction=item["direction"],end_ms=item["end_ms"],
                        provider_message_id=message_id,accepted_at_utc=now.isoformat())
        save(STATE,previous)
        print("Telegram API accepted WATCH message; handset receipt unverified")
    except Exception as exc:
        # Never log exception strings: HTTP errors may contain credential URLs.
        print("Telegram adapter failed:",type(exc).__name__)
        raise SystemExit(1) from None

if __name__=="__main__":
    main()
