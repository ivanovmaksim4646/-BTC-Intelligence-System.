"""Pre-entry OHLC context only; no order-book or executed-flow claims."""
from datetime import datetime,timezone
try:
    from src.okx_market_context_v1 import confirmed_pivots
except ModuleNotFoundError:
    from okx_market_context_v1 import confirmed_pivots

def trend(bars):
    hi,lo=confirmed_pivots(bars)
    if len(hi)<2 or len(lo)<2:return "insufficient"
    a,b=hi[-2]["price"],hi[-1]["price"]
    c,d=lo[-2]["price"],lo[-1]["price"]
    return "bullish" if b>a and d>c else "bearish" if b<a and d<c else "mixed"

def sweep(bars,direction,lookback=12):
    # Pivot must have been confirmed before the sweeping candle opened.
    for i in range(max(5,len(bars)-lookback),len(bars)):
        h,l=confirmed_pivots(bars[:i])
        pivots=l if direction=="long" else h
        if not pivots:continue
        p=pivots[-1]["price"];b=bars[i]
        if direction=="long" and b["l"]<p<b["c"]:return True
        if direction=="short" and b["h"]>p>b["c"]:return True
    return False

def context(entry,frames):
    close=entry["entry_close_utc"];direction=entry["direction"]
    steps={"5m":300,"1h":3600,"4h":14400,"1d":86400}
    for tf,step in steps.items():
        b=frames[tf]
        if not b or any(x["t"]+step>close for x in b):
            raise ValueError("future or missing context")
    states={tf:trend(frames[tf]) for tf in ("1h","4h","1d")}
    wanted="bullish" if direction=="long" else "bearish"
    hour=datetime.fromtimestamp(close,timezone.utc).hour
    session="asia_utc_00_08" if hour<8 else "london_utc_08_13" if hour<13 else "ny_utc_13_21" if hour<21 else "late_utc"
    return {"structure":states,"h1_h4_aligned":states["1h"]==states["4h"]==wanted,
        "d1_aligned":states["1d"]==wanted,"recent_m5_sweep":sweep(frames["5m"],direction),
        "utc_session_bucket":session,"orderflow":None,"orderbook":None,
        "classification":"closed_ohlc_context_only"}

def cohorts(entries):
    # Fixed hypotheses, not optimized from outcomes.
    return {"baseline":entries,
      "h1_h4_alignment":[e for e in entries if e["context"]["h1_h4_aligned"]],
      "recent_sweep":[e for e in entries if e["context"]["recent_m5_sweep"]],
      "alignment_and_sweep":[e for e in entries if e["context"]["h1_h4_aligned"] and e["context"]["recent_m5_sweep"]],
      "d1_alignment":[e for e in entries if e["context"]["d1_aligned"]]}
