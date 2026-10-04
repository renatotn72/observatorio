#!/usr/bin/env python3
"""Indicadores ESTRANGEIROS discriminam entre papeis brasileiros?

Mesma disciplina da surpresa domestica: a dispersao transversal dos betas tem
de superar uma nula de permutacao. Se nao superar, os papeis nao reagem de
forma mensuravelmente diferente e a camada nao entra em sinal nenhum.

LEIA A CIRCULARIDADE (obs/externo.py explica): a proxy de surpresa e o proprio
movimento do DXY/HSI no dia. A cadeia de afetacao ja regride contra esses
drivers todo dia. Entao a pergunta aqui e estreita: a exposicao discrimina
MAIS nos dias de divulgacao do que nos demais?
"""
from __future__ import annotations
import bisect, os, random, statistics as st, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from obs import drivers, externo                                # noqa: E402
from obs.db import connect                                      # noqa: E402

PERMS = 2000


def abnormais():
    con = connect()
    rows = con.execute("SELECT ticker,date,close FROM prices ORDER BY ticker,date").fetchall()
    con.close()
    by = {}
    for r in rows:
        by.setdefault(r["ticker"], []).append((r["date"], r["close"]))
    ret = {t: {s[i][0]: s[i][1] / s[i - 1][1] - 1 for i in range(1, len(s)) if s[i - 1][1]}
           for t, s in by.items()}
    alld = sorted({d for r in ret.values() for d in r})
    abn = {t: {} for t in ret}
    for d in alld:
        v = {t: ret[t][d] for t in ret if d in ret[t]}
        if len(v) < 8:
            continue
        m = st.fmean(v.values())
        for t, x in v.items():
            abn[t][d] = x - m
    return abn


def main():
    abn = abnormais()
    con = connect(); dret = drivers.driver_returns(con); con.close()
    rng = random.Random(13)
    print(f"{len(abn)} papeis\n")
    print(f"{'evento':<14} {'instr':<6} {'n':>4} {'dispersao':>11} {'nula':>10} {'p':>8}")
    print("-" * 60)

    for ev, cfg in externo.EVENTOS.items():
        pares = externo.proxy(ev, dret)
        if len(pares) < 30:
            print(f"{ev:<14} {cfg['instr']:<6} {len(pares):>4}  (poucos eventos)")
            continue
        datas = [d for d, _ in pares]
        surps = [s for _, s in pares]

        pre = {}
        for tkr, serie in abn.items():
            ds = sorted(serie)
            idx, ys = [], []
            for k, d in enumerate(datas):
                j = bisect.bisect_left(ds, d)
                if j < len(ds) and ds[j] == d:
                    idx.append(k); ys.append(serie[d])
            if len(ys) >= 20:
                pre[tkr] = (idx, ys)
        if len(pre) < 8:
            print(f"{ev:<14} {cfg['instr']:<6} {len(pares):>4}  (poucos papeis casados)")
            continue

        def betas(sv):
            out = {}
            for tkr, (idx, ys) in pre.items():
                xs = [sv[k] for k in idx]
                mx, my = st.fmean(xs), st.fmean(ys)
                den = sum((x - mx) ** 2 for x in xs)
                if den > 0:
                    out[tkr] = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
            return out

        real = st.pstdev(list(betas(surps).values()))
        nul = []
        for _ in range(PERMS):
            e = surps[:]; rng.shuffle(e)
            b = betas(e)
            if b:
                nul.append(st.pstdev(list(b.values())))
        p = sum(1 for x in nul if x >= real) / len(nul)
        sig = "  SIG" if p < 0.05 else ""
        n_cas = len(next(iter(pre.values()))[1])
        print(f"{ev:<14} {cfg['instr']:<6} {n_cas:>4} {real:>11.5f} {st.fmean(nul):>10.5f} {p:>8.3f}{sig}")

    print("\n[p < 0,05 = os papeis reagem diferente; senao, a camada nao entra em sinal]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
