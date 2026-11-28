"""Standalone HTML with closed candles and recorded setup evidence for trade review."""
from datetime import datetime, timezone
from html import escape
from bisect import bisect_left

UTC = timezone.utc


def epoch(value):
    return int(datetime.fromisoformat(value).timestamp())


def panel(bars, levels, points, title, step):
    if not bars:
        return ""
    left,right,top,bottom = 45,825,25,232
    low = min([b.l for b in bars]+[v for _,v in levels])
    high = max([b.h for b in bars]+[v for _,v in levels])
    span = max(high-low,0.1)
    y = lambda v: bottom-(v-low)/span*(bottom-top)
    wid = (right-left)/len(bars)
    x = lambda t: left+(t-bars[0].t)/step*wid+wid/2
    result=[f'<h3>{escape(title)}</h3><svg viewBox="0 0 1040 270" role="img" aria-label="{escape(title)}">']
    for b in bars:
        cx=x(b.t);color="#008373" if b.c>=b.o else "#a43f52"
        result.append(f'<path stroke="{color}" d="M{cx:.2f} {y(b.h):.2f}V{y(b.l):.2f}"/>'
            f'<rect x="{cx-wid*.30:.2f}" y="{min(y(b.c),y(b.o)):.2f}" width="{wid*.60:.2f}" '
            f'height="{max(.8,abs(y(b.c)-y(b.o))):.2f}" fill="{color}"/>')
    for i,(name,v) in enumerate(levels):
        h=y(v); color=("#315a9c","#a54223","#0f7553","#795a84","#ac7430")[i%5]
        result.append(f'<path stroke="{color}" opacity=".7" stroke-dasharray="4 4" d="M{left} {h:.2f}H{right}"/>'
            f'<text fill="{color}" x="{right+12}" y="{18+i*23}">{escape(name)} {v:,.2f}</text>')
    for label,t,price in points:
        if bars[0].t<=t<bars[-1].t+step and low<=price<=high:
            result.append(f'<circle cx="{x(t):.2f}" cy="{y(price):.2f}" r="3" fill="#292952"/>'
                f'<text x="{x(t)+3:.2f}" y="{max(10,y(price)-5):.2f}">{escape(label)}</text>')
    for index in sorted({0,len(bars)//2,len(bars)-1}):
        b=bars[index]
        label=datetime.fromtimestamp(b.t,UTC).strftime("%m-%d %H:%M")
        result.append(f'<text text-anchor="middle" x="{x(b.t):.1f}" y="257">{label}</text>')
    return "".join(result)+"</svg>"


def render(path, bars, trades):
    times=[b.t for b in bars]
    doc=['<!doctype html><html lang="uk"><meta charset="utf-8"><title>BTCUSDT — перевірка входів</title>',
         '<meta name="viewport" content="width=device-width"><style>body{font:16px system-ui;max-width:1080px;margin:auto;padding:16px;color:#192e36}svg{width:100%;background:#fafaf8}svg text{font:12px monospace}article{border-top:1px solid #bbb;padding:12px 0}summary{cursor:pointer}</style>',
         '<h1>BTCUSDT · перевірка історичних входів</h1><p>Binance USD-M. Час UTC. Ціни в USDT. '
         'HTF містить закриті свічки на момент входу. Права частина M5 показує подальший рух.</p>']
    for r in trades:
        t=epoch(r["entry_utc"]); i=bisect_left(times,t); e=r['evidence']
        tf=r['poi_tf']; boundary=t//tf*tf; first=bisect_left(times,boundary-32*tf)
        stop=bisect_left(times,boundary); aggregate=[]
        for j in range(first,stop,tf//300):
            part=bars[j:min(j+tf//300,stop)]
            if len(part)==tf//300 and part[0].t%tf==0:
                aggregate.append(part[0]._replace(h=max(b.h for b in part),l=min(b.l for b in part),c=part[-1].c))
        doc.append(f'<article><h2>{escape(r["model"])} · {"LONG" if r["d"]==1 else "SHORT"} · {escape(r["entry_utc"])}</h2>')
        doc.append(panel(aggregate,[(r["poi"]+" low",r["poi_lo"]),(r["poi"]+" high",r["poi_hi"])],[],
                         f'Контекст POI · {tf//3600}H',tf))
        shift=e["shift"]
        points=[("Shift",epoch(shift["close_utc"])-300,shift["close_price"]),("Entry",t,r["entry"])]
        points.extend((f'QM{j+1}',epoch(p["open_utc"]),p["price"]) for j,p in enumerate(e.get("qm_pivots",[])))
        begin=max(0,min(i-36,bisect_left(times,epoch(e["touch_open_utc"]))-4,
            *( [bisect_left(times,epoch(p["open_utc"])) for p in e.get("qm_pivots",[])] or [i])))
        doc.append(panel(bars[begin:i+25],[
            ("Entry",r["entry"]),("SL",r["stop"]),("TP",r["target"]),("Shift",shift["level"]),
            ("Retest low",r["retest_lo"]),("Retest high",r["retest_hi"])],points,"Ретест та вхід · M5",300))
        doc.append(f'<p>Дотик POI {e["touch_open_utc"]}. Shift {shift["tf_seconds"]//60} хв, закриття {shift["close_utc"]} '
            f'за рівнем {shift["level"]:.2f}. Закриття ретесту {e["retest_close_utc"]}. '
            f'Структурна ціль {escape(r["target_type"])}. Плановий RR {r["planned_RR"]:.2f}. '
            f'Вихід {escape(r["outcome"])} о {r["exit_utc"]}, результат {r["R"]:+.2f}R.</p></article>')
    if not trades:
        doc.append('<p>За цей період входів немає.</p>')
    path.write_text("".join(doc)+"</html>",encoding="utf-8")
