#!/usr/bin/env python3
"""Cambio ajuda a prever acao? Teste ex-ante limpo.

Janela: a barra diaria de cambio fecha 19:59 BRT -- DEPOIS do fechamento da
B3 (18:00) e ANTES da abertura seguinte (10:00). Logo cambio[T] -> acao[T+1]
nao tem contaminacao contemporanea, ao contrario do que ocorreu com Brent e
com o proprio USDBRL no teste anterior (onde eu usava cambio[T] -> acao[T]).

Hipotese economica: USD/BRL tem sinal OPOSTO entre papeis -- exportadora
ganha com real fraco, varejo domestico e quem tem divida em dolar perde.
Sinal oposto e justamente o que gera dispersao transversal aproveitavel.

Alvos:
  gap[T+1]   = abertura T+1 / fechamento T - 1     (leilao de abertura)
  dia[T+1]   = fechamento T+1 / fechamento T - 1   (dia inteiro)
ambos em residuo transversal (removida a media do dia).
"""
from __future__ import annotations
import math
import os
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.backtest import spearman                              # noqa: E402
from scripts.exposure_test import ACOES, daily_returns, ols_beta   # noqa: E402
from scripts.leadlag import fetch                                  # noqa: E402

FX = {"USDBRL": "USDBRL%3DX", "EURUSD": "EURUSD%3DX", "DXY": "DX-Y.NYB",
      "USDCNY": "USDCNY%3DX", "USDMXN": "USDMXN%3DX"}
OUTROS = {"HSI": "%5EHSI"}          # referencia ja medida

MIN_TREINO, MIN_NOMES, JANELA = 60, 8, 250


def main():
    print("Baixando...")
    px = {}
    for nm, sym in ACOES.items():
        s = fetch(sym, "2y")
        if len(s) > 200:
            px[nm] = s
    drv = {}
    for nm, sym in {**FX, **OUTROS}.items():
        s = fetch(sym, "2y")
        if len(s) > 200:
            drv[nm] = s
    print(f"  {len(px)} acoes, {len(drv)} drivers: {sorted(drv)}\n")

    ret = {k: daily_returns(v) for k, v in px.items()}
    dret = {k: daily_returns(v) for k, v in drv.items()}

    # alvos, em residuo transversal
    all_d = sorted({d for r in ret.values() for d in r})
    gap_r, dia_r = {k: {} for k in px}, {k: {} for k in px}
    ds = {k: sorted(px[k]) for k in px}
    prevc = {k: None for k in px}
    raw_gap, raw_dia = {k: {} for k in px}, {k: {} for k in px}
    for k in px:
        p = None
        for d in ds[k]:
            c, o = px[k][d]["close"], px[k][d].get("open")
            if p and px[k][p]["close"]:
                pc = px[k][p]["close"]
                if o:
                    raw_gap[k][d] = o / pc - 1.0
                raw_dia[k][d] = c / pc - 1.0
            p = d
    for tgt_raw, tgt_res in ((raw_gap, gap_r), (raw_dia, dia_r)):
        for d in all_d:
            vals = {k: tgt_raw[k][d] for k in tgt_raw if d in tgt_raw[k]}
            if len(vals) < MIN_NOMES:
                continue
            m = st.fmean(vals.values())
            for k, v in vals.items():
                tgt_res[k][d] = v - m

    def avaliar(dname, alvo, defasagem=1):
        dr = dret[dname]
        dates = sorted(set(dr) & set(all_d))
        preds, acts = [], []
        for i, d in enumerate(dates):
            if i < MIN_TREINO or i + defasagem >= len(dates):
                continue
            alvo_d = dates[i + defasagem]         # o driver de T preve T+1
            hist = dates[max(0, i - JANELA):i]
            row_p, row_a = [], []
            for k in px:
                ys = [ret[k][h] for h in hist if h in ret[k] and h in dr]
                xs = [dr[h] for h in hist if h in ret[k] and h in dr]
                if len(ys) < 40 or alvo_d not in alvo[k]:
                    continue
                row_p.append(ols_beta(ys, xs) * dr[d])
                row_a.append(alvo[k][alvo_d])
            if len(row_p) < MIN_NOMES:
                continue
            mp = st.fmean(row_p)
            preds += [p - mp for p in row_p]
            acts += row_a
        if len(preds) < 500:
            return None, 0
        return spearman(preds, acts), len(preds)

    for nome_alvo, alvo in (("GAP de abertura T+1", gap_r), ("DIA INTEIRO T+1", dia_r)):
        print("=" * 70)
        print(f"ALVO: {nome_alvo}  (residuo transversal, beta ex-ante)")
        print("=" * 70)
        print(f"{'driver (fecha 19:59 BRT de T)':<34} {'n':>7} {'IC':>9} {'limiar':>9}")
        print("-" * 70)
        for dn in sorted(drv):
            ic, n = avaliar(dn, alvo)
            if ic is None:
                print(f"{dn:<34} dados insuficientes")
                continue
            crit = 1.96 / math.sqrt(n)
            star = "  SIG" if abs(ic) > crit else ""
            print(f"{dn:<34} {n:>7} {ic:>+9.4f} {crit:>9.4f}{star}")
        print()

    print("Lembrete: a maior parte do movimento cambial do dia T ocorre DURANTE")
    print("o pregao da B3 e ja esta no fechamento de T. O que resta de novo e a")
    print("janela 18:00-19:59. Por isso o sinal aqui tende a ser pequeno -- o")
    print("teste mede subreacao, nao informacao nova.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
