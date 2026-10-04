#!/usr/bin/env python3
"""Mede o lead-lag global -> gap de abertura da B3.

A pergunta: o que acontece no mundo ENQUANTO a B3 esta fechada (18h BRT ->
10h BRT) ja preve a abertura brasileira? Se sim, isso e previsao de verdade:
no momento em que voce forma a estimativa, o preco brasileiro ainda nao se
moveu. E o unico ponto do sistema onde pessoa fisica nao chega atrasada.

Relogio (BRT):
  Asia (HSI, N225)   fecha ~05h   -> ANTES da abertura da B3   [utilizavel]
  Europa (DAX, FTSE) abre  ~04h   -> ANTES da abertura da B3   [utilizavel]
  EUA (GSPC)         fecha ~17h   -> 1h ANTES do fechamento da B3 [ja precificado]

Por isso o teste separa: GSPC do dia anterior deve prever POUCO (ja esta no
preco), Asia e Europa do mesmo dia devem prever MAIS.
"""
from __future__ import annotations
import os
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from obs.util import http_get                           # noqa: E402
from scripts.backtest import spearman                   # noqa: E402

YF = "https://query1.finance.yahoo.com/v8/finance/chart/"
HEAD = {"User-Agent": "Mozilla/5.0 (compatible; pesquisa-academica)"}


def fetch(symbol: str, rng: str = "2y") -> dict[str, dict]:
    r = http_get(YF + symbol, params={"range": rng, "interval": "1d"}, headers=HEAD)
    if r is None:
        print(f"  [yf] {symbol}: falhou")
        return {}
    try:
        res = r.json()["chart"]["result"][0]
    except (KeyError, IndexError, TypeError, ValueError):
        print(f"  [yf] {symbol}: resposta inesperada")
        return {}
    import datetime as dt
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    out = {}
    for i, t in enumerate(ts):
        o, c = q["open"][i], q["close"][i]
        if o is None or c is None:
            continue
        d = dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d")
        out[d] = {"open": o, "close": c}
    return out


def main():
    print("Baixando series (Yahoo, sem chave)...")
    series = {}
    for name, sym in [("BVSP", "%5EBVSP"), ("GSPC", "%5EGSPC"),
                      ("HSI", "%5EHSI"), ("DAX", "%5EGDAXI"),
                      ("BRENT", "BZ%3DF"), ("USDBRL", "USDBRL%3DX")]:
        series[name] = fetch(sym)
        print(f"  {name:<7} {len(series[name]):>4} pregoes")

    bv = series["BVSP"]
    if len(bv) < 100:
        print("\nSem dados suficientes do Ibovespa."); return 1

    dates = sorted(bv)
    # alvo: gap de abertura = open[T] / close[T-1] - 1
    gap, prev = {}, None
    for d in dates:
        if prev and bv[prev]["close"]:
            gap[d] = bv[d]["open"] / bv[prev]["close"] - 1.0
        prev = d

    # retorno intradiario da B3 no MESMO dia: open[T] -> close[T]
    intraday = {d: bv[d]["close"] / bv[d]["open"] - 1.0 for d in dates if bv[d]["open"]}

    def ret_same_day(name):
        s = series[name]
        return {d: (s[d]["close"] / s[d]["open"] - 1.0) for d in s if s[d]["open"]}

    def ret_prev_day(name):
        s = series[name]
        ds, out, p = sorted(s), {}, None
        for d in ds:
            if p and s[p]["close"]:
                out[d] = s[d]["close"] / s[p]["close"] - 1.0
            p = d
        # desloca: o retorno de ONTEM e o preditor de HOJE
        shifted, p = {}, None
        for d in sorted(bv):
            if p is not None and p in out:
                shifted[d] = out[p]
            p = d
        return shifted

    tests = [
        ("HSI  mesmo dia  (fecha 05h BRT, ANTES da abertura)", ret_same_day("HSI")),
        ("DAX  mesmo dia  (abre 04h BRT, ANTES da abertura)", ret_same_day("DAX")),
        ("GSPC dia anterior (fecha 17h BRT, JA precificado)", ret_prev_day("GSPC")),
        ("BRENT mesmo dia", ret_same_day("BRENT")),
        ("USDBRL mesmo dia", ret_same_day("USDBRL")),
    ]

    print(f"\n{'PREDITOR':<52} {'n':>5} {'IC vs GAP':>11} {'IC vs INTRA':>12}")
    print("-" * 83)
    for label, pred in tests:
        common_g = sorted(set(pred) & set(gap))
        common_i = sorted(set(pred) & set(intraday))
        if len(common_g) < 50:
            print(f"{label:<52} {len(common_g):>5}   (dados insuficientes)")
            continue
        ic_g = spearman([pred[d] for d in common_g], [gap[d] for d in common_g])
        ic_i = spearman([pred[d] for d in common_i], [intraday[d] for d in common_i])
        print(f"{label:<52} {len(common_g):>5} {ic_g:>+11.4f} {ic_i:>+12.4f}")

    n = len(gap)
    crit = 1.96 / (n ** 0.5)
    print(f"\nlimiar de significancia (5%, n~{n}): |IC| > {crit:.4f}")
    print("\nGAP   = abertura da B3 vs fechamento anterior  -> AINDA NAO precificado")
    print("INTRA = abertura -> fechamento do mesmo dia     -> coluna de controle")
    print("\nSe o IC for alto no GAP e baixo no INTRA, o sinal e de ABERTURA:")
    print("a informacao entra no preco no leilao de abertura e acaba ali.")

    vol_gap = st.pstdev(list(gap.values()))
    print(f"\ndesvio-padrao do gap diario do Ibovespa: {100*vol_gap:.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
