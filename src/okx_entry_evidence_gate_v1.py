#!/usr/bin/env python3
"""OKX-only closed-candle evidence gate for POI -> QM retest -> prior swing TP.

Never create an entry based only on alert flags. Reconstructs every candidate
from timestamped OKX M5 and HTF OHLC, exact observed OKX TradingView venue,
chronological FVG, touch, QM and confirmed shoulder retest. Opposing target is
a confirmed pre-entry HTF swing, independent of desired RR. This is a
PAPER HYPOTHESIS, not an order or a fill. No trading account access.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import json
from pathlib import Path
try:
    from src.binance_poi_qm_v1 import fvg_zones,overlaps
    from src.strategy_models_v1 import scan_qm, scan_ifvg
    from src.okx_market_context_v1 import fresh_structure_break
    from src.okx_outcome_tracker_v1 import check_bar,canonical,VENUE
    from src.rr_outcome_research_v1 import valid_number
except ModuleNotFoundError:
    from binance_poi_qm_v1 import fvg_zones,overlaps
    from strategy_models_v1 import scan_qm, scan_ifvg
    from okx_market_context_v1 import fresh_structure_break
    from okx_outcome_tracker_v1 import check_bar,canonical,VENUE
    from rr_outcome_research_v1 import valid_number

DATA=Path(__file__).resolve().parents[1]/"data"
OUT=DATA/"BTC-okx-entry-evidence-gate-v1.json"
ENTRY_JOURNAL=DATA/"BTC-okx-validated-paper-entries-v1.jsonl"
MAX_FRESH_AGE=15*60
M5=300
HTF_SECONDS={"1h":3600,"4h":14400}
COST_ESTIMATE_BPS=14

def fresh(iso,now,seconds=MAX_FRESH_AGE):
    try:
        date=dt.datetime.fromisoformat(iso.replace("Z","+00:00"))
        return date.tzinfo is not None and 0<=(now-date).total_seconds()<=seconds
    except (ValueError,TypeError,AttributeError):return False

def confirmed_pivots(bars,tf_seconds,direction,at):
    """Prior opposite-liquidity pivots confirmed with 2 right-side closed bars."""
    out=[]
    for i in range(2,len(bars)-2):
        p=bars[i]
        confirmation=bars[i+2]["t"]+tf_seconds
        if confirmation>at:continue
        if direction=="long":
            val=p["h"]
            ok=all(val>bars[j]["h"] for j in range(i-2,i+3) if j!=i)
        else:
            val=p["l"]
            ok=all(val<bars[j]["l"] for j in range(i-2,i+3) if j!=i)
        if ok:out.append({"level":val,"pivot_at":p["t"],"confirmed_at":confirmation})
    return out

def chronological_break(bars,head,extreme,retest_open,direction):
    """Reconstruct candidate breaks using only information available at each close."""
    if direction not in ("long","short") or not head<extreme<retest_open:
        return None
    prefix="bullish" if direction=="long" else "bearish"
    latest=None
    for i,bar in enumerate(bars):
        if not head<bar["t"] or bar["t"]+M5>retest_open:
            continue
        event=fresh_structure_break(bars[:i+1],"5m")
        if event is None:
            continue
        if not event["kind"].startswith(prefix):
            latest=None
        elif bar["t"]<=extreme:
            latest=event
    return latest

def prior_poi_zones(bars,step,head,direction):
    """Only HTF candles closed before QM head; IFVG usable after inversion closes."""
    prior=[b for b in bars if b["t"]+step<=head]
    zones=[dict(p,kind="FVG",available_at=p["formed"]+step)
           for p in fvg_zones(prior) if p["direction"]==direction]
    zones.extend({"direction":direction,"low":p["low"],"high":p["high"],
                  "formed":p["formed_at"],"kind":"IFVG",
                  "available_at":p["inverted_at"]+step}
                 for p in scan_ifvg(prior) if p["direction"]==direction)
    # Never reuse a zone invalidated by a later HTF close before the head.
    return [p for p in zones if p["available_at"]<=head and not any(
        (b["c"]<p["low"] if direction=="long" else b["c"]>p["high"])
        for b in prior if b["t"]>=p["available_at"])]

def evaluate(snapshot,observations,now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    if now.utcoffset() is None:raise ValueError("timezone-aware now required")
    report={"schema_version":"1.0","generated_at_utc":now.isoformat(),
       "classification":"independently_reconstructed_okx_paper_hypotheses",
       "source":VENUE,"decision":"NO_TRADE","trade_signal":None,
       "candidates_evaluated":0,"paper_entries":[],"reasons":[],
       "diagnostics":{"latest_m5_close_s":None,"matching_tv_events":0,
          "qm_patterns":0,"direction_matched_qm":0,"confirmed_qm":0,
          "first_retest_matches":0,"directional_break_matches":0,
          "eligible_poi_zones":0,"poi_touches":0,"poi_not_invalidated":0,
          "valid_stop":0,"target_matches":0,"net_rr_matches":0},
       "policy":{"risk_fraction_cap":0.01,"leverage_cap":5,
          "entry":"closed_M5_retest_close_only",
          "stop":"QM_head_extreme_with_outward_3bps",
          "target":"pre_entry_confirmed_opposing_HTF_swing",
          "requires_TV_OKX_observation":True,
          "requires_directional_bos_or_shift_after_qm_head":True,
          "execution":"not_executed"}}
    frames=(snapshot or {}).get("timeframes") if isinstance(snapshot,dict) else None
    if (not isinstance(snapshot,dict) or snapshot.get("source")!=VENUE
        or snapshot.get("status")!="verified" or not fresh(snapshot.get("collected_at_utc"),now)
        or not isinstance(frames,dict)):
        report["reasons"].append("missing_or_stale_verified_okx_candles")
        return report
    wanted=("5m","1h","4h")
    for tf in wanted:
        f=frames.get(tf)
        if not isinstance(f,dict) or f.get("status")!="ok" or len(f.get("bars") or [])<30:
            report["reasons"].append("missing_"+tf)
            return report
        bars=f["bars"]
        if not all(check_bar(x) for x in bars):
            report["reasons"].append("invalid_closed_okx_"+tf)
            return report
        step=M5 if tf=="5m" else HTF_SECONDS[tf]
        if any(b["t"]%step for b in bars) or any(bars[i]["t"]-bars[i-1]["t"]!=step for i in range(1,len(bars))):
            report["reasons"].append("gapped_okx_"+tf)
            return report
        if bars[-1]["t"]+step>now.timestamp():
            report["reasons"].append("forming_okx_candle_"+tf)
            return report
    obs=observations if isinstance(observations,list) else []
    m5=frames["5m"]["bars"]
    entry_bar=m5[-1]
    close=entry_bar["t"]+M5
    # Prefer newest confirmed M5 close; no backdating historical setup entries.
    if not 0<=now.timestamp()-close<=M5+60:
        report["reasons"].append("latest_m5_close_stale")
        return report
    diag=report["diagnostics"]
    diag["latest_m5_close_s"]=close
    corroborated=[o for o in obs if isinstance(o,dict)
         and o.get("source")==VENUE and o.get("status")=="observed_not_trade"
         and o.get("symbol")=="OKX:BTCUSDT.P"
         and o.get("event_close_ms")==close*1000
         and o.get("corroboration") in ("three_candle_fvg_consistent",
                                        "closed_candle_price_consistent_only")
         and o.get("side") in ("long","short")]
    diag["matching_tv_events"]=len(corroborated)
    qms=scan_qm(m5)
    diag["qm_patterns"]=len(qms)
    if not corroborated:
        report["reasons"].append("no_same_bar_independently_corroborated_okx_tv_alert")
        return report
    # Count each directional path once, regardless of multiple TV alerts.
    corroborated=sorted(corroborated,key=lambda o:str(o.get("event_id") or ""))
    corroborated=list({o["side"]:o for o in reversed(corroborated)}.values())
    for o in corroborated:
        direction=o["side"]
        for q in qms:
            if q.get("direction")!=direction:continue
            diag["direction_matched_qm"]+=1
            head=q.get("head_time");extreme=q.get("structural_extreme_time")
            shoulder=q.get("left_shoulder");head_price=q.get("head_extreme")
            if not all(valid_number(x) for x in (shoulder,head_price)):
                continue
            if type(head) is not int or type(extreme) is not int or not head<extreme<entry_bar["t"]:
                continue
            if entry_bar["t"]<extreme+3*M5:continue
            diag["confirmed_qm"]+=1
            if not (entry_bar["l"]<=shoulder<=entry_bar["h"] and
                abs(entry_bar["c"]-shoulder)/shoulder<=0.001 and
                (entry_bar["c"]>shoulder if direction=="long" else entry_bar["c"]<shoulder)):
                continue
            # First eligible retest after full structure confirmation must be
            # CURRENT closed candle; don't select a later convenient retest.
            first=[b for b in m5 if b["t"]>=extreme+3*M5 and b["t"]>head and
               b["l"]<=shoulder<=b["h"] and abs(b["c"]-shoulder)/shoulder<=0.001 and
               (b["c"]>shoulder if direction=="long" else b["c"]<shoulder)]
            if not first or first[0]["t"]!=entry_bar["t"]:continue
            diag["first_retest_matches"]+=1
            structure_break=chronological_break(m5,head,extreme,entry_bar["t"],direction)
            if structure_break is None:
                if "no_directional_bos_or_shift_in_qm_sequence" not in report["reasons"]:
                    report["reasons"].append("no_directional_bos_or_shift_in_qm_sequence")
                continue
            diag["directional_break_matches"]+=1
            report["candidates_evaluated"]+=1
            stop=head_price*(0.9997 if direction=="long" else 1.0003)
            entry=entry_bar["c"]
            if not ((stop<entry) if direction=="long" else (entry<stop)):continue
            diag["valid_stop"]+=1
            for tf in ("1h","4h"):
                ht=frames[tf]["bars"];step=HTF_SECONDS[tf]
                # HTF POI formed and CONFIRMED before touch; no future HTF.
                pois=prior_poi_zones(ht,step,head,direction)
                diag["eligible_poi_zones"]+=len(pois)
                for poi in pois:
                    touches=[b for b in m5 if poi["available_at"]<=b["t"]<head
                             and overlaps(b,poi["low"],poi["high"])]
                    if not touches:continue
                    diag["poi_touches"]+=1
                    # A close through the far edge after touch invalidates the POI.
                    if any((b["c"]<poi["low"] if direction=="long" else b["c"]>poi["high"])
                           for b in m5 if touches[0]["t"]<=b["t"]<=entry_bar["t"]):
                        continue
                    diag["poi_not_invalidated"]+=1
                    # Opposing TP pivot confirmed BEFORE entry. Must lie
                    # beyond entry in profit direction, and not be selected
                    # from bars formed after entry.
                    targets=confirmed_pivots(ht,step,direction,close)
                    targets=[p for p in targets if (p["level"]>entry if direction=="long"
                                                   else p["level"]<entry)]
                    if not targets:continue
                    diag["target_matches"]+=1
                    # Choose NEAREST already-confirmed profit-side swing,
                    # independent of desired RR and never manufacture a TP.
                    target=min(targets,key=lambda p:abs(p["level"]-entry))
                    tp=target["level"]
                    gross=abs(tp-entry)/abs(entry-stop)
                    # Use conservative proxy for net RR classification; actual
                    # account fee tier and market slippage still unverified.
                    risk=abs(entry-stop)+entry*COST_ESTIMATE_BPS/10000
                    reward=abs(tp-entry)-entry*COST_ESTIMATE_BPS/10000
                    net=reward/risk if risk>0 else -1
                    if net<1:continue
                    diag["net_rr_matches"]+=1
                    evidence={"htf":tf,"poi_formed":poi["formed"],
                         "poi_kind":poi["kind"],"poi_available_at":poi["available_at"],
                         "structure_break":structure_break,
                         "poi_low":poi["low"],"poi_high":poi["high"],
                         "poi_touch":touches[0]["t"],"qm_head":head,
                         "qm_extreme":extreme,"qm_head_price":head_price,
                         "shoulder":shoulder,"retest_open":entry_bar["t"],
                         "target_pivot":target["pivot_at"],
                         "target_confirmed":target["confirmed_at"],
                         "tv_event_id":o.get("event_id")}
                    ident=hashlib.sha256(canonical([VENUE,close,direction,evidence]).encode()).hexdigest()[:32]
                    record={"entry_id":"paper-"+ident,
                       "source":VENUE,"classification":"validated_paper_entry_only",
                       "execution":"not_executed","entry_signal":False,"trade_signal":None,
                       "independent_entry_validator":"okx_poi_qm_execution_validator_v1",
                       "venue_candle_close_verified":True,"independent_target_verified":True,
                       "direction":direction,"entry":entry,"stop_loss":round(stop,8),
                       "take_profit":tp,"entry_close_utc":close,
                       "risk_fraction":0.01,"leverage_cap":5,
                       "total_cost_bps":COST_ESTIMATE_BPS,
                       "model":"HTF_POI_QM_LTF",
                       "trading_session":None,"rr_gross":round(gross,4),
                       "rr_net_estimate":round(net,4),
                       "rr_category":"main_watchlist_candidate" if net>=2 else "research_only",
                       "evidence":evidence,"paper_only":True}
                    report["paper_entries"].append(record)
    # Multiple zones can explain the same directional M5 retest. Count one
    # paper hypothesis, choosing the nearest eligible opposing target, then
    # newest available POI and stable ID as deterministic tie breakers.
    unique={}
    for p in report["paper_entries"]:
        key=(p["source"],p["entry_close_utc"],p["direction"])
        rank=(abs(p["take_profit"]-p["entry"]),-p["evidence"]["poi_available_at"],p["entry_id"])
        old=unique.get(key)
        if old is None or rank<old[0]:
            unique[key]=(rank,p)
    report["paper_entries"]=[value[1] for value in unique.values()]
    if not report["paper_entries"]:
        report["reasons"].append("no_full_chronological_poi_qm_retest_and_preconfirmed_target")
    # Always NO_TRADE even if research hypothesis exists; no user account
    # balance, actual fee tier, contract precision or execution evidence.
    return report

def main():
    def read(name):
        try:return json.loads((DATA/name).read_text(encoding="utf-8"))
        except (OSError,ValueError):return {}
    obs=[]
    path=DATA/"BTC-okx-setup-observations-v1.jsonl"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines()[-200:]:
            try:obs.append(json.loads(line))
            except ValueError:pass
    report=evaluate(read("BTC-okx-futures-candles.json"),obs)
    existing=set()
    existing_keys=set()
    if ENTRY_JOURNAL.exists():
        for line in ENTRY_JOURNAL.read_text(encoding="utf-8").splitlines():
            try:
                row=json.loads(line)
                existing.add(row["entry_id"])
                existing_keys.add((row["source"],row["entry_close_utc"],row["direction"]))
            except (ValueError,KeyError,TypeError):pass
    new=[e for e in report["paper_entries"] if e["entry_id"] not in existing
         and (e["source"],e["entry_close_utc"],e["direction"]) not in existing_keys]
    if new:
        with ENTRY_JOURNAL.open("a",encoding="utf-8") as file:
            for e in new:file.write(canonical(e)+"\n")
    report["new_paper_entries"]=len(new)
    report["paper_entries_count"]=len(report.pop("paper_entries"))
    OUT.parent.mkdir(parents=True,exist_ok=True)
    t=OUT.with_suffix(".json.tmp")
    t.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    t.replace(OUT)
    print("OKX evidence gate:",report["new_paper_entries"],
          "new paper hypotheses; NO_TRADE; reasons",report["reasons"])

if __name__=="__main__":main()
