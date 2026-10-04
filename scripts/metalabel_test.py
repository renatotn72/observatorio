#!/usr/bin/env python3
"""O meta-labeling entrega? Troca frequencia por acerto, e quanto?

Primario = sinal de exposicao cambial (o unico que sobreviveu ao teste
rigoroso: IC -0.081, t = -3.81 por Fama-MacBeth). E de REVERSAO, logo a
chamada de direcao e o sinal INVERTIDO.

Meta = logistica sobre as condicoes do dia, prevendo se o primario acertou.
Tudo walk-forward: o meta de cada dobra ve so o passado.
"""
from __future__ import annotations
import math, os, statistics as st, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                              # noqa: E402
from obs import drivers, metalabel, volatility as vol           # noqa: E402
from obs.db import connect                                      # noqa: E402
from scripts.exposure_test import ACOES, daily_returns          # noqa: E402
from scripts.leadlag import fetch                               # noqa: E402

CAMBIO = ["DXY", "USDBRL", "EURUSD", "USDCNY"]
REFIT, JAN, MINOBS = 20, 250, 120


def main():
    px = {}
    for nm, sym in ACOES.items():
        s = fetch(sym, "2y")
        if len(s) > 200:
            px[nm] = s
    ret = {k: daily_returns(v) for k, v in px.items()}
    con = connect(); dret = drivers.driver_returns(con); con.close()

    # alvo: residuo transversal do gap de abertura
    gap = {k: {} for k in px}
    for k in px:
        ds, p = sorted(px[k]), None
        for d in ds:
            o = px[k][d].get("open"); pc = px[k][p]["close"] if p else None
            if pc and o:
                gap[k][d] = o / pc - 1.0
            p = d
    alvo = {k: {} for k in px}
    for d in sorted({d for g in gap.values() for d in g}):
        vals = {k: gap[k][d] for k in gap if d in gap[k]}
        if len(vals) < 8:
            continue
        m = st.fmean(vals.values())
        for k, v in vals.items():
            alvo[k][d] = v - m

    abn = {k: {} for k in ret}
    allret = sorted({d for r in ret.values() for d in r})
    for d in allret:
        vals = {k: ret[k][d] for k in ret if d in ret[k]}
        if len(vals) < 8:
            continue
        m = st.fmean(vals.values())
        for k, v in vals.items():
            abn[k][d] = v - m

    comuns = sorted(d for d in allret if all(d in dret[g] for g in CAMBIO))
    disp_drv = {d: st.pstdev([dret[g][d] for g in CAMBIO]) for d in comuns}

    # --- primario: sinal de exposicao cambial, beta ex-ante ---
    regs, exps = [], {}
    for i, d in enumerate(comuns):
        if i < 150 or i + 1 >= len(comuns):
            continue
        ad = comuns[i + 1]
        if i % REFIT == 0 or not exps:
            exps = {}
            for tkr in px:
                hist = [h for h in comuns[:i] if h in ret[tkr]][-JAN:]
                if len(hist) < MINOBS:
                    continue
                X = np.array([[dret[g][h] for g in CAMBIO] for h in hist])
                y = np.array([ret[tkr][h] for h in hist])
                b, _r2, sd = drivers.ridge_fit(X, y)
                exps[tkr] = (b, sd)
        x = np.array([dret[g][d] for g in CAMBIO])
        linha = []
        for tkr, (b, sd) in exps.items():
            if ad not in alvo.get(tkr, {}):
                continue
            linha.append((tkr, float((b * (x / sd)).sum())))
        if len(linha) < 8:
            continue
        m = st.fmean(v for _t, v in linha)
        s = st.pstdev([v for _t, v in linha]) or 1.0
        dates_t = sorted(abn[list(px)[0]])
        for tkr, v in linha:
            z = (v - m) / s                       # forca padronizada no dia
            # REVERSAO: a chamada e o sinal invertido
            direcao = -1 if z > 0 else 1
            acertou = 1.0 if direcao * alvo[tkr][ad] > 0 else 0.0
            dser = sorted(abn[tkr])
            j = dser.index(d) if d in dser else -1
            f = vol.build_features(abn[tkr], dser, j, {}) if j >= 21 else None
            regs.append({"d": ad, "tkr": tkr, "z": z, "acertou": acertou,
                         "vol_prev": (f[1] if f else 0.0),
                         "vol_real": (f[2] if f else 0.0),
                         "disp": disp_drv.get(d, 0.0)})

    regs.sort(key=lambda r: r["d"])
    X = np.array([metalabel.montar_features(r["z"], r["vol_prev"], r["vol_real"],
                                            r["disp"], 0.0) for r in regs])
    y = np.array([r["acertou"] for r in regs])
    print(f"{len(y)} chamadas do primario | acerto bruto: {y.mean():.1%}\n")

    # --- walk-forward do meta ---
    n = len(y); fold = n // 6
    P, A = [], []
    for f in range(5):
        corte = (f + 1) * fold
        tr, te = slice(0, corte), slice(corte, corte + fold)
        if corte < metalabel.MIN_TREINO or len(y[te]) < 50:
            continue
        m = metalabel.fit(X[tr], y[tr])
        p = metalabel.predict(m, X[te])
        if p is None:
            continue
        P += list(p); A += list(y[te])
    P, A = np.array(P), np.array(A)
    if not len(A):
        print("dobras insuficientes"); return 1

    print("TROCA DE FREQUENCIA POR ACERTO (fora da amostra)")
    print("=" * 76)
    print(f"{'limiar':>7} {'opera em':>9} {'acerto':>8} {'ganho':>8} {'erro-padrao':>12} {'t':>6}")
    print("-" * 76)
    base = A.mean()
    for lim in (0.0, 0.52, 0.54, 0.56, 0.58, 0.60):
        sel = P >= lim
        k = int(sel.sum())
        if k < 20:
            print(f"{lim:>7.2f} {k:>9}  (poucos casos)")
            continue
        acc = A[sel].mean()
        # erro-padrao do acerto no subconjunto, sob binomial
        se = math.sqrt(max(acc * (1 - acc), 1e-9) / k)
        t = (acc - base) / se if se else 0.0
        print(f"{lim:>7.2f} {k:>9} {acc:>7.1%} {acc-base:>+8.1%} {se:>11.1%} {t:>6.2f}")
    print("\n[t > 2 = ganho real; abaixo disso o 'ganho' cabe no ruido]")

    # monotonia: se o meta discrimina, acerto sobe com o limiar
    lims = [0.50, 0.52, 0.54, 0.56, 0.58]
    accs = []
    for lim in lims:
        sel = P >= lim
        accs.append(A[sel].mean() if sel.sum() >= 20 else float("nan"))
    mono = all(accs[i] <= accs[i + 1] + 1e-9 for i in range(len(accs) - 1)
               if accs[i] == accs[i] and accs[i + 1] == accs[i + 1])
    print(f"acerto cresce monotonicamente com o limiar? {'SIM' if mono else 'NAO'}")
    print(f"   sequencia: {[f'{a:.1%}' for a in accs]}")
    print(f"\n* extrapolado para 18 papeis x 250 pregoes")
    pos, neg = P[A > 0.5], P[A < 0.5]
    auc = float((pos[:, None] > neg[None, :]).mean()) if len(pos) and len(neg) else float("nan")
    print(f"\nAUC do meta: {auc:.3f}   [0.5 = o meta nao sabe nada]")
    print(f"acerto sem filtro: {base:.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
