#!/usr/bin/env python3
"""Existe lead-lag ENTRE acoes? O movimento de A hoje preve o de B amanha?

O risco aqui e maior que o do resto do projeto: com 18 acoes ha 306 pares
ordenados. Testar todos e anunciar o melhor encontra "significancia" por puro
acaso -- com 306 testes a 5%, ~15 pares passam sem que exista nada.

Por isso NAO procuramos o melhor par. Comparamos a DISTRIBUICAO dos 306 ICs
observados contra a distribuicao sob a hipotese nula, gerada embaralhando o
tempo em blocos (preserva autocorrelacao de cada serie, destroi a relacao
entre elas). Se a distribuicao real for mais larga que a nula, existe
estrutura de lead-lag. Se coincidir, nao existe e qualquer par "bom" e sorte.

Alvo: retorno RESIDUAL (removida a media transversal). Sem isso o fator comum
de mercado cria lead-lag espurio entre tudo e todos.
"""
from __future__ import annotations
import math
import os
import random
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.exposure_test import ACOES, daily_returns   # noqa: E402
from scripts.leadlag import fetch                        # noqa: E402

PERMS = 300
BLOCK = 10          # blocos de 10 pregoes no embaralhamento


def ranks(v: list[float]) -> list[float]:
    order = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def pearson(x: list[float], y: list[float]) -> float:
    n = len(x)
    mx, my = st.fmean(x), st.fmean(y)
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    den = math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y))
    return num / den if den else 0.0


def block_shuffle(v: list[float], rng: random.Random) -> list[float]:
    blocks = [v[i:i + BLOCK] for i in range(0, len(v), BLOCK)]
    rng.shuffle(blocks)
    return [x for b in blocks for x in b]


def main():
    print("Baixando precos...")
    px = {}
    for nm, sym in ACOES.items():
        s = fetch(sym, "2y")
        if len(s) > 200:
            px[nm] = s
    print(f"  {len(px)} acoes\n")

    ret = {k: daily_returns(v) for k, v in px.items()}
    dates = sorted(set.intersection(*(set(r) for r in ret.values())))
    print(f"{len(dates)} pregoes em comum")

    # residuo transversal
    resid = {k: [] for k in ret}
    for d in dates:
        vals = {k: ret[k][d] for k in ret}
        m = st.fmean(vals.values())
        for k, v in vals.items():
            resid[k].append(v - m)

    names = sorted(resid)
    rk = {k: ranks(resid[k]) for k in names}

    # --- ICs observados: resid_A[t] -> resid_B[t+1] ---
    obs = []
    for a in names:
        for b in names:
            if a == b:
                continue
            x = rk[a][:-1]
            y = rk[b][1:]
            obs.append((pearson(x, y), a, b))

    ics = [o[0] for o in obs]
    print(f"{len(ics)} pares ordenados testados\n")

    # --- nula por embaralhamento em blocos ---
    rng = random.Random(7)
    null = []
    for _ in range(PERMS):
        a, b = rng.sample(names, 2)
        xs = block_shuffle(resid[a], rng)
        x = ranks(xs)[:-1]
        y = rk[b][1:]
        null.append(pearson(x, y))

    print("DISTRIBUICAO DOS ICs DE LEAD-LAG")
    print("=" * 58)
    print(f"{'':<12} {'media':>9} {'desvio':>9} {'min':>9} {'max':>9}")
    print(f"{'observado':<12} {st.fmean(ics):>+9.4f} {st.pstdev(ics):>9.4f} "
          f"{min(ics):>+9.4f} {max(ics):>+9.4f}")
    print(f"{'nula':<12} {st.fmean(null):>+9.4f} {st.pstdev(null):>9.4f} "
          f"{min(null):>+9.4f} {max(null):>+9.4f}")

    ratio = st.pstdev(ics) / st.pstdev(null) if st.pstdev(null) else float("nan")
    print(f"\nrazao de desvios (observado / nula): {ratio:.3f}")
    print("  ~1.0  -> nenhuma estrutura: os 'melhores pares' sao acaso")
    print("  >1.2  -> existe lead-lag real a explorar")

    # quantos pares batem o maximo da nula? (controle de familia)
    thr = sorted(null)[int(0.975 * len(null))]
    strong = [o for o in obs if abs(o[0]) > abs(thr)]
    print(f"\nlimiar da nula (97.5%): {thr:+.4f}")
    print(f"pares acima dele: {len(strong)} de {len(obs)} "
          f"({100*len(strong)/len(obs):.1f}%)  [esperado por acaso: ~5%]")

    print("\n--- 6 pares de maior |IC| (NAO use isso como estrategia) ---")
    for ic, a, b in sorted(obs, key=lambda o: -abs(o[0]))[:6]:
        print(f"  {a:>7} (T) -> {b:<7} (T+1)   IC={ic:+.4f}")
    print("\nCom 306 testes, os extremos de uma distribuicao SEM sinal tambem")
    print("parecem impressionantes. So a comparacao com a nula decide.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
