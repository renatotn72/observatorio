"""A direcao aparece em horizonte mais longo? D+1, D+5, D+20.

O projeto mira D+1. Se o efeito dos drivers existir mas for lento, ele
apareceria em D+5 ou D+20. Testa os tres e reporta TODOS -- tres testes a 5%
dao ~14% de chance de um falso positivo, entao uma aprovacao isolada aqui
pediria replicacao antes de virar produto.

Alvo acumulado: soma dos retornos anormais de D+1 ate D+h, classificada por
K_SIGMA * sigma * sqrt(h) -- a escala do desvio cresce com a raiz do
horizonte, senao h=20 classificaria quase tudo como movimento grande.
"""
import sys

sys.path.insert(0, "/mnt/nvmep2/home/rtnati/Downloads/projeto_final/observatorio")
import math                                                   # noqa: E402
import statistics as st                                       # noqa: E402

import numpy as np                                            # noqa: E402

from obs import drivers                                       # noqa: E402
from obs.db import connect                                    # noqa: E402
from obs.label import K_SIGMA, MIN_SIGMA_OBS, abnormal_returns  # noqa: E402
from obs.prices import returns_by_date                        # noqa: E402
from direcao_test import REESTIMA, avalia                     # noqa: E402

HORIZONTES = (1, 5, 20)


def constroi_h(h: int):
    con = connect()
    rets = returns_by_date(con)
    ab = abnormal_returns(con)
    dret = drivers.driver_returns(con)
    con.close()
    datas_drv = sorted(set.intersection(*[set(v) for v in dret.values()]))
    sig: dict[str, dict[str, float]] = {}
    for tkr, serie in ab.items():
        ds, vals, acc = sorted(serie), [], {}
        for d in ds:
            if len(vals) >= MIN_SIGMA_OBS:
                s = st.pstdev(vals)
                if s > 0:
                    acc[d] = s
            vals.append(serie[d])
        sig[tkr] = acc

    Z, Y, D = [], [], []
    exposures = None
    for i, dia in enumerate(datas_drv):
        if i % REESTIMA == 0:
            exposures = drivers.fit_exposures(rets, dia, persist=False)
        if not exposures:
            continue
        for tkr, z in drivers.driver_signal(exposures, dret, dia).items():
            serie = ab.get(tkr) or {}
            fut = sorted(d for d in serie if d > dia)[:h]
            if len(fut) < h:
                continue
            s = sig.get(tkr, {}).get(fut[0])
            if not s:
                continue
            acum = sum(serie[d] for d in fut)
            lim = K_SIGMA * s * math.sqrt(h)
            Z.append(z)
            Y.append(1 if acum > lim else (-1 if acum < -lim else 0))
            D.append(fut[-1])
    return np.array(Z), np.array(Y), D


def main():
    print(f"{'h':>3}{'cabeca':<9}{'n_oos':>8}{'base':>8}{'AUC':>8}"
          f"{'skill':>9}{'prec@10%':>10}{'IC95':>16}")
    aprovados = 0
    for h in HORIZONTES:
        Z, Y, D = constroi_h(h)
        for nome, alvo in (("ALTA", (Y == 1).astype(float)),
                           ("QUEDA", (Y == -1).astype(float))):
            r = avalia(Z, alvo, D, nome)
            if r is None:
                continue
            passa = (r["auc"] > 0.52 and r["skill"] > 0
                     and r["ic95"][0] > 100 * r["taxa_base"])
            aprovados += passa
            print(f"{h:>3}  {nome:<7}{r['n_oos']:>8}{100*r['taxa_base']:>7.1f}"
                  f"{r['auc']:>8.4f}{r['skill']:>+9.4f}"
                  f"{100*r['prec_topo10']:>9.1f}"
                  f"   [{r['ic95'][0]:.1f}, {r['ic95'][1]:.1f}]"
                  f"  {'PASSOU' if passa else ''}", flush=True)
    print(f"\n{aprovados} de {2*len(HORIZONTES)} testes passaram.")
    print("Com 6 testes a 5%, ~0.3 falso positivo esperado.")


if __name__ == "__main__":
    main()
