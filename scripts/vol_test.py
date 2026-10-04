#!/usr/bin/env python3
"""A cabeca de volatilidade entrega os 70-80% prometidos? Walk-forward."""
from __future__ import annotations
import os, statistics as st, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                               # noqa: E402
from obs import drivers, volatility as vol                       # noqa: E402
from obs.db import connect                                       # noqa: E402
from scripts.exposure_test import ACOES, daily_returns           # noqa: E402
from scripts.leadlag import fetch                                # noqa: E402

TREINO_MIN = 200


def main():
    px = {}
    for nm, sym in ACOES.items():
        s = fetch(sym, "2y")
        if len(s) > 200:
            px[nm] = s
    print(f"{len(px)} acoes")
    ret = {k: daily_returns(v) for k, v in px.items()}
    con = connect(); dret = drivers.driver_returns(con); con.close()

    # retorno anormal = retorno - media transversal
    all_d = sorted({d for r in ret.values() for d in r})
    abn = {k: {} for k in ret}
    for d in all_d:
        vals = {k: ret[k][d] for k in ret if d in ret[k]}
        if len(vals) < 8:
            continue
        m = st.fmean(vals.values())
        for k, v in vals.items():
            abn[k][d] = v - m

    # volatilidade do painel macro no dia (media dos |retornos| dos drivers)
    drv_vol = {}
    for d in all_d:
        vs = [abs(dret[k][d]) for k in dret if d in dret[k]]
        if vs:
            drv_vol[d] = st.fmean(vs)

    def montar(serie, nome):
        """serie = {ticker: {data: retorno}}. Devolve X, y, keys.

        Duas correcoes sobre a primeira versao:
        1. A mediana que define "dia agitado" e EXPANSIVA (so o passado). Antes
           eu usava a mediana da amostra inteira -- look-ahead no proprio rotulo.
        2. Testamos tambem o retorno TOTAL, nao so o anormal. Remover a media
           transversal tira a volatilidade DE MERCADO, que e a parte mais
           persistente -- eu estava medindo so a vol idiossincratica, que e
           um alvo bem mais dificil, e atribuindo o fracasso ao modelo.
        """
        X, y, keys = [], [], []
        for tkr in px:
            dates = sorted(serie[tkr])
            if len(dates) < 60:
                continue
            for i in range(len(dates) - 1):
                f = vol.build_features(serie[tkr], dates, i, drv_vol)
                if f is None:
                    continue
                passado = [abs(serie[tkr][d]) for d in dates[:i]]
                if len(passado) < 40:
                    continue
                med = st.median(passado)          # expansiva: so o passado
                alvo = dates[i + 1]
                X.append(f)
                y.append(1.0 if abs(serie[tkr][alvo]) > med else 0.0)
                keys.append((tkr, alvo))
        return np.array(X), np.array(y), keys, nome

    casos = [montar(abn, "VOL IDIOSSINCRATICA (retorno anormal)"),
             montar(ret, "VOL TOTAL (retorno bruto)")]

    for X, y, keys, nome in casos:
        ordem = sorted(range(len(keys)), key=lambda j: keys[j][1])
        X, y = X[ordem], y[ordem]
        n = len(y); fold = n // 6
        P, A = [], []
        for f in range(5):
            corte = (f + 1) * fold
            tr = slice(0, corte); te = slice(corte, corte + fold)
            if corte < TREINO_MIN or len(y[te]) < 50:
                continue
            m = vol.logit_fit(X[tr], y[tr])
            P += list(vol.logit_predict(m, X[te])); A += list(y[te])
        P = np.array(P); A = np.array(A)
        acc = float(((P > 0.5) == (A > 0.5)).mean())
        base = float(max(A.mean(), 1 - A.mean()))
        brier = float(((P - A) ** 2).mean())
        brier_base = float(((A.mean() - A) ** 2).mean())
        pos, neg = P[A > 0.5], P[A < 0.5]
        auc = float((pos[:, None] > neg[None, :]).mean()) if len(pos) and len(neg) else float("nan")
        print(f"\n=== {nome} ===")
        print(f"  n fora da amostra : {len(A)}   taxa-base: {A.mean():.1%}")
        print(f"  acerto            : {acc:.1%}   (classe maior: {base:.1%})")
        print(f"  AUC               : {auc:.3f}   [0.5 = nada, >0.7 = bom]")
        print(f"  skill de Brier    : {1 - brier/brier_base:+.3f}")
    print("\nCabeca de DIRECAO, para comparar: 52.6% de acerto, IC 0.081.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
