#!/usr/bin/env python3
"""As anomalias famosas funcionam nos SEUS dados?

Mesma disciplina do resto do projeto: IC transversal, Fama-MacBeth (cada DIA
vale uma observacao, nao cada par papel-dia) e nula de permutacao onde cabe.

Testadas, todas no residuo transversal (removida a media do dia):
  momento 12-1     retorno de 12 meses excluindo o ultimo  -> retorno futuro
  reversao 1 mes   retorno do ultimo mes                   -> retorno futuro
  reversao 1 dia   retorno de ontem                        -> retorno de hoje
  baixa vol        -vol de 60 pregoes                      -> retorno futuro
  persistencia vol vol de 20 pregoes                       -> |retorno| futuro
"""
from __future__ import annotations
import math, os, statistics as st, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from obs.db import connect                                      # noqa: E402
from scripts.backtest import spearman                           # noqa: E402

H = 21          # horizonte futuro, em pregoes (1 mes)


def main():
    con = connect()
    rows = con.execute("SELECT ticker,date,close FROM prices ORDER BY ticker,date").fetchall()
    con.close()
    by = {}
    for r in rows:
        by.setdefault(r["ticker"], []).append((r["date"], r["close"]))
    px = {t: dict(v) for t, v in by.items()}
    datas = sorted(set.intersection(*[set(v) for v in px.values()]))
    tks = sorted(px)
    print(f"{len(tks)} papeis | {len(datas)} pregoes | {datas[0]} a {datas[-1]}\n")

    def ret(t, i, j):
        a, b = px[t].get(datas[i]), px[t].get(datas[j])
        return (b / a - 1) if (a and b) else None

    def vol(t, i, n):
        vs = []
        for k in range(max(1, i - n + 1), i + 1):
            r = ret(t, k - 1, k)
            if r is not None:
                vs.append(r)
        return st.pstdev(vs) if len(vs) > 5 else None

    sinais = {
        "momento 12-1":    lambda t, i: ret(t, max(0, i - 252), max(0, i - 21)),
        "reversao 1 mes":  lambda t, i: (lambda r: -r if r is not None else None)(ret(t, max(0, i - 21), i)),
        "reversao 1 dia":  lambda t, i: (lambda r: -r if r is not None else None)(ret(t, i - 1, i)),
        "baixa vol":       lambda t, i: (lambda v: -v if v is not None else None)(vol(t, i, 60)),
    }

    print(f"{'sinal':<18} {'alvo':<22} {'dias':>6} {'IC medio':>10} {'t':>7}")
    print("-" * 70)

    for nome, fn in sinais.items():
        ics = []
        for i in range(260, len(datas) - H, 5):
            linha = []
            for t in tks:
                s = fn(t, i)
                fut = ret(t, i, i + H)
                if s is not None and fut is not None:
                    linha.append((s, fut))
            if len(linha) < 8:
                continue
            ms = st.fmean(x for x, _ in linha); mf = st.fmean(y for _, y in linha)
            ic = spearman([x - ms for x, _ in linha], [y - mf for _, y in linha])
            if ic == ic:
                ics.append(ic)
        if len(ics) < 20:
            print(f"{nome:<18} (dados insuficientes)"); continue
        m = st.fmean(ics); se = st.stdev(ics) / math.sqrt(len(ics)); t = m / se
        sig = " SIG" if abs(t) > 2 else ""
        print(f"{nome:<18} {'retorno 21 pregoes':<22} {len(ics):>6} {m:>+10.4f} {t:>+7.2f}{sig}")

    # persistencia de volatilidade: vol passada -> |retorno| futuro
    ics = []
    for i in range(260, len(datas) - H, 5):
        linha = []
        for t in tks:
            v = vol(t, i, 20)
            fut = ret(t, i, i + 1)
            if v is not None and fut is not None:
                linha.append((v, abs(fut)))
        if len(linha) < 8:
            continue
        ms = st.fmean(x for x, _ in linha); mf = st.fmean(y for _, y in linha)
        ic = spearman([x - ms for x, _ in linha], [y - mf for _, y in linha])
        if ic == ic:
            ics.append(ic)
    m = st.fmean(ics); se = st.stdev(ics) / math.sqrt(len(ics)); t = m / se
    print(f"{'persistencia vol':<18} {'|retorno| amanha':<22} {len(ics):>6} {m:>+10.4f} {t:>+7.2f}"
          f"{' SIG' if abs(t) > 2 else ''}")
    print("\n[t > 2 = sobrevive; Harvey et al. defendem t > 3 pelo volume de testes da area]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
