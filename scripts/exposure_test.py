#!/usr/bin/env python3
"""Valida (ou refuta) a arquitetura de VETOR DE EXPOSICAO antes de constru-la.

Hipotese: cada ativo tem um vetor de sensibilidades a drivers globais (Brent,
cambio, cobre, Asia, EUA). Se o driver se move enquanto a B3 esta fechada,
a exposicao preve QUAL acao abre mais forte que as outras.

Por que o alvo e o RESIDUO transversal e nao o retorno:
  gap_residual[i] = gap[i] - media_transversal(gap)
Remover a media remove o fator comum -- que e justamente o que destruia a
amplitude (10 blue chips valiam 1,7 apostas). No residuo, as apostas voltam
a ser aproximadamente independentes.

Disciplina ex-ante: o beta de cada ativo e estimado SO com dados anteriores a
T. Nada do dia T entra na estimativa que preve o dia T.
"""
from __future__ import annotations
import os
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.backtest import spearman                   # noqa: E402
from scripts.leadlag import fetch                       # noqa: E402

ACOES = {
    "PETR4": "PETR4.SA", "PRIO3": "PRIO3.SA", "VALE3": "VALE3.SA",
    "CSNA3": "CSNA3.SA", "GGBR4": "GGBR4.SA", "USIM5": "USIM5.SA",
    "ITUB4": "ITUB4.SA", "BBDC4": "BBDC4.SA", "BBAS3": "BBAS3.SA",
    "SANB11": "SANB11.SA", "ABEV3": "ABEV3.SA", "WEGE3": "WEGE3.SA",
    "SUZB3": "SUZB3.SA", "KLBN11": "KLBN11.SA", "MGLU3": "MGLU3.SA",
    "LREN3": "LREN3.SA", "RADL3": "RADL3.SA", "RENT3": "RENT3.SA",
    "EMBR3": "EMBR3.SA", "CPLE6": "CPLE6.SA",
}
# Drivers que FECHAM antes da abertura da B3 (10h BRT) ou negociam 24h
DRIVERS = {"BRENT": "BZ%3DF", "USDBRL": "USDBRL%3DX", "COBRE": "HG%3DF",
           "HSI": "%5EHSI", "OURO": "GC%3DF"}

MIN_TREINO = 60      # pregoes para estimar beta
MIN_NOMES = 8        # minimo de acoes no dia para a media transversal valer


def daily_returns(s: dict) -> dict[str, float]:
    ds, out, p = sorted(s), {}, None
    for d in ds:
        if p and s[p]["close"] and s[d]["close"]:
            out[d] = s[d]["close"] / s[p]["close"] - 1.0
        p = d
    return out


def opening_gaps(s: dict) -> dict[str, float]:
    ds, out, p = sorted(s), {}, None
    for d in ds:
        if p and s[p]["close"] and s[d].get("open"):
            out[d] = s[d]["open"] / s[p]["close"] - 1.0
        p = d
    return out


def ols_beta(ys: list[float], xs: list[float]) -> float:
    n = len(ys)
    if n < 10:
        return 0.0
    mx, my = st.fmean(xs), st.fmean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    return num / den if den else 0.0


def main():
    print("Baixando precos (Yahoo, sem chave)...")
    px, drv = {}, {}
    for nm, sym in ACOES.items():
        s = fetch(sym, "2y")
        if len(s) > 200:
            px[nm] = s
    print(f"  {len(px)}/{len(ACOES)} acoes")
    for nm, sym in DRIVERS.items():
        s = fetch(sym, "2y")
        if len(s) > 200:
            drv[nm] = s
    print(f"  {len(drv)}/{len(DRIVERS)} drivers: {sorted(drv)}")

    if len(px) < MIN_NOMES or not drv:
        print("dados insuficientes"); return 1

    ret = {k: daily_returns(v) for k, v in px.items()}
    gap = {k: opening_gaps(v) for k, v in px.items()}
    dret = {k: daily_returns(v) for k, v in drv.items()}

    # residuo transversal do gap
    all_d = sorted({d for g in gap.values() for d in g})
    resid: dict[str, dict[str, float]] = {k: {} for k in gap}
    mkt_gap: dict[str, float] = {}
    for d in all_d:
        vals = {k: gap[k][d] for k in gap if d in gap[k]}
        if len(vals) < MIN_NOMES:
            continue
        m = st.fmean(vals.values())
        mkt_gap[d] = m
        for k, v in vals.items():
            resid[k][d] = v - m

    # --- 1) o driver preve o gap COMUM do mercado? ---
    print(f"\n{'='*74}\n1) GAP COMUM DO MERCADO (media transversal)\n{'='*74}")
    print(f"{'driver (mesmo dia, fecha antes da abertura)':<46} {'n':>5} {'IC':>9}")
    for dn, dr in sorted(dret.items()):
        common = sorted(set(dr) & set(mkt_gap))
        if len(common) < 100:
            continue
        ic = spearman([dr[d] for d in common], [mkt_gap[d] for d in common])
        star = " *" if abs(ic) > 1.96 / len(common) ** 0.5 else ""
        print(f"{dn:<46} {len(common):>5} {ic:>+9.4f}{star}")

    # --- 2) a EXPOSICAO preve o residuo transversal? ---
    print(f"\n{'='*74}\n2) RESIDUO TRANSVERSAL via vetor de exposicao (ex-ante)\n{'='*74}")
    print("Para cada dia T: beta estimado so com dados < T; previsao =")
    print("beta[acao,driver] x retorno_do_driver[T]; alvo = residuo do gap[T].\n")

    for dn, dr in sorted(dret.items()):
        preds, actuals = [], []
        dates = sorted(set(dr) & set(mkt_gap))
        for i, d in enumerate(dates):
            if i < MIN_TREINO:
                continue
            hist = dates[max(0, i - 250):i]          # janela movel, estritamente passada
            row_p, row_a = [], []
            for k in px:
                ys = [ret[k][h] for h in hist if h in ret[k] and h in dr]
                xs = [dr[h] for h in hist if h in ret[k] and h in dr]
                if len(ys) < 40 or d not in resid[k]:
                    continue
                b = ols_beta(ys, xs)
                row_p.append(b * dr[d])
                row_a.append(resid[k][d])
            if len(row_p) < MIN_NOMES:
                continue
            # demeia a previsao tambem: comparamos ranking transversal
            mp = st.fmean(row_p)
            preds += [p - mp for p in row_p]
            actuals += row_a

        if len(preds) < 500:
            print(f"{dn:<12} dados insuficientes ({len(preds)})")
            continue
        ic = spearman(preds, actuals)
        crit = 1.96 / len(preds) ** 0.5
        star = " SIGNIFICATIVO" if abs(ic) > crit else ""
        print(f"{dn:<12} n={len(preds):>6}  IC={ic:>+7.4f}  (limiar {crit:.4f}){star}")

    print(f"\nObs: n aqui conta pares (acao, dia) -- a amplitude que o residuo libera.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
