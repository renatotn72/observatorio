#!/usr/bin/env python3
"""Volatilidade: o alvo estava errado, nao o fenomeno?

Testa tres formulacoes do MESMO dado:
  A) continua  -- correlacao entre vol prevista e |retorno| realizado
  B) mediana   -- "amanha passa da mediana?"  (o que eu testei antes)
  C) extremo   -- "amanha fica no top 20% de agitacao?"

Hipotese: a persistencia de volatilidade e real, mas aparece em (A) e (C).
A mediana e onde a distincao e quase toda ruido.
"""
from __future__ import annotations
import os, statistics as st, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                            # noqa: E402
from obs import drivers, volatility as vol                    # noqa: E402
from obs.db import connect                                    # noqa: E402
from scripts.backtest import spearman                         # noqa: E402
from scripts.exposure_test import ACOES, daily_returns        # noqa: E402
from scripts.leadlag import fetch                             # noqa: E402


def main():
    px = {}
    for nm, sym in ACOES.items():
        s = fetch(sym, "2y")
        if len(s) > 200:
            px[nm] = s
    ret = {k: daily_returns(v) for k, v in px.items()}
    con = connect(); dret = drivers.driver_returns(con); con.close()
    all_d = sorted({d for r in ret.values() for d in r})
    abn = {k: {} for k in ret}
    for d in all_d:
        vals = {k: ret[k][d] for k in ret if d in ret[k]}
        if len(vals) < 8:
            continue
        m = st.fmean(vals.values())
        for k, v in vals.items():
            abn[k][d] = v - m
    drv_vol = {}
    for d in all_d:
        vs = [abs(dret[k][d]) for k in dret if d in dret[k]]
        if vs:
            drv_vol[d] = st.fmean(vs)

    X, mag, keys = [], [], []
    for tkr in px:
        dates = sorted(abn[tkr])
        for i in range(len(dates) - 1):
            f = vol.build_features(abn[tkr], dates, i, drv_vol)
            if f is None or len(dates[:i]) < 40:
                continue
            X.append(f)
            mag.append(abs(abn[tkr][dates[i + 1]]))
            keys.append((tkr, dates[i + 1]))
    X = np.array(X); mag = np.array(mag)
    ordem = sorted(range(len(keys)), key=lambda j: keys[j][1])
    X, mag = X[ordem], mag[ordem]
    n = len(mag); corte = int(n * 0.6)
    print(f"{n} pares (acao, dia) | treino {corte}, teste {n - corte}\n")

    tr, te = slice(0, corte), slice(corte, n)

    # A) continua: prever |retorno| por minimos quadrados nas mesmas features
    mu, sd = X[tr].mean(0), X[tr].std(0); sd[sd == 0] = 1
    Z = np.hstack([np.ones((len(X), 1)), (X - mu) / sd])
    b = np.linalg.solve(Z[tr].T @ Z[tr] + 1e-3 * np.eye(Z.shape[1]), Z[tr].T @ mag[tr])
    pred = Z[te] @ b
    ic = spearman(list(pred), list(mag[te]))
    r2 = 1 - float(((mag[te] - pred) ** 2).sum() / ((mag[te] - mag[tr].mean()) ** 2).sum())
    print("A) ALVO CONTINUO (prever a magnitude)")
    print(f"   IC (Spearman) : {ic:+.4f}   <- compare com 0.081 da direcao")
    print(f"   R2 fora amostra: {r2:+.4f}")

    def binario(q, nome):
        lim_tr = np.quantile(mag[tr], q)
        y = (mag > lim_tr).astype(float)
        m = vol.logit_fit(X[tr], y[tr])
        p = vol.logit_predict(m, X[te])
        yt = y[te]
        acc = float(((p > np.quantile(p, q)) == (yt > 0.5)).mean())
        pos, neg = p[yt > 0.5], p[yt < 0.5]
        auc = float((pos[:, None] > neg[None, :]).mean()) if len(pos) and len(neg) else float("nan")
        print(f"\n{nome}")
        print(f"   taxa-base     : {yt.mean():.1%}")
        print(f"   AUC           : {auc:.3f}")
        print(f"   acerto (corte no mesmo quantil): {acc:.1%}")
        return auc

    binario(0.50, "B) ALVO MEDIANA (o que testei antes)")
    binario(0.80, "C) ALVO EXTREMO (top 20% de agitacao)")
    binario(0.90, "D) ALVO MUITO EXTREMO (top 10%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
