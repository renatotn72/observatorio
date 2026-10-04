#!/usr/bin/env python3
"""O resultado do Payroll e descoberta ou circularidade?

A proxy de surpresa E o movimento do DXY no MESMO dia do retorno da acao.
Isso mede exposicao contemporanea, nao previsao. Se a dispersao dos betas for
igualmente alta em dias ALEATORIOS, nao ha nada de especial no payroll: o que
o teste capturou foi exposicao ao dolar, que a cadeia de afetacao ja conhece.

CONTROLE: mesma quantidade de dias, sorteados fora das datas de divulgacao.
"""
from __future__ import annotations
import os, random, statistics as st, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from obs import drivers, externo                                # noqa: E402
from scripts.externo_test import abnormais                      # noqa: E402
from obs.db import connect                                      # noqa: E402

AMOSTRAS = 400


def disp_betas(datas, abn, dret_dxy, sd):
    pre = {}
    for tkr, serie in abn.items():
        xs, ys = [], []
        for d in datas:
            if d in serie and d in dret_dxy:
                xs.append(dret_dxy[d] / sd); ys.append(serie[d])
        if len(ys) >= 20:
            pre[tkr] = (xs, ys)
    if len(pre) < 8:
        return None
    out = {}
    for tkr, (xs, ys) in pre.items():
        mx, my = st.fmean(xs), st.fmean(ys)
        den = sum((x - mx) ** 2 for x in xs)
        if den > 0:
            out[tkr] = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
    return st.pstdev(list(out.values())) if out else None


def main():
    abn = abnormais()
    con = connect(); dret = drivers.driver_returns(con); con.close()
    dxy = dret.get("DXY") or {}
    sd = st.pstdev(list(dxy.values())) or 1.0

    pares = externo.proxy("Payroll EUA", dret)
    dpay = [d for d, _ in pares]
    real = disp_betas(dpay, abn, dxy, sd)

    # universo de dias NAO-payroll com dado em todos os papeis
    todos = sorted(set(dxy) & set.intersection(*[set(v) for v in abn.values()]))
    fora = [d for d in todos if d not in set(dpay)]
    rng = random.Random(21)
    amostras = []
    for _ in range(AMOSTRAS):
        amostras.append(disp_betas(rng.sample(fora, len(dpay)), abn, dxy, sd))
    amostras = [a for a in amostras if a]

    print("DISPERSAO DOS BETAS AO DOLAR")
    print("=" * 58)
    print(f"  dias de payroll ({len(dpay)})   : {real:.5f}")
    print(f"  dias aleatorios (media)    : {st.fmean(amostras):.5f}")
    print(f"  dias aleatorios (p95)      : {sorted(amostras)[int(.95*len(amostras))]:.5f}")
    p = sum(1 for a in amostras if a >= real) / len(amostras)
    print(f"  p-valor contra dias comuns : {p:.3f}")
    print()
    if p < 0.05:
        print("  -> o payroll discrimina MAIS que um dia comum: ha algo especifico.")
    else:
        print("  -> indistinguivel de um dia qualquer. O p = 0,000 do teste anterior")
        print("     era CIRCULARIDADE: a proxy e o movimento do dolar, e a dispersao")
        print("     dos betas ao dolar e a mesma em qualquer dia. Nao e descoberta.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
