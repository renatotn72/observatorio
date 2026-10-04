#!/usr/bin/env python3
"""A data aproximada e a culpada pelo p = 0.508?

A data de divulgacao usada e o dia 10 rolado para dia util -- o IBGE publica
calendario proprio e a data varia. Se o efeito existir mas a data errar por
1-2 dias, uma JANELA mais larga em torno da data o recupera; se a janela larga
tambem nao achar nada, o problema nao era a data.

Testa o retorno anormal ACUMULADO em janelas [0], [0,+1], [0,+2], [-1,+1].
"""
from __future__ import annotations
import bisect, os, random, statistics as st, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from obs import surpresa                                        # noqa: E402
from obs.db import connect                                      # noqa: E402

PERMS = 2000


def carrega():
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


def acumula(serie, ds, d0, ini, fim):
    """Soma o retorno anormal de ini..fim pregoes em torno da data d0."""
    j = bisect.bisect_left(ds, d0)
    tot, n = 0.0, 0
    for k in range(j + ini, j + fim + 1):
        if 0 <= k < len(ds):
            tot += serie[ds[k]]; n += 1
    return tot if n else None


def avalia(datas, surps, abn, ini, fim, rng):
    pre = {}
    for tkr, serie in abn.items():
        ds = sorted(serie)
        idx, ys = [], []
        for k, d in enumerate(datas):
            v = acumula(serie, ds, d, ini, fim)
            if v is not None:
                idx.append(k); ys.append(v)
        if len(ys) >= 8:
            pre[tkr] = (idx, ys)
    if not pre:
        return None

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
    return {"disp": real, "nula": st.fmean(nul), "p": p, "n": len(pre)}


def main():
    abn = carrega()
    linhas = surpresa.listar("IPCA")
    datas = [surpresa.data_divulgacao("IPCA", l["referencia"]) for l in linhas]
    surps = [l["surpresa"] for l in linhas]
    rng = random.Random(7)
    print(f"{len(linhas)} divulgacoes do IPCA | {len(abn)} papeis\n")
    print(f"{'janela':>12} {'dispersao':>11} {'nula':>10} {'p':>8}")
    print("-" * 46)
    for ini, fim, rot in [(0, 0, "[0]"), (0, 1, "[0,+1]"), (0, 2, "[0,+2]"),
                          (-1, 1, "[-1,+1]"), (-1, 2, "[-1,+2]")]:
        r = avalia(datas, surps, abn, ini, fim, rng)
        if r is None:
            print(f"{rot:>12}  (sem dados)"); continue
        sig = "  SIG" if r["p"] < 0.05 else ""
        print(f"{rot:>12} {r['disp']:>11.5f} {r['nula']:>10.5f} {r['p']:>8.3f}{sig}")
    print("\nSe NENHUMA janela passar, o problema nao era a data aproximada.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
