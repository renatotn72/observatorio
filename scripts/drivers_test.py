#!/usr/bin/env python3
"""A cadeia de afetacao funciona? E a regressao multipla bate a soma ingenua?

Walk-forward: a cada 20 pregoes a cadeia e reestimada com dados ESTRITAMENTE
anteriores; o sinal do dia T preve o residuo transversal do pregao T+1.
"""
from __future__ import annotations
import math, os, statistics as st, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                            # noqa: E402
from obs import drivers                                       # noqa: E402
from obs.db import connect                                    # noqa: E402
from scripts.backtest import spearman                         # noqa: E402
from scripts.exposure_test import ACOES, daily_returns, ols_beta  # noqa: E402
from scripts.leadlag import fetch                             # noqa: E402

REFIT = 20


def main():
    print("Baixando acoes...")
    px = {}
    for nm, sym in ACOES.items():
        s = fetch(sym, "2y")
        if len(s) > 200:
            px[nm] = s
    print(f"  {len(px)} acoes")

    ret = {k: daily_returns(v) for k, v in px.items()}
    con = connect(); dret = drivers.driver_returns(con); con.close()
    dnames = sorted(dret)

    # alvo: residuo transversal do retorno close-to-close
    all_d = sorted({d for r in ret.values() for d in r})
    resid = {k: {} for k in ret}
    for d in all_d:
        vals = {k: ret[k][d] for k in ret if d in ret[k]}
        if len(vals) < 8:
            continue
        m = st.fmean(vals.values())
        for k, v in vals.items():
            resid[k][d] = v - m

    comuns = [d for d in all_d if all(d in dret[k] for k in dnames)]
    print(f"  {len(comuns)} pregoes com todos os {len(dnames)} drivers\n")

    def avaliar(subset, modo):
        preds, acts, exps = [], [], {}
        for i, d in enumerate(comuns):
            if i < 150 or i + 1 >= len(comuns):
                continue
            alvo_d = comuns[i + 1]
            if i % REFIT == 0 or not exps:
                exps = {}
                for tkr in px:
                    hist = [h for h in comuns[:i] if h in ret[tkr]][-250:]
                    if len(hist) < 120:
                        continue
                    y = np.array([ret[tkr][h] for h in hist])
                    if modo == "multipla":
                        X = np.array([[dret[k][h] for k in subset] for h in hist])
                        b, r2, sd = drivers.ridge_fit(X, y)
                        exps[tkr] = {"b": b, "sd": sd}
                    else:  # univariada somada (a forma ingenua)
                        bs, sds = [], []
                        for k in subset:
                            xs = [dret[k][h] for h in hist]
                            bs.append(ols_beta(list(y), xs))
                            sds.append(st.pstdev(xs) or 1.0)
                        exps[tkr] = {"b": np.array(bs), "sd": np.array(sds)}
            row_p, row_a = [], []
            for tkr, e in exps.items():
                if alvo_d not in resid.get(tkr, {}):
                    continue
                x = np.array([dret[k][d] for k in subset])
                val = float((e["b"] * (x / e["sd"])).sum()) if modo == "multipla" \
                    else float((e["b"] * x).sum())
                row_p.append(val); row_a.append(resid[tkr][alvo_d])
            if len(row_p) < 8:
                continue
            mp = st.fmean(row_p)
            preds += [p - mp for p in row_p]; acts += row_a
        if len(preds) < 500:
            return None, 0
        return spearman(preds, acts), len(preds)

    cats = {}
    for k, (_s, c) in drivers.DRIVERS.items():
        if k in dnames:
            cats.setdefault(c, []).append(k)

    grupos = [
        ("so cambio", cats.get("cambio", [])),
        ("so metais (c/ minerio e ouro)", cats.get("metal", [])),
        ("so energia", cats.get("energia", [])),
        ("cambio + metais + energia", cats.get("cambio", []) + cats.get("metal", []) + cats.get("energia", [])),
        ("TUDO (15 drivers)", dnames),
    ]

    print("=" * 76)
    print("IC do SINAL DE DRIVERS -> residuo transversal do pregao T+1")
    print("=" * 76)
    print(f"{'conjunto':<34} {'n':>7} {'multipla':>10} {'ingenua':>10} {'limiar':>8}")
    print("-" * 76)
    for nome, subset in grupos:
        if not subset:
            continue
        ic_m, n_m = avaliar(subset, "multipla")
        ic_u, n_u = avaliar(subset, "univariada")
        crit = 1.96 / math.sqrt(n_m) if n_m else float("nan")
        f = lambda v: f"{v:+.4f}" if v is not None else "   n/d"
        star = " *" if ic_m and abs(ic_m) > crit else ""
        print(f"{nome:<34} {n_m:>7} {f(ic_m):>10} {f(ic_u):>10} {crit:>8.4f}{star}")

    # cadeia de afetacao legivel
    print("\n" + "=" * 76)
    print("CADEIA DE AFETACAO (ultima estimativa, participacao na sensibilidade)")
    print("=" * 76)
    asof = comuns[-1]
    exps = drivers.fit_exposures({k: ret[k] for k in px}, asof, persist=True)
    for tkr in sorted(exps):
        e = exps[tkr]
        top = drivers.affect_index(e, top=4)
        txt = "  ".join(f"{k} {100*s:.0f}%{'+' if b > 0 else '-'}" for k, s, b in top)
        print(f"  {tkr:<7} R²={e['r2']:.2f}  {txt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
