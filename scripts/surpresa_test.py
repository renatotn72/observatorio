#!/usr/bin/env python3
"""A dispersao dos betas de surpresa e real ou acaso?

Com 19 observacoes por papel, betas com sinais diferentes aparecem por puro
ruido. A nula: embaralhar as surpresas entre as datas de divulgacao, mantendo
os retornos no lugar. Se a dispersao real dos betas nao superar a nula, o
padrao economico bonito (MGLU3 negativo, VALE3 positivo) e coincidencia.
"""
from __future__ import annotations
import os, random, statistics as st, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from obs import surpresa                                        # noqa: E402
from obs.db import connect                                      # noqa: E402

PERMS = 2000


def retornos_nas_datas(datas, abn):
    """Pre-computa os retornos de cada papel nas datas de divulgacao.

    Isto sai do laco de permutacao de proposito: as DATAS e os RETORNOS sao
    fixos -- so as surpresas embaralham. Reordenar a serie dentro do laco
    fazia 2000 permutacoes x 131 datas x 10 papeis de trabalho redundante e
    estourava o tempo.
    """
    import bisect
    out = {}
    for tkr, serie in abn.items():
        ds = sorted(serie)
        ys, idx = [], []
        for k, d in enumerate(datas):
            j = bisect.bisect_left(ds, d)
            if j >= len(ds):
                continue
            ys.append(serie[ds[j]]); idx.append(k)
        if len(ys) >= 8:
            out[tkr] = (idx, ys)
    return out


def betas_rapido(surps, pre):
    out = {}
    for tkr, (idx, ys) in pre.items():
        xs = [surps[k] for k in idx]
        mx, my = st.fmean(xs), st.fmean(ys)
        den = sum((x - mx) ** 2 for x in xs)
        if den <= 0:
            continue
        out[tkr] = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
    return out


def main():
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

    ind = sys.argv[1] if len(sys.argv) > 1 else "IPCA"
    linhas = surpresa.listar(ind)
    datas = [surpresa.data_divulgacao(ind, l["referencia"]) for l in linhas]
    surps = [l["surpresa"] for l in linhas]
    print(f"=== {ind} === {len(linhas)} divulgacoes | {len(abn)} papeis")

    pre = retornos_nas_datas(datas, abn)
    print(f"papeis com >= 8 divulgacoes casadas: {len(pre)}")
    if not pre:
        print("nenhum papel com historico suficiente"); return 1
    print(f"divulgacoes casadas por papel: {st.median(len(v[1]) for v in pre.values()):.0f}\n")

    real = betas_rapido(surps, pre)
    disp_real = st.pstdev(list(real.values()))

    rng = random.Random(11)
    nulas = []
    for _ in range(PERMS):
        emb = surps[:]
        rng.shuffle(emb)
        b = betas_rapido(emb, pre)
        if b:
            nulas.append(st.pstdev(list(b.values())))

    p = sum(1 for x in nulas if x >= disp_real) / len(nulas)
    print("DISPERSAO TRANSVERSAL DOS BETAS DE SURPRESA")
    print("=" * 62)
    print(f"  observada        : {disp_real:.5f}")
    print(f"  nula (media)     : {st.fmean(nulas):.5f}")
    print(f"  nula (percentil 95): {sorted(nulas)[int(.95*len(nulas))]:.5f}")
    print(f"  p-valor          : {p:.3f}   [< 0.05 = dispersao real]")
    print()
    if p < 0.05:
        print("  -> os papeis REAGEM DIFERENTE a surpresa de inflacao.")
        print("     A camada de surpresa tem conteudo transversal.")
    else:
        print(f"  -> NAO distinguivel de acaso com {len(linhas)} divulgacoes.")
        print("     O padrao economicamente coerente (MGLU3 negativo por ser")
        print("     varejo alavancado, VALE3 positivo por exportar) NAO se")
        print("     sustenta. Com 131 divulgacoes ja nao e falta de amostra.")
        print()
        print("     SUSPEITO PRINCIPAL: a data de divulgacao e aproximada")
        print("     (dia 10 rolado para dia util). O IBGE publica calendario")
        print("     proprio e a data varia -- errar o dia borra um estudo de")
        print("     evento que mede reacao no MESMO dia. Antes de concluir que")
        print("     nao ha efeito, use as datas reais do calendario do IBGE.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
