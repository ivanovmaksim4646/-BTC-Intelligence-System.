"""Portfolio projection of independently simulated candidates; no overlapping positions.
Tie-break fixed before replay: earliest entry, higher planned RR, model name.
Risk normalized to 1% of shared realized equity. Not an online shared-order simulation.
"""
from research.baseline.replay import stats

def combine(books):
    rows=sorted((r for book in books.values() for r in book.rows),
                key=lambda r:(r["entry_utc"],-r["planned_RR"],r["model"]))
    accepted=[]; rejected=[]; equity=peak=1000.; dd=0.; occupied_until=""
    for r in rows:
        if r["entry_utc"]<occupied_until:
            rejected.append(dict(model=r["model"],entry_utc=r["entry_utc"],
                                 reason="portfolio_overlap",d=r["d"]))
            continue
        if equity<=0:break
        row=dict(r)
        budget=equity*.01
        row["qty"]=r["qty"]*budget/r["risk"]
        row["risk"]=budget
        row["pnl"]=r["R"]*budget
        equity+=row["pnl"]
        row["equity"]=equity
        peak=max(peak,equity)
        dd=max(dd,1-equity/peak)
        occupied_until=r["exit_utc"]
        accepted.append(row)
    return dict(trades=accepted,excluded=rejected,
                summary=dict(**stats(accepted),initial_equity=1000.,
                final_equity=equity,closed_drawdown_pct=dd*100,
                overlap_excluded=len(rejected),classification="independent_candidate_projection"))
