#!/usr/bin/env python3
"""Quanto a cadeia de drivers melhora a previsao? Alvo UNICO, combinacao medida.

Medicoes anteriores usaram alvos diferentes (gap do mesmo dia, gap de T+1,
dia inteiro de T+1). Somar aqueles ICs em quadratura seria errado: nao sao
preditores do mesmo alvo. Aqui tudo e avaliado contra UM alvo so.

Alvo: residuo transversal do GAP de abertura de T+1.
Preditores (todos ex-ante, driver do dia T fecha antes da abertura de T+1):
  A) exposicao a ENERGIA        (o unico grupo significativo isolado)
  B) exposicao a CAMBIO/dolar   (DXY+USDBRL, o efeito de reversao)
  C) A + B combinados por media das previsoes padronizadas
"""
from __future__ import annotations
import math, os, statistics as st, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                               # noqa: E402
from obs import drivers                                          # noqa: E402
from obs.db import connect                                       # noqa: E402
from scripts.backtest import spearman                            # noqa: E402
from scripts.exposure_test import ACOES, daily_returns           # noqa: E402
from scripts.leadlag import fetch                                # noqa: E402

REFIT, JAN, MINOBS = 20, 250, 120
GRUPOS = {"ENERGIA": ["BRENT", "GAS"],
          "CAMBIO": ["DXY", "USDBRL", "EURUSD", "USDCNY"]}


def zscore(v):
    s = st.pstdev(v)
    m = st.fmean(v)
    return [(x - m) / s for x in v] if s else [0.0] * len(v)


def main():
    px = {}
    for nm, sym in ACOES.items():
        s = fetch(sym, "2y")
        if len(s) > 200:
            px[nm] = s
    print(f"{len(px)} acoes")
    ret = {k: daily_returns(v) for k, v in px.items()}
    con = connect(); dret = drivers.driver_returns(con); con.close()

    # alvo: residuo transversal do gap T+1
    gap = {k: {} for k in px}
    for k in px:
        ds, p = sorted(px[k]), None
        for d in ds:
            o, pc = px[k][d].get("open"), (px[k][p]["close"] if p else None)
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

    comuns = sorted(d for d in {d for r in ret.values() for d in r}
                    if all(d in dret[g] for g in dret))
    print(f"{len(comuns)} pregoes\n")

    def sinais(subset):
        """Devolve {(ticker, data_alvo): previsao} para um grupo de drivers."""
        out, exps = {}, {}
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
                    X = np.array([[dret[k][h] for k in subset] for h in hist])
                    y = np.array([ret[tkr][h] for h in hist])
                    b, _r2, sd = drivers.ridge_fit(X, y)
                    exps[tkr] = (b, sd)
            x = np.array([dret[k][d] for k in subset])
            for tkr, (b, sd) in exps.items():
                if ad in alvo.get(tkr, {}):
                    out[(tkr, ad)] = float((b * (x / sd)).sum())
        return out

    sA = sinais(GRUPOS["ENERGIA"])
    sB = sinais(GRUPOS["CAMBIO"])

    def fama_macbeth(por_dia_pa, nome):
        """IC transversal POR DIA, depois teste t sobre a serie de ICs diarios.

        Agrupar 18 acoes do mesmo dia como 18 observacoes independentes infla
        a significancia: elas compartilham o mesmo choque macro mesmo depois de
        removida a media. Aqui cada DIA vale uma observacao, que e o tratamento
        correto (Fama-MacBeth) e e bem mais exigente.
        """
        ics = []
        for d, (P, A) in sorted(por_dia_pa.items()):
            if len(P) < 8:
                continue
            ic = spearman(P, A)
            if ic == ic:
                ics.append(ic)
        n = len(ics)
        media = st.fmean(ics)
        se = st.stdev(ics) / math.sqrt(n) if n > 1 else float("nan")
        t = media / se if se else float("nan")
        sig = "  SIG" if abs(t) > 1.96 else ""
        print(f"{nome:<30} dias={n:>4}  IC_medio={media:>+8.4f}  "
              f"t={t:>+6.2f}{sig}")
        return media, t

    def avaliar(sig, nome):
        por_dia, pa = {}, {}
        for (tkr, d), v in sig.items():
            por_dia.setdefault(d, []).append((tkr, v))
        P_all, A_all = [], []
        for d, lst in por_dia.items():
            if len(lst) < 8:
                continue
            m = st.fmean(v for _t, v in lst)
            P = [v - m for _t, v in lst]
            A = [alvo[t][d] for t, _v in lst]
            pa[d] = (P, A)
            P_all += P; A_all += A
        ic_pool = spearman(P_all, A_all)
        print(f"{nome:<30} agrupado: IC={ic_pool:+.4f} "
              f"(limiar ingenuo {1.96/math.sqrt(len(P_all)):.4f})")
        media, t = fama_macbeth(pa, "   -> Fama-MacBeth")
        return ic_pool, P_all, A_all

    print("=" * 72)
    print("ALVO UNICO: residuo transversal do GAP de abertura T+1")
    print("=" * 72)
    icA, PA, AA = avaliar(sA, "A) exposicao a ENERGIA")
    icB, PB, AB = avaliar(sB, "B) exposicao a CAMBIO")

    # combinacao: media dos z-scores das duas previsoes, nos pares comuns
    chaves = sorted(set(sA) & set(sB))
    por_dia = {}
    for k in chaves:
        por_dia.setdefault(k[1], []).append(k[0])
    P, A = [], []
    for d, tks in por_dia.items():
        if len(tks) < 8:
            continue
        a = zscore([sA[(t, d)] for t in tks])
        b = zscore([sB[(t, d)] for t in tks])
        # sinal de B e de REVERSAO (IC negativo medido): entra invertido
        comb = [(x - y) / math.sqrt(2) for x, y in zip(a, b)] if icB < 0 \
            else [(x + y) / math.sqrt(2) for x, y in zip(a, b)]
        P += comb; A += [alvo[t][d] for t in tks]
    icC = spearman(P, A)
    print(f"{'C) A + B combinados':<30} agrupado: IC={icC:+.4f} "
          f"(limiar ingenuo {1.96/math.sqrt(len(P)):.4f})")
    pa_c = {}
    idx = 0
    for d, tks in sorted(por_dia.items()):
        if len(tks) < 8:
            continue
        k = len(tks)
        pa_c[d] = (P[idx:idx + k], A[idx:idx + k])
        idx += k
    fama_macbeth(pa_c, "   -> Fama-MacBeth")

    print("\n" + "=" * 72)
    melhor = max(abs(icA), abs(icB), abs(icC))
    print(f"melhor |IC| num alvo unico: {melhor:.4f}")
    hit = 0.5 + math.asin(min(0.999, melhor)) / math.pi
    print(f"-> acerto direcional: {hit:.1%}  ({100*hit:.1f} em 100)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
